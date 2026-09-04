from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Callable
import logging
import time

from jzk.domain.data_loader import get_donor_display_info
from jzk.domain.preference.schema import field_short_label
from jzk.domain.preference.scorer import FieldScore, Ranker
from jzk.domain.preference.match_snapshot import build_match_snapshot_item
from jzk.domain.preference.result_types import MatchSnapshotItem, RankedCandidateRef
from jzk.domain.preference.validate import PreferenceProfile

logger = logging.getLogger(__name__)

PREFER_HIT_SCORE = 0.8


def _jsonable(value: Any) -> Any:
    """PostgreSQL NUMERIC 会变成 Decimal，不能直接 json.dumps。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(x) for x in value]
    return value


@dataclass
class MatchResult:
    candidates: list[dict[str, Any]]
    match_level: str
    bottlenecks: list[dict[str, Any]]
    skipped: bool
    filtered_count: int
    ranked_count: int | None = None
    model_version: str = ""
    checkpoint_sha256: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    prefer_hits: list[dict[str, Any]] = field(default_factory=list)
    ranked_refs: list[RankedCandidateRef] = field(default_factory=list)
    snapshot_items: list[MatchSnapshotItem] = field(default_factory=list)


def diagnose_bottlenecks(profile: PreferenceProfile, count_fn) -> list[dict]:
    """逐个把 must 放宽为 prefer，看能恢复多少人。count_fn 吃的是画像，不是 SQL。"""
    must_fields = [f for f, a in profile.attributes.items() if a.constraint == "must"]
    results = []
    for field in must_fields:
        clone = profile.model_copy(deep=True)
        clone.attributes[field].constraint = "prefer"
        recovered = int(count_fn(clone))
        results.append({"field": field, "recovered": recovered})
    results.sort(key=lambda x: x["recovered"], reverse=True)
    return results


def _reason(parts: list[FieldScore]) -> str:
    hits = [p.field for p in parts if p.s >= 0.8]
    if not hits:
        return "综合相似度排序"
    return "匹配：" + "、".join(hits)


def _field_match(parts: list[FieldScore]) -> dict[str, dict[str, Any]]:
    out = {}
    for p in parts:
        user = p.target
        if isinstance(user, dict) and "min" in user:
            user = str({k: v for k, v in user.items() if v is not None})
        elif isinstance(user, list):
            user = "、".join(str(x) for x in user)
        out[p.field] = {
            "match": p.s >= 1.0 - 1e-9,
            "actual": _jsonable(p.actual),
            "user": user,
        }
    return out


def _candidate_dict(row: dict[str, Any], score: float, parts: list[FieldScore], rank: int) -> dict[str, Any]:
    return {
        "donor_info": get_donor_display_info(row),
        "score": round(float(score), 4),
        "match_pct": round(100 * float(score), 2),
        "reason": _reason(parts),
        "match_level": (
            "full"
            if parts and all(p.s >= 1.0 - 1e-9 for p in parts)
            else "high" if score >= 0.85
            else "medium" if score >= 0.70
            else "low"
        ),
        "field_match": _field_match(parts),
        "field_scores": [_jsonable(asdict(p)) for p in parts],
        "rank": rank,
    }


def _prefer_field_hit(candidate: dict[str, Any], field: str) -> bool:
    fm = (candidate.get("field_match") or {}).get(field) or {}
    if fm.get("match"):
        return True
    for part in candidate.get("field_scores") or []:
        if part.get("field") == field and float(part.get("s") or 0) >= PREFER_HIT_SCORE:
            return True
    return False


def compute_prefer_hits(
    profile: PreferenceProfile,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """在已过滤名单上计数 prefer 命中；不改变过滤结果。"""
    n = len(candidates)
    out: list[dict[str, Any]] = []
    for name, attr in profile.attributes.items():
        if getattr(attr, "constraint", None) != "prefer":
            continue
        hits = sum(1 for c in candidates if _prefer_field_hit(c, name))
        out.append({
            "field": name,
            "label": field_short_label(name),
            "hits": hits,
            "of": n,
        })
    return out


def _prefer_part_hit(parts: list[FieldScore], field: str) -> bool:
    return any(
        part.field == field and (part.s >= 1.0 - 1e-9 or part.s >= PREFER_HIT_SCORE)
        for part in parts
    )


def compute_prefer_hits_from_ranked(
    profile: PreferenceProfile,
    ranked: list[tuple[dict[str, Any], float, list[FieldScore]]],
) -> list[dict[str, Any]]:
    """直接从排序中间结果聚合，避免先组装所有候选详情。"""
    n = len(ranked)
    out: list[dict[str, Any]] = []
    for name, attr in profile.attributes.items():
        if getattr(attr, "constraint", None) != "prefer":
            continue
        hits = sum(1 for _row, _score, parts in ranked if _prefer_part_hit(parts, name))
        out.append({"field": name, "label": field_short_label(name), "hits": hits, "of": n})
    return out


def _internal_donor_id(row: dict[str, Any], fallback_rank: int) -> int:
    """生产数据使用 donor.donors.id；fallback 仅兼容无 ID 的单元测试/旧数据。"""
    for key in ("id", "donor_id", "_donor_id", "serial_no", "编号"):
        value = row.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return fallback_rank


def hydrate_ranked_candidates(
    profile: PreferenceProfile,
    refs: list[RankedCandidateRef],
    rows: list[dict[str, Any]],
    *,
    ranker: Ranker | None = None,
) -> list[dict[str, Any]]:
    """为一页引用批量组装详情，并严格恢复快照中的 rank/score。"""
    if not refs or not rows:
        return []
    if ranker is None:
        from jzk.domain.preference.ranker_factory import get_default_ranker

        ranker = get_default_ranker()
    scored = ranker.rank(profile, rows)
    by_id = {
        _internal_donor_id(row, index): (row, parts)
        for index, (row, _score, parts) in enumerate(scored, 1)
    }
    candidates: list[dict[str, Any]] = []
    for ref in refs:
        found = by_id.get(ref.donor_id)
        if found is None:
            continue
        row, parts = found
        candidates.append(_candidate_dict(row, ref.score, parts, ref.rank))
    return candidates


def match_profile(
    profile: PreferenceProfile,
    fetch_rows: Callable | None = None,
    count_rows: Callable | None = None,
    ranker: Ranker | None = None,
    log: bool = False,
    session_id: str = "",
    detail_limit: int | None = None,
    build_snapshot: bool = False,
) -> MatchResult:
    if not profile.attributes:
        return MatchResult(
            candidates=[],
            match_level="none",
            bottlenecks=[],
            skipped=True,
            filtered_count=0,
        )

    fetch = fetch_rows
    if fetch is None:
        raise TypeError("match_profile 需要 fetch_rows；生产路径由 matching.execute 注入")

    t0 = time.perf_counter()
    rows = fetch(profile)
    sql_ms = (time.perf_counter() - t0) * 1000
    if not rows:
        bottlenecks = diagnose_bottlenecks(profile, count_rows) if count_rows else []
        return MatchResult(
            candidates=[],
            match_level="none",
            bottlenecks=bottlenecks,
            skipped=False,
            filtered_count=0,
            timings={"sql_ms": round(sql_ms, 1)},
        )

    if ranker is None:
        from jzk.domain.preference.ranker_factory import get_default_ranker

        t_load = time.perf_counter()
        ranker = get_default_ranker()
        load_ms = (time.perf_counter() - t_load) * 1000
    else:
        load_ms = 0.0
    t1 = time.perf_counter()
    ranked = ranker.rank(profile, rows)
    rank_ms = (time.perf_counter() - t1) * 1000
    metadata_getter = getattr(ranker, "metadata", None)
    scoring_metadata = metadata_getter() if callable(metadata_getter) else None
    ranked_refs = [
        RankedCandidateRef(
            donor_id=_internal_donor_id(row, i + 1),
            rank=i + 1,
            score=round(float(score), 6),
        )
        for i, (row, score, _parts) in enumerate(ranked)
    ]
    snapshot_items = (
        [
            build_match_snapshot_item(
                row,
                donor_id=ranked_refs[index].donor_id,
                rank=ranked_refs[index].rank,
                score=ranked_refs[index].score,
                parts=parts,
            )
            for index, (row, _score, parts) in enumerate(ranked)
        ]
        if build_snapshot
        else []
    )
    detail_count = len(ranked) if detail_limit is None else max(0, min(detail_limit, len(ranked)))
    t2 = time.perf_counter()
    candidates = [
        _candidate_dict(row, score, parts, i + 1)
        for i, (row, score, parts) in enumerate(ranked[:detail_count])
    ]
    assemble_ms = (time.perf_counter() - t2) * 1000
    timings = {
        "sql_ms": round(sql_ms, 1),
        "ranker_load_ms": round(load_ms, 1),
        "rank_ms": round(rank_ms, 1),
        "assemble_ms": round(assemble_ms, 1),
        "filtered_count": float(len(rows)),
        "detail_hydrated_count": float(len(candidates)),
    }
    extra = getattr(ranker, "last_timings", None)
    if isinstance(extra, dict):
        timings.update(extra)
    logger.info("match_profile timings %s", timings)

    if log:
        from jzk.domain.preference.match_log import append_match_turn

        try:
            append_match_turn({
                "schema_version": "1.0",
                "session_id": session_id,
                "preference_profile": profile.model_dump(),
                "filtered_count": len(rows),
                "candidates": [
                    {
                        "donor_id": ranked_refs[index].donor_id,
                        "code": get_donor_display_info(row).get("code"),
                        "score": ranked_refs[index].score,
                        "rank": ranked_refs[index].rank,
                        "field_scores": [_jsonable(asdict(part)) for part in parts],
                        "attrs": {
                            part.field: _jsonable(part.actual) for part in parts
                        },
                    }
                    for index, (row, _score, parts) in enumerate(ranked)
                ],
            })
        except Exception:
            logger.exception("写入 match_log 失败")

    return MatchResult(
        candidates=candidates,
        match_level="full",
        bottlenecks=[],
        skipped=False,
        filtered_count=len(rows),
        ranked_count=len(ranked),
        model_version=(
            str(getattr(scoring_metadata, "model_version", ""))
            if scoring_metadata is not None
            else ""
        ),
        checkpoint_sha256=(
            str(getattr(scoring_metadata, "checkpoint_sha256", ""))
            if scoring_metadata is not None
            else ""
        ),
        timings=timings,
        prefer_hits=compute_prefer_hits_from_ranked(profile, ranked),
        ranked_refs=ranked_refs,
        snapshot_items=snapshot_items,
    )
