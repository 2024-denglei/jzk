"""Chat Outbox 的领取、租约 fencing、重试和数据库清理动作。"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from jzk import config
from jzk.db.pg import db_session, fetchone


class OutboxLeaseLost(RuntimeError):
    pass


_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|api[_-]?key\s*[:=]\s*\S+|sk-[a-z0-9_-]{8,})"
)


def _safe_error(error: Exception) -> str:
    return _SECRET_PATTERN.sub("[redacted]", " ".join(str(error).split()))[:500]


def claim_next_outbox(worker_id: str) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            """
            WITH candidate AS (
              SELECT id FROM app.outbox_events
              WHERE attempts < %s
                AND (
                  (status IN ('pending', 'failed') AND available_at <= now())
                  OR
                  (status = 'processing'
                   AND locked_at < now() - (%s * interval '1 second'))
                )
              ORDER BY available_at, id
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            UPDATE app.outbox_events event
            SET status = 'processing', attempts = attempts + 1,
                locked_by = %s, locked_at = now(), last_error = NULL
            FROM candidate
            WHERE event.id = candidate.id
            RETURNING event.*
            """,
            (
                config.CHAT_OUTBOX_MAX_ATTEMPTS,
                config.CHAT_OUTBOX_LEASE_SECONDS,
                worker_id,
            ),
        )


def complete_outbox(event_id: int, worker_id: str) -> None:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE app.outbox_events
            SET status = 'completed', processed_at = now(),
                locked_by = NULL, locked_at = NULL, last_error = NULL
            WHERE id = %s AND status = 'processing' AND locked_by = %s
            """,
            (event_id, worker_id),
        )
    if cur.rowcount != 1:
        raise OutboxLeaseLost("Outbox 任务租约已丢失")


def fail_outbox(event_id: int, worker_id: str, error: Exception, attempts: int) -> None:
    delay = min(
        config.CHAT_OUTBOX_RETRY_MAX_SECONDS,
        config.CHAT_OUTBOX_RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1)),
    )
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE app.outbox_events
            SET status = 'failed', available_at = now() + (%s * interval '1 second'),
                locked_by = NULL, locked_at = NULL, last_error = %s
            WHERE id = %s AND status = 'processing' AND locked_by = %s
            """,
            (delay, _safe_error(error), event_id, worker_id),
        )
    if cur.rowcount != 1:
        raise OutboxLeaseLost("Outbox 任务租约已丢失")


def delete_orphan_match_runs(match_run_ids: list[UUID]) -> int:
    if not match_run_ids:
        return 0
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            WITH deleted AS (
              DELETE FROM app.match_runs run
              WHERE run.id = ANY(%s)
                AND NOT EXISTS (
                  SELECT 1 FROM app.chat_messages message
                  WHERE message.match_run_id = run.id
                )
              RETURNING run.id
            )
            SELECT COUNT(*) AS count FROM deleted
            """,
            (match_run_ids,),
        )
    return int((row or {}).get("count") or 0)
