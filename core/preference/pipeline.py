from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from core.data_loader import get_donor_display_info
from core.preference.scorer import FieldScore, HeuristicRanker, Ranker
from core.preference.sql_filter import build_hard_filter_sql, diagnose_bottlenecks
from core.preference.validate import PreferenceProfile


@dataclass
class MatchResult:
    candidates: list[dict[str, Any]]
    match_level: str
    bottlenecks: list[dict[str, Any]]
    skipped: bool
    filtered_count: int


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
            "actual": p.actual,
            "user": user,
        }
    return out


def _candidate_dict(row: dict[str, Any], score: float, parts: list[FieldScore], rank: int) -> dict[str, Any]:
    mean_s = sum(p.s for p in parts) / len(parts) if parts else 0.0
    return {
        "donor_info": get_donor_display_info(row),
        "score": round(float(score), 4),
        "match_pct": round(100 * mean_s, 1),
        "reason": _reason(parts),
        "match_level": "full",
        "field_match": _field_match(parts),
        "field_scores": [asdict(p) for p in parts],
        "rank": rank,
    }


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
    ranker = ranker or HeuristicRanker()

    sql, params = build_hard_filter_sql(profile)
    rows = fetch(sql, params)
    if not rows:
        bottlenecks = diagnose_bottlenecks(profile, counter)
        return MatchResult(
            candidates=[],
            match_level="none",
            bottlenecks=bottlenecks,
            skipped=False,
            filtered_count=0,
        )

    ranked = ranker.rank(profile, rows)
    candidates = [
        _candidate_dict(row, score, parts, i + 1)
        for i, (row, score, parts) in enumerate(ranked)
    ]

    if log:
        from core.preference.match_log import append_match_turn

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

    return MatchResult(
        candidates=candidates,
        match_level="full",
        bottlenecks=[],
        skipped=False,
        filtered_count=len(rows),
    )
