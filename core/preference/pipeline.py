from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Callable
import logging
import time

from core.data_loader import get_donor_display_info
from core.preference.schema import field_short_label
from core.preference.scorer import FieldScore, Ranker
from core.preference.sql_filter import build_hard_filter_sql, diagnose_bottlenecks
from core.preference.validate import PreferenceProfile

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
    timings: dict[str, float] = field(default_factory=dict)
    prefer_hits: list[dict[str, Any]] = field(default_factory=list)


def default_fetch(sql: str, params: tuple) -> list[dict[str, Any]]:
    from db.pg import db_session, fetchall

    with db_session() as conn:
        return fetchall(conn, sql, params)


def default_count(sql: str, params: tuple) -> int:
    from db.pg import db_session, fetchone

    count_sql = sql.replace("SELECT *", "SELECT COUNT(*) AS c", 1)
    with db_session() as conn:
        row = fetchone(conn, count_sql, params)
        return int(row["c"]) if row else 0


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


def match_profile(
    profile: PreferenceProfile,
    fetch_rows: Callable | None = None,
    count_rows: Callable | None = None,
    ranker: Ranker | None = None,
    log: bool = False,
    session_id: str = "",
) -> MatchResult:
    if not profile.attributes:
        return MatchResult(
            candidates=[],
            match_level="none",
            bottlenecks=[],
            skipped=True,
            filtered_count=0,
        )

    fetch = fetch_rows or default_fetch
    counter = count_rows or default_count

    sql, params = build_hard_filter_sql(profile)
    t0 = time.perf_counter()
    rows = fetch(sql, params)
    sql_ms = (time.perf_counter() - t0) * 1000
    if not rows:
        bottlenecks = diagnose_bottlenecks(profile, counter)
        return MatchResult(
            candidates=[],
            match_level="none",
            bottlenecks=bottlenecks,
            skipped=False,
            filtered_count=0,
            timings={"sql_ms": round(sql_ms, 1)},
        )

    if ranker is None:
        from core.preference.v2_ranker import get_default_ranker

        t_load = time.perf_counter()
        ranker = get_default_ranker()
        load_ms = (time.perf_counter() - t_load) * 1000
    else:
        load_ms = 0.0
    t1 = time.perf_counter()
    ranked = ranker.rank(profile, rows)
    rank_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    candidates = [
        _candidate_dict(row, score, parts, i + 1)
        for i, (row, score, parts) in enumerate(ranked)
    ]
    assemble_ms = (time.perf_counter() - t2) * 1000
    timings = {
        "sql_ms": round(sql_ms, 1),
        "ranker_load_ms": round(load_ms, 1),
        "rank_ms": round(rank_ms, 1),
        "assemble_ms": round(assemble_ms, 1),
        "filtered_count": float(len(rows)),
    }
    extra = getattr(ranker, "last_timings", None)
    if isinstance(extra, dict):
        timings.update(extra)
    logger.info("match_profile timings %s", timings)

    if log:
        from core.preference.match_log import append_match_turn

        try:
            append_match_turn({
                "schema_version": "1.0",
                "session_id": session_id,
                "preference_profile": profile.model_dump(),
                "filtered_count": len(rows),
                "candidates": [
                    {
                        "code": c["donor_info"].get("code"),
                        "score": c["score"],
                        "rank": c["rank"],
                        "field_scores": c["field_scores"],
                        "attrs": {
                            p["field"]: p["actual"] for p in c["field_scores"]
                        },
                    }
                    for c in candidates
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
        timings=timings,
        prefer_hits=compute_prefer_hits(profile, candidates),
    )
