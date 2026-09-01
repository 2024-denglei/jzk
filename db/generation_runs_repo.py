"""持久 AI 生成任务：领取、租约、停止、终态提交和数据库 Trace。"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

import config
from db.chat_models import GenerationRunView, GenerationStatus, MessageStatus
from db.pg import db_session, fetchall, fetchone
from dialogue.state_schema import dump_state


_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|api[_-]?key\s*[:=]\s*\S+|sk-[a-z0-9_-]{8,})"
)
_TRACE_FORBIDDEN_KEYS = frozenset({
    "messages",
    "message_content",
    "content",
    "prompt",
    "prompt_text",
    "response",
    "raw_response",
    "user_message",
    "assistant_message",
    "candidates",
    "donor_snapshot",
    "system_prompt",
})


class GenerationLeaseLost(RuntimeError):
    pass


class GenerationTraceValidationError(ValueError):
    pass


def _safe_error(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "生成失败").split())
    text = _SECRET_PATTERN.sub("[redacted]", text)
    return text[:limit]


def _sanitize_trace_value(value: Any, *, key: str | None = None) -> Any:
    if key and key.lower() in _TRACE_FORBIDDEN_KEYS:
        raise GenerationTraceValidationError(f"Trace 禁止保存字段 {key}")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return _SECRET_PATTERN.sub("[redacted]", value)[:1000]
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_trace_value(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_trace_value(child) for child in value[:100]]
    return str(value)[:1000]


def sanitize_trace_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    return _sanitize_trace_value(dict(payload or {}))


def _run_view(row: dict[str, Any]) -> GenerationRunView:
    keys = {
        "id",
        "user_id",
        "chat_id",
        "branch_id",
        "user_message_id",
        "assistant_message_id",
        "status",
        "model",
        "prompt_version",
        "cancel_requested_at",
        "attempt_count",
        "error_type",
        "error_message_safe",
        "queued_at",
        "started_at",
        "finished_at",
    }
    return GenerationRunView.model_validate({key: row.get(key) for key in keys})


def claim_next_generation(
    worker_id: str,
    allowed_user_ids: frozenset[int] | None = None,
) -> GenerationRunView | None:
    """领取 queued 或租约过期任务；FOR UPDATE SKIP LOCKED 支持多 Worker。"""
    if allowed_user_ids is not None and not allowed_user_ids:
        return None
    scope_sql = ""
    params: list[Any] = [config.CHAT_GENERATION_MAX_ATTEMPTS]
    if allowed_user_ids is not None:
        scope_sql = "AND user_id = ANY(%s)"
        params.append(sorted(allowed_user_ids))
    params.extend([worker_id, config.CHAT_GENERATION_LEASE_SECONDS])
    with db_session() as conn:
        row = fetchone(
            conn,
            f"""
            WITH candidate AS (
              SELECT id
              FROM app.ai_generation_runs
              WHERE (
                    status = 'queued'
                    OR (status = 'running' AND lease_expires_at < now())
                  )
                AND attempt_count < %s
                {scope_sql}
              ORDER BY queued_at, id
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            UPDATE app.ai_generation_runs g
            SET status = 'running', lease_owner = %s,
                lease_expires_at = now() + (%s * interval '1 second'),
                heartbeat_at = now(), attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, now()),
                error_type = NULL, error_message_safe = NULL
            FROM candidate c
            WHERE g.id = c.id
            RETURNING g.*
            """,
            params,
        )
    return _run_view(row) if row else None


def heartbeat_generation(generation_id: UUID, worker_id: str) -> bool:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE app.ai_generation_runs
            SET heartbeat_at = now(),
                lease_expires_at = now() + (%s * interval '1 second')
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            """,
            (config.CHAT_GENERATION_LEASE_SECONDS, generation_id, worker_id),
        )
    return cur.rowcount == 1


