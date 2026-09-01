"""PostgreSQL 严格匹配排名快照。"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import UUID

from psycopg.types.json import Jsonb

import config
from core.preference.match_snapshot import validate_match_snapshot_item
from core.preference.result_types import MatchResultMeta, MatchSnapshotItem, RankedCandidateRef
from db.pg import db_session, fetchall, fetchone


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


def _validate_snapshot_items(
    refs: list[RankedCandidateRef],
    snapshot_items: Iterable[MatchSnapshotItem] | None,
) -> list[MatchSnapshotItem]:
    items = list(snapshot_items or [])
    if not items:
        return []
    if len(items) != len(refs):
        raise MatchRunValidationError("完整候选快照数量与排名数量不一致")
    for ref, item in zip(refs, items):
        validate_match_snapshot_item(item)
        if (item.donor_id, item.rank, round(item.score, 6)) != (
            ref.donor_id,
            ref.rank,
            round(ref.score, 6),
        ):
            raise MatchRunValidationError("候选快照与排名引用不一致")
    return items


def create_match_run(
    meta: MatchResultMeta,
    refs: Iterable[RankedCandidateRef],
    snapshot_items: Iterable[MatchSnapshotItem] | None = None,
) -> MatchResultMeta:
    """原子写入完整排名快照；只有全部明细校验成功后才标记 ready。"""
    items = _validate(meta, refs)
    frozen_items = _validate_snapshot_items(items, snapshot_items)
    donor_ids = [item.donor_id for item in items]
    scores = [round(float(item.score), 6) for item in items]
    profile_json = canonical_profile_json(meta.profile)
    digest = meta.profile_hash or profile_digest(meta.profile)
    source = "native" if frozen_items or not items else "legacy_backfill"
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            INSERT INTO app.match_runs (
                id, user_id, profile_json, profile_hash, model_version,
                dataset_version, total, donor_ids, scores, prefer_hits,
                status, snapshot_schema_version, snapshot_source
            )
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb,
                    'building', 1, %s)
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
                source,
            ),
        )
        if row is None:
            existing = fetchone(
                conn,
                """
                SELECT created_at, ready_at, status, snapshot_schema_version, snapshot_source,
                       (SELECT COUNT(*) FROM app.match_run_items i WHERE i.match_run_id = m.id)
                         AS item_count
                FROM app.match_runs m
                WHERE m.id = %s AND user_id = %s AND profile_hash = %s
                  AND donor_ids = %s AND scores = %s
                """,
                (meta.result_set_id, meta.owner_user_id, digest, donor_ids, scores),
            )
            if existing is None:
                raise MatchRunValidationError("result_set_id 已被其他快照占用")
            if frozen_items and (
                existing["status"] != "ready" or int(existing["item_count"]) != meta.total
            ):
                raise MatchRunValidationError("result_set_id 对应的完整快照尚未就绪")
            return replace(
                meta,
                profile_hash=digest,
                status=str(existing["status"]),
                snapshot_schema_version=int(existing["snapshot_schema_version"]),
                snapshot_source=str(existing["snapshot_source"]),
                created_at=existing["created_at"],
                ready_at=existing["ready_at"],
            )

        if frozen_items or meta.total == 0:
            if frozen_items:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO app.match_run_items (
                            match_run_id, rank, donor_id, score, donor_code_snapshot,
                            donor_snapshot_json, match_explanation_json, snapshot_schema_version
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                meta.result_set_id,
                                item.rank,
                                item.donor_id,
                                round(float(item.score), 6),
                                item.donor_code_snapshot,
                                Jsonb(item.donor_snapshot),
                                Jsonb(item.match_explanation),
                                item.snapshot_schema_version,
                            )
                            for item in frozen_items
                        ],
                    )
            verified = fetchone(
                conn,
                """
                SELECT COUNT(*) AS count, MIN(rank) AS min_rank, MAX(rank) AS max_rank
                FROM app.match_run_items WHERE match_run_id = %s
                """,
                (meta.result_set_id,),
            )
            expected_min = 1 if meta.total else None
            expected_max = meta.total if meta.total else None
            if not verified or (
                int(verified["count"]) != meta.total
                or verified["min_rank"] != expected_min
                or verified["max_rank"] != expected_max
            ):
                raise MatchRunValidationError("完整候选快照写入校验失败")
            ready = fetchone(
                conn,
                """
                UPDATE app.match_runs
                SET status = 'ready', ready_at = now()
                WHERE id = %s AND status = 'building'
                RETURNING created_at, ready_at
                """,
                (meta.result_set_id,),
            )
            assert ready is not None
            return replace(
                meta,
                profile_hash=digest,
                status="ready",
                snapshot_schema_version=1,
                snapshot_source="native",
                created_at=ready["created_at"],
                ready_at=ready["ready_at"],
            )

    return replace(
        meta,
        profile_hash=digest,
        status="building",
        snapshot_schema_version=1,
        snapshot_source=source,
        created_at=row["created_at"],
    )


def get_match_run(result_set_id: str, owner_user_id: int) -> MatchResultMeta | None:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT id, user_id, profile_json, profile_hash, model_version,
                   dataset_version, total, prefer_hits, status,
                   snapshot_schema_version, snapshot_source, created_at, ready_at
            FROM app.match_runs WHERE id = %s AND user_id = %s AND status = 'ready'
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
        status=str(row.get("status") or "ready"),
        snapshot_schema_version=int(row.get("snapshot_schema_version") or 1),
        snapshot_source=str(row.get("snapshot_source") or "native"),
        created_at=row["created_at"],
        ready_at=row.get("ready_at"),
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
                   dataset_version, total, prefer_hits, status,
                   snapshot_schema_version, snapshot_source, created_at, ready_at,
                   donor_ids[%s:%s] AS page_ids,
                   scores[%s:%s] AS page_scores
            FROM app.match_runs WHERE id = %s AND user_id = %s AND status = 'ready'
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
        status=str(row.get("status") or "ready"),
        snapshot_schema_version=int(row.get("snapshot_schema_version") or 1),
        snapshot_source=str(row.get("snapshot_source") or "native"),
        created_at=row["created_at"], ready_at=row.get("ready_at"),
    )
    ids = list(row.get("page_ids") or [])
    scores = list(row.get("page_scores") or [])
    refs = [
        RankedCandidateRef(int(donor_id), offset + index + 1, round(float(score), 6))
        for index, (donor_id, score) in enumerate(zip(ids, scores))
    ]
    return meta, refs


def get_all_match_run_refs(
    result_set_id: str, owner_user_id: int
) -> tuple[MatchResultMeta, list[RankedCandidateRef]] | None:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT id, user_id, profile_json, profile_hash, model_version,
                   dataset_version, total, prefer_hits, status,
                   snapshot_schema_version, snapshot_source, created_at, ready_at,
                   donor_ids, scores
            FROM app.match_runs WHERE id = %s AND user_id = %s AND status = 'ready'
            """,
            (result_set_id, owner_user_id),
        )
    if row is None:
        return None
    meta = MatchResultMeta(
        result_set_id=str(row["id"]), owner_user_id=int(row["user_id"]),
        total=int(row["total"]), profile=dict(row["profile_json"] or {}),
        profile_hash=str(row["profile_hash"]), model_version=str(row["model_version"]),
        dataset_version=str(row["dataset_version"]), prefer_hits=list(row["prefer_hits"] or []),
        status=str(row.get("status") or "ready"),
        snapshot_schema_version=int(row.get("snapshot_schema_version") or 1),
        snapshot_source=str(row.get("snapshot_source") or "native"),
        created_at=row["created_at"], ready_at=row.get("ready_at"),
    )
    refs = [
        RankedCandidateRef(int(donor_id), index, round(float(score), 6))
        for index, (donor_id, score) in enumerate(
            zip(row.get("donor_ids") or [], row.get("scores") or []), 1
        )
    ]
    return meta, refs


