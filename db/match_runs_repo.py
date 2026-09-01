"""PostgreSQL 严格匹配排名快照。"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

import config
from core.preference.result_types import MatchResultMeta, RankedCandidateRef
from db.pg import db_session, fetchone


class MatchRunValidationError(ValueError):
    pass


def canonical_profile_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def profile_digest(profile: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_profile_json(profile).encode("utf-8")).hexdigest()


def _validate(meta: MatchResultMeta, refs: Iterable[RankedCandidateRef]) -> list[RankedCandidateRef]:
    try:
        UUID(meta.result_set_id)
    except (TypeError, ValueError) as exc:
        raise MatchRunValidationError("result_set_id 必须是 UUID") from exc
    items = list(refs)
    if meta.total != len(items):
        raise MatchRunValidationError("total 与排名引用数量不一致")
    if meta.total > config.MATCH_RESULT_MAX_CANDIDATES:
        raise MatchRunValidationError("匹配候选数量超过允许上限")
    seen: set[int] = set()
    for expected_rank, ref in enumerate(items, 1):
        if ref.rank != expected_rank:
            raise MatchRunValidationError("rank 必须从 1 开始连续递增")
        if ref.donor_id <= 0 or ref.donor_id in seen:
            raise MatchRunValidationError("donor_id 必须为正整数且不能重复")
        if not math.isfinite(ref.score):
            raise MatchRunValidationError("score 必须是有限数值")
        seen.add(ref.donor_id)
    return items


def create_match_run(meta: MatchResultMeta, refs: Iterable[RankedCandidateRef]) -> MatchResultMeta:
    """幂等写入严格快照；相同 UUID 的内容不可被覆盖。"""
    items = _validate(meta, refs)
    donor_ids = [item.donor_id for item in items]
    scores = [round(float(item.score), 6) for item in items]
    profile_json = canonical_profile_json(meta.profile)
    digest = meta.profile_hash or profile_digest(meta.profile)
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            INSERT INTO app.match_runs (
                id, user_id, profile_json, profile_hash, model_version,
                dataset_version, total, donor_ids, scores, prefer_hits
            )
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO NOTHING
            RETURNING created_at
            """,
            (
                meta.result_set_id,
                meta.owner_user_id,
                profile_json,
                digest,
                meta.model_version,
                meta.dataset_version,
                meta.total,
                donor_ids,
                scores,
                json.dumps(meta.prefer_hits, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        if row is None:
            existing = fetchone(
                conn,
                """
                SELECT created_at FROM app.match_runs
                WHERE id = %s AND user_id = %s AND profile_hash = %s
                  AND donor_ids = %s AND scores = %s
                """,
                (meta.result_set_id, meta.owner_user_id, digest, donor_ids, scores),
            )
            if existing is None:
                raise MatchRunValidationError("result_set_id 已被其他快照占用")
            row = existing
    return replace(meta, profile_hash=digest, created_at=row["created_at"])


def get_match_run(result_set_id: str, owner_user_id: int) -> MatchResultMeta | None:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT id, user_id, profile_json, profile_hash, model_version,
                   dataset_version, total, prefer_hits, created_at
            FROM app.match_runs WHERE id = %s AND user_id = %s
            """,
            (result_set_id, owner_user_id),
        )
    if row is None:
        return None
    return MatchResultMeta(
        result_set_id=str(row["id"]),
        owner_user_id=int(row["user_id"]),
        total=int(row["total"]),
        profile=dict(row["profile_json"] or {}),
        profile_hash=str(row["profile_hash"]),
        model_version=str(row["model_version"]),
        dataset_version=str(row["dataset_version"]),
        prefer_hits=list(row["prefer_hits"] or []),
        created_at=row["created_at"],
    )


def get_match_run_page(
    result_set_id: str,
    owner_user_id: int,
    *,
    offset: int,
    limit: int,
) -> tuple[MatchResultMeta, list[RankedCandidateRef]] | None:
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), config.MATCH_RESULT_PAGE_SIZE_MAX))
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT id, user_id, profile_json, profile_hash, model_version,
                   dataset_version, total, prefer_hits, created_at,
                   donor_ids[%s:%s] AS page_ids,
                   scores[%s:%s] AS page_scores
            FROM app.match_runs WHERE id = %s AND user_id = %s
            """,
            (offset + 1, offset + limit, offset + 1, offset + limit, result_set_id, owner_user_id),
        )
    if row is None:
        return None
    meta = MatchResultMeta(
        result_set_id=str(row["id"]), owner_user_id=int(row["user_id"]),
        total=int(row["total"]), profile=dict(row["profile_json"] or {}),
        profile_hash=str(row["profile_hash"]), model_version=str(row["model_version"]),
        dataset_version=str(row["dataset_version"]), prefer_hits=list(row["prefer_hits"] or []),
        created_at=row["created_at"],
    )
    ids = list(row.get("page_ids") or [])
    scores = list(row.get("page_scores") or [])
    refs = [
        RankedCandidateRef(int(donor_id), offset + index + 1, round(float(score), 6))
        for index, (donor_id, score) in enumerate(zip(ids, scores))
    ]
    return meta, refs


def match_run_contains(result_set_id: str, owner_user_id: int, donor_id: int) -> bool:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT %s = ANY(donor_ids) AS present
            FROM app.match_runs WHERE id = %s AND user_id = %s
            """,
            (donor_id, result_set_id, owner_user_id),
        )
    return bool(row and row["present"])


def delete_match_run(result_set_id: str, owner_user_id: int) -> bool:
    with db_session() as conn:
        row = fetchone(
            conn,
            "DELETE FROM app.match_runs WHERE id = %s AND user_id = %s RETURNING id",
            (result_set_id, owner_user_id),
        )
    return row is not None


def cleanup_expired_match_runs(*, retention_days: int | None = None, batch_size: int = 1000) -> int:
    days = config.MATCH_SNAPSHOT_RETENTION_DAYS if retention_days is None else max(1, retention_days)
    size = max(1, min(batch_size, 10000))
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            WITH victims AS (
                SELECT id FROM app.match_runs
                WHERE created_at < now() - (%s * interval '1 day')
                ORDER BY created_at LIMIT %s
            ), deleted AS (
                DELETE FROM app.match_runs m USING victims v
                WHERE m.id = v.id RETURNING m.id
            )
            SELECT COUNT(*) AS count FROM deleted
            """,
            (days, size),
        )
    return int(row["count"]) if row else 0