def generation_cancel_requested(generation_id: UUID, worker_id: str) -> bool:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT cancel_requested_at IS NOT NULL AS requested
            FROM app.ai_generation_runs
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            """,
            (generation_id, worker_id),
        )
    if row is None:
        raise GenerationLeaseLost("生成任务租约已丢失")
    return bool(row["requested"])


def set_generation_model_metadata(
    generation_id: UUID,
    worker_id: str,
    *,
    model: str,
    prompt_version: str,
    prompt_hash: str,
) -> None:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE app.ai_generation_runs
            SET model = %s, prompt_version = %s, prompt_hash = %s
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            """,
            (
                _safe_error(model, 120),
                _safe_error(prompt_version, 120),
                _safe_error(prompt_hash, 128),
                generation_id,
                worker_id,
            ),
        )
    if cur.rowcount != 1:
        raise GenerationLeaseLost("生成任务租约已丢失")


def request_generation_stop(user_id: int, generation_id: UUID) -> GenerationRunView | None:
    """queued 任务立即停止；running 任务写取消标记，由持租约 Worker 收尾。"""
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT * FROM app.ai_generation_runs
            WHERE id = %s AND user_id = %s
            FOR UPDATE
            """,
            (generation_id, user_id),
        )
        if row is None:
            return None
        if row["status"] == GenerationStatus.QUEUED.value:
            conn.execute(
                """
                UPDATE app.chat_messages
                SET status = 'stopped', completed_at = now()
                WHERE id = %s AND status = 'generating'
                """,
                (row["assistant_message_id"],),
            )
            row = fetchone(
                conn,
                """
                UPDATE app.ai_generation_runs
                SET status = 'stopped', cancel_requested_at = now(), finished_at = now()
                WHERE id = %s RETURNING *
                """,
                (generation_id,),
            )
        elif row["status"] == GenerationStatus.RUNNING.value and not row.get(
            "cancel_requested_at"
        ):
            row = fetchone(
                conn,
                """
                UPDATE app.ai_generation_runs
                SET cancel_requested_at = now()
                WHERE id = %s RETURNING *
                """,
                (generation_id,),
            )
    assert row is not None
    return _run_view(row)


def checkpoint_generation(
    generation_id: UUID,
    worker_id: str,
    *,
    content: str,
    state_after: dict[str, Any],
) -> None:
    state = dump_state(state_after)
    with db_session() as conn:
        run = fetchone(
            conn,
            """
            SELECT assistant_message_id FROM app.ai_generation_runs
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            FOR UPDATE
            """,
            (generation_id, worker_id),
        )
        if run is None:
            raise GenerationLeaseLost("生成任务租约已丢失")
        cur = conn.execute(
            """
            UPDATE app.chat_messages
            SET content = %s, state_after_json = %s, state_recoverable = TRUE
            WHERE id = %s AND status = 'generating'
            """,
            (content[: config.CHAT_MESSAGE_MAX_CHARS], Jsonb(state), run["assistant_message_id"]),
        )
        if cur.rowcount != 1:
            raise GenerationLeaseLost("AI 消息已进入终态")


def _next_step_order(conn, generation_id: UUID) -> int:
    row = fetchone(
        conn,
        "SELECT COALESCE(MAX(step_order), -1) + 1 AS n FROM app.ai_generation_steps WHERE generation_id = %s",
        (generation_id,),
    )
    return int(row["n"] if row else 0)


def append_generation_step(
    generation_id: UUID,
    step_type: str,
    payload: dict[str, Any] | None = None,
    *,
    elapsed_ms: float | None = None,
) -> int:
    clean = sanitize_trace_payload(payload)
    if not step_type.strip() or len(step_type) > 80:
        raise GenerationTraceValidationError("step_type 无效")
    if elapsed_ms is not None and elapsed_ms < 0:
        raise GenerationTraceValidationError("elapsed_ms 不能为负数")
    with db_session() as conn:
        order = _next_step_order(conn, generation_id)
        row = fetchone(
            conn,
            """
            INSERT INTO app.ai_generation_steps
                (generation_id, step_order, step_type, payload_json, elapsed_ms)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (generation_id, order, step_type.strip(), Jsonb(clean), elapsed_ms),
        )
    assert row is not None
    return int(row["id"])