def get_match_run_items_page(
    result_set_id: str,
    owner_user_id: int,
    *,
    offset: int,
    limit: int,
) -> tuple[MatchResultMeta, list[MatchSnapshotItem]] | None:
    """读取冻结排名页；候选当前状态不会改变这里的资料、rank 或 score。"""
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), config.MATCH_RESULT_PAGE_SIZE_MAX))
    with db_session() as conn:
        meta_row = fetchone(
            conn,
            """
            SELECT id, user_id, profile_json, profile_hash, model_version,
                   dataset_version, total, prefer_hits, status,
                   snapshot_schema_version, snapshot_source, created_at, ready_at
            FROM app.match_runs
            WHERE id = %s AND user_id = %s AND status = 'ready'
            """,
            (result_set_id, owner_user_id),
        )
        if meta_row is None:
            return None
        rows = fetchall(
            conn,
            """
            SELECT rank, donor_id, score, donor_code_snapshot,
                   donor_snapshot_json, match_explanation_json,
                   snapshot_schema_version
            FROM app.match_run_items
            WHERE match_run_id = %s AND rank > %s
            ORDER BY rank
            LIMIT %s
            """,
            (result_set_id, offset, limit),
        )
    meta = MatchResultMeta(
        result_set_id=str(meta_row["id"]),
        owner_user_id=int(meta_row["user_id"]),
        total=int(meta_row["total"]),
        profile=dict(meta_row["profile_json"] or {}),
        profile_hash=str(meta_row["profile_hash"]),
        model_version=str(meta_row["model_version"]),
        dataset_version=str(meta_row["dataset_version"]),
        prefer_hits=list(meta_row["prefer_hits"] or []),
        status=str(meta_row["status"]),
        snapshot_schema_version=int(meta_row["snapshot_schema_version"]),
        snapshot_source=str(meta_row["snapshot_source"]),
        created_at=meta_row["created_at"],
        ready_at=meta_row["ready_at"],
    )
    items = [
        MatchSnapshotItem(
            donor_id=int(row["donor_id"]),
            rank=int(row["rank"]),
            score=round(float(row["score"]), 6),
            donor_code_snapshot=str(row["donor_code_snapshot"]),
            donor_snapshot=dict(row["donor_snapshot_json"] or {}),
            match_explanation=dict(row["match_explanation_json"] or {}),
            snapshot_schema_version=int(row["snapshot_schema_version"]),
        )
        for row in rows
    ]
    return meta, items