def complete_generation(
    generation_id: UUID,
    worker_id: str,
    *,
    content: str,
    state_after: dict[str, Any],
    match_run_id: UUID | None = None,
    timings: dict[str, Any] | None = None,
) -> GenerationRunView:
    state = dump_state(state_after)
    with db_session() as conn:
        run = fetchone(
            conn,
            """
            SELECT * FROM app.ai_generation_runs
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            FOR UPDATE
            """,
            (generation_id, worker_id),
        )
        if run is None or run.get("cancel_requested_at") is not None:
            raise GenerationLeaseLost("生成任务不可提交完成状态")
        cur = conn.execute(
            """
            UPDATE app.chat_messages
            SET status = 'completed', content = %s,
                state_after_json = %s, state_recoverable = TRUE,
                match_run_id = %s, completed_at = now()
            WHERE id = %s AND status = 'generating'
            """,
            (
                content[: config.CHAT_MESSAGE_MAX_CHARS],
                Jsonb(state),
                match_run_id,
                run["assistant_message_id"],
            ),
        )
        if cur.rowcount != 1:
            raise GenerationLeaseLost("AI 消息已进入终态")
        finished = fetchone(
            conn,
            """
            UPDATE app.ai_generation_runs
            SET status = 'completed', timings_json = %s,
                finished_at = now(), lease_expires_at = NULL
            WHERE id = %s
            RETURNING *
            """,
            (Jsonb(timings or {}), generation_id),
        )
    assert finished is not None
    return _run_view(finished)


def finish_generation_unsuccessfully(
    generation_id: UUID,
    worker_id: str,
    *,
    stopped: bool,
    error_type: str | None = None,
    error_message: Any = None,
) -> GenerationRunView:
    target = GenerationStatus.STOPPED if stopped else GenerationStatus.FAILED
    message_target = MessageStatus.STOPPED if stopped else MessageStatus.FAILED
    safe_message = None if stopped else _safe_error(error_message)
    with db_session() as conn:
        run = fetchone(
            conn,
            """
            SELECT * FROM app.ai_generation_runs
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            FOR UPDATE
            """,
            (generation_id, worker_id),
        )
        if run is None:
            raise GenerationLeaseLost("生成任务租约已丢失")
        conn.execute(
            """
            UPDATE app.chat_messages
            SET status = %s, completed_at = now()
            WHERE id = %s AND status = 'generating'
            """,
            (message_target.value, run["assistant_message_id"]),
        )
        finished = fetchone(
            conn,
            """
            UPDATE app.ai_generation_runs
            SET status = %s, error_type = %s, error_message_safe = %s,
                finished_at = now(), lease_expires_at = NULL
            WHERE id = %s RETURNING *
            """,
            (target.value, _safe_error(error_type, 80) if error_type else None, safe_message, generation_id),
        )
    assert finished is not None
    return _run_view(finished)