def match_run_is_expired(meta: MatchResultMeta, *, now: datetime | None = None) -> bool:
    if meta.created_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    created = meta.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created < current - timedelta(days=config.MATCH_SNAPSHOT_RETENTION_DAYS)


def match_run_contains(result_set_id: str, owner_user_id: int, donor_id: int) -> bool:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT EXISTS (
                SELECT 1 FROM app.match_run_items i
                WHERE i.match_run_id = m.id AND i.donor_id = %s
            ) AS present
            FROM app.match_runs m
            WHERE m.id = %s AND m.user_id = %s AND m.status = 'ready'
            """,
            (donor_id, result_set_id, owner_user_id),
        )
    return bool(row and row["present"])


def delete_match_run(result_set_id: str, owner_user_id: int) -> bool:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            DELETE FROM app.match_runs m
            WHERE m.id = %s AND m.user_id = %s
              AND NOT EXISTS (
                SELECT 1 FROM app.chat_messages cm WHERE cm.match_run_id = m.id
              )
            RETURNING id
            """,
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
                SELECT m.id FROM app.match_runs m
                WHERE (m.status = 'failed'
                       OR m.created_at < now() - (%s * interval '1 day'))
                  AND NOT EXISTS (
                    SELECT 1 FROM app.chat_messages cm WHERE cm.match_run_id = m.id
                  )
                ORDER BY m.created_at LIMIT %s
            ), deleted AS (
                DELETE FROM app.match_runs m USING victims v
                WHERE m.id = v.id RETURNING m.id
            )
            SELECT COUNT(*) AS count FROM deleted
            """,
            (days, size),
        )
    return int(row["count"]) if row else 0