def release_generation_for_retry(
    generation_id: UUID,
    worker_id: str,
    *,
    error_type: str,
    error_message: Any,
) -> GenerationRunView:
    """非终态释放租约；下一次领取会增加 attempt_count。"""
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            UPDATE app.ai_generation_runs
            SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL,
                heartbeat_at = NULL, error_type = %s, error_message_safe = %s
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
              AND attempt_count < %s
            RETURNING *
            """,
            (
                _safe_error(error_type, 80),
                _safe_error(error_message),
                generation_id,
                worker_id,
                config.CHAT_GENERATION_MAX_ATTEMPTS,
            ),
        )
    if row is None:
        raise GenerationLeaseLost("生成任务不能重试或租约已丢失")
    return _run_view(row)


def fail_exhausted_generations(*, limit: int = 100) -> int:
    """收尾已用尽尝试次数的 queued/过期 running 任务，避免永久悬挂。"""
    size = max(1, min(int(limit), 1000))
    with db_session() as conn:
        rows = fetchall(
            conn,
            """
            SELECT * FROM app.ai_generation_runs
            WHERE attempt_count >= %s
              AND (
                status = 'queued'
                OR (status = 'running' AND lease_expires_at < now())
              )
            ORDER BY queued_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
            """,
            (config.CHAT_GENERATION_MAX_ATTEMPTS, size),
        )
        for run in rows:
            conn.execute(
                """
                UPDATE app.chat_messages
                SET status = 'failed', completed_at = now()
                WHERE id = %s AND status = 'generating'
                """,
                (run["assistant_message_id"],),
            )
            conn.execute(
                """
                UPDATE app.ai_generation_runs
                SET status = 'failed', error_type = 'MAX_ATTEMPTS_EXCEEDED',
                    error_message_safe = '生成任务已达到最大尝试次数',
                    finished_at = now(), lease_expires_at = NULL
                WHERE id = %s
                """,
                (run["id"],),
            )
    return len(rows)


def get_generation(user_id: int, generation_id: UUID, *, admin: bool = False) -> GenerationRunView | None:
    with db_session(admin=admin) as conn:
        row = fetchone(
            conn,
            "SELECT * FROM app.ai_generation_runs WHERE id = %s AND user_id = %s",
            (generation_id, user_id),
        )
    return _run_view(row) if row else None


def load_generation_context(generation_id: UUID, worker_id: str) -> dict[str, Any]:
    """从用户消息父链和该消息状态快照恢复本轮上下文。"""
    with db_session() as conn:
        run = fetchone(
            conn,
            """
            SELECT * FROM app.ai_generation_runs
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND lease_expires_at > now()
            """,
            (generation_id, worker_id),
        )
        if run is None:
            raise GenerationLeaseLost("生成任务租约已丢失")
        rows = fetchall(
            conn,
            """
            WITH RECURSIVE path AS (
              SELECT id, parent_message_id, role, content, depth,
                     state_after_json, state_schema_version, state_recoverable
              FROM app.chat_messages
              WHERE chat_id = %s AND id = %s
              UNION ALL
              SELECT parent.id, parent.parent_message_id, parent.role, parent.content,
                     parent.depth, parent.state_after_json, parent.state_schema_version,
                     parent.state_recoverable
              FROM app.chat_messages parent
              JOIN path child ON child.parent_message_id = parent.id
              WHERE parent.chat_id = %s
            )
            SELECT * FROM path ORDER BY depth, id
            """,
            (run["chat_id"], run["user_message_id"], run["chat_id"]),
        )
    if not rows or UUID(str(rows[-1]["id"])) != UUID(str(run["user_message_id"])):
        raise GenerationLeaseLost("生成上下文不完整")
    current = rows[-1]
    return {
        "generation": _run_view(run),
        "messages": [
            {"id": str(row["id"]), "role": row["role"], "content": row["content"]}
            for row in rows
        ],
        "state_after_user": dict(current["state_after_json"] or {}),
        "state_schema_version": int(current["state_schema_version"]),
        "state_recoverable": bool(current["state_recoverable"]),
    }


def list_generation_steps(
    user_id: int,
    generation_id: UUID,
    *,
    after_order: int = -1,
    limit: int = 100,
    admin: bool = False,
) -> list[dict[str, Any]] | None:
    size = max(1, min(int(limit), 500))
    with db_session(admin=admin) as conn:
        owned = fetchone(
            conn,
            "SELECT 1 AS ok FROM app.ai_generation_runs WHERE id = %s AND user_id = %s",
            (generation_id, user_id),
        )
        if owned is None:
            return None
        return fetchall(
            conn,
            """
            SELECT id, step_order, step_type, payload_json, created_at, elapsed_ms
            FROM app.ai_generation_steps
            WHERE generation_id = %s AND step_order > %s
            ORDER BY step_order LIMIT %s
            """,
            (generation_id, max(-1, int(after_order)), size),
        )
