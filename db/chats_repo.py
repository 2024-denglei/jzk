"""分支化长期对话的写仓储；调用方负责单个数据库事务。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from db.chat_models import ForkReason, GenerationStatus, MessageRole, MessageStatus
from db.pg import db_session, fetchall, fetchone


def find_turn_by_request(conn, user_id: int, request_id: UUID) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT g.chat_id, g.branch_id, g.user_message_id, g.assistant_message_id,
               g.id AS generation_id, b.fork_reason
        FROM app.ai_generation_runs g
        JOIN app.chat_branches b ON b.id = g.branch_id AND b.chat_id = g.chat_id
        WHERE g.user_id = %s AND g.client_request_id = %s
        """,
        (user_id, request_id),
    )


def create_chat(conn, user_id: int, *, title: str, legacy_session_id: str) -> int:
    row = fetchone(
        conn,
        """
        INSERT INTO app.chats
            (user_id, session_id, title, storage_version, branch_count, message_count)
        VALUES (%s, %s, %s, 2, 0, 0)
        RETURNING id
        """,
        (user_id, legacy_session_id, title),
    )
    assert row is not None
    return int(row["id"])


def lock_chat(conn, user_id: int, chat_id: int) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT id, user_id, title, active_branch_id, branch_count, message_count, storage_version
        FROM app.chats
        WHERE id = %s AND user_id = %s
        FOR UPDATE
        """,
        (chat_id, user_id),
    )


def lock_branch(conn, chat_id: int, branch_id: UUID) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT id, chat_id, parent_branch_id, forked_from_message_id,
               derived_from_message_id, fork_reason, head_message_id,
               version, is_archived
        FROM app.chat_branches
        WHERE chat_id = %s AND id = %s
        FOR UPDATE
        """,
        (chat_id, branch_id),
    )


def get_message(conn, chat_id: int, message_id: UUID) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT id, chat_id, created_in_branch_id, parent_message_id,
               derived_from_message_id, role, status, content,
               state_schema_version, state_after_json, state_recoverable,
               match_run_id, depth, created_at, completed_at
        FROM app.chat_messages
        WHERE chat_id = %s AND id = %s
        """,
        (chat_id, message_id),
    )


def message_is_on_branch_path(
    conn,
    chat_id: int,
    branch_head_id: UUID | None,
    message_id: UUID,
) -> bool:
    if branch_head_id is None:
        return False
    row = fetchone(
        conn,
        """
        WITH RECURSIVE path AS (
            SELECT id, parent_message_id
            FROM app.chat_messages
            WHERE chat_id = %s AND id = %s
          UNION ALL
            SELECT parent.id, parent.parent_message_id
            FROM app.chat_messages parent
            JOIN path child ON child.parent_message_id = parent.id
            WHERE parent.chat_id = %s
        )
        SELECT EXISTS (SELECT 1 FROM path WHERE id = %s) AS present
        """,
        (chat_id, branch_head_id, chat_id, message_id),
    )
    return bool(row and row["present"])


def branch_has_active_generation(conn, branch_id: UUID) -> bool:
    row = fetchone(
        conn,
        """
        SELECT EXISTS (
          SELECT 1 FROM app.ai_generation_runs
          WHERE branch_id = %s AND status IN ('queued', 'running')
        ) AS active
        """,
        (branch_id,),
    )
    return bool(row and row["active"])


def insert_branch(
    conn,
    *,
    branch_id: UUID,
    chat_id: int,
    parent_branch_id: UUID | None,
    forked_from_message_id: UUID | None,
    derived_from_message_id: UUID | None,
    name: str,
    system_name: str,
    fork_reason: ForkReason,
    head_message_id: UUID | None,
    created_by: str,
) -> None:
    conn.execute(
        """
        INSERT INTO app.chat_branches (
            id, chat_id, parent_branch_id, forked_from_message_id,
            derived_from_message_id, name, system_name, fork_reason,
            head_message_id, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            branch_id,
            chat_id,
            parent_branch_id,
            forked_from_message_id,
            derived_from_message_id,
            name,
            system_name,
            fork_reason.value,
            head_message_id,
            created_by,
        ),
    )


def insert_message(
    conn,
    *,
    message_id: UUID,
    chat_id: int,
    branch_id: UUID,
    parent_message_id: UUID | None,
    derived_from_message_id: UUID | None,
    role: MessageRole,
    status: MessageStatus,
    content: str,
    state_schema_version: int,
    state_after: dict[str, Any],
    state_recoverable: bool,
    depth: int,
    client_request_id: UUID | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO app.chat_messages (
            id, chat_id, created_in_branch_id, parent_message_id,
            derived_from_message_id, role, status, content,
            state_schema_version, state_after_json, state_recoverable,
            depth, client_request_id, completed_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            CASE WHEN %s = 'generating' THEN NULL ELSE now() END
        )
        """,
        (
            message_id,
            chat_id,
            branch_id,
            parent_message_id,
            derived_from_message_id,
            role.value,
            status.value,
            content,
            state_schema_version,
            Jsonb(state_after),
            state_recoverable,
            depth,
            client_request_id,
            status.value,
        ),
    )


def insert_generation(
    conn,
    *,
    generation_id: UUID,
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    user_message_id: UUID,
    assistant_message_id: UUID,
    client_request_id: UUID,
) -> None:
    conn.execute(
        """
        INSERT INTO app.ai_generation_runs (
            id, user_id, chat_id, branch_id, user_message_id,
            assistant_message_id, client_request_id, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            generation_id,
            user_id,
            chat_id,
            branch_id,
            user_message_id,
            assistant_message_id,
            client_request_id,
            GenerationStatus.QUEUED.value,
        ),
    )


def update_branch_head(
    conn,
    *,
    chat_id: int,
    branch_id: UUID,
    head_message_id: UUID,
    expected_version: int,
) -> bool:
    cur = conn.execute(
        """
        UPDATE app.chat_branches
        SET head_message_id = %s, version = version + 1, updated_at = now()
        WHERE chat_id = %s AND id = %s AND version = %s
        """,
        (head_message_id, chat_id, branch_id, expected_version),
    )
    return cur.rowcount == 1


def update_chat_after_turn(
    conn,
    *,
    chat_id: int,
    branch_id: UUID,
    message_delta: int,
    branch_delta: int,
) -> None:
    conn.execute(
        """
        UPDATE app.chats
        SET active_branch_id = %s,
            message_count = message_count + %s,
            branch_count = branch_count + %s,
            updated_at = now()
        WHERE id = %s
        """,
        (branch_id, message_delta, branch_delta, chat_id),
    )


def rename_chat(user_id: int, chat_id: int, title: str) -> bool:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE app.chats SET title = %s, updated_at = now()
            WHERE id = %s AND user_id = %s AND storage_version = 2
            """,
            (title.strip(), chat_id, user_id),
        )
    return cur.rowcount == 1


def update_branch_metadata(
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    *,
    name: str | None = None,
    is_archived: bool | None = None,
) -> bool:
    with db_session() as conn:
        chat = lock_chat(conn, user_id, chat_id)
        if chat is None or int(chat.get("storage_version") or 1) != 2:
            return False
        branch = lock_branch(conn, chat_id, branch_id)
        if branch is None:
            return False
        if is_archived is True and UUID(str(chat["active_branch_id"])) == branch_id:
            raise ValueError("当前活跃分支不能归档")
        sets = []
        params: list[Any] = []
        if name is not None:
            sets.append("name = %s")
            params.append(name.strip())
        if is_archived is not None:
            sets.append("is_archived = %s")
            params.append(is_archived)
        if not sets:
            return True
        params.extend([chat_id, branch_id])
        conn.execute(
            f"""
            UPDATE app.chat_branches
            SET {", ".join(sets)}, updated_at = now()
            WHERE chat_id = %s AND id = %s
            """,
            params,
        )
    return True


def hard_delete_chat(
    user_id: int,
    chat_id: int,
    request_id: UUID,
) -> dict[str, Any] | None:
    """不可恢复整会话删除；审计和 Outbox 不保存任何正文。"""
    with db_session() as conn:
        replay = fetchone(
            conn,
            """
            SELECT chat_id, branch_count, message_count, match_run_count, deleted_at
            FROM app.chat_deletion_audit
            WHERE user_id = %s AND request_id = %s
            """,
            (user_id, request_id),
        )
        if replay is not None:
            if int(replay["chat_id"]) != int(chat_id):
                raise ValueError("request_id 已用于其他会话删除")
            return {**replay, "idempotent_replay": True}
        chat = lock_chat(conn, user_id, chat_id)
        if chat is None or int(chat.get("storage_version") or 1) != 2:
            return None
        counts = fetchone(
            conn,
            """
            SELECT
              (SELECT COUNT(*) FROM app.chat_branches WHERE chat_id = %s) AS branches,
              (SELECT COUNT(*) FROM app.chat_messages WHERE chat_id = %s) AS messages,
              (SELECT COUNT(DISTINCT match_run_id) FROM app.chat_messages
               WHERE chat_id = %s AND match_run_id IS NOT NULL) AS matches
            """,
            (chat_id, chat_id, chat_id),
        ) or {}
        match_rows = fetchall(
            conn,
            "SELECT DISTINCT match_run_id FROM app.chat_messages WHERE chat_id = %s AND match_run_id IS NOT NULL",
            (chat_id,),
        )
        generation_rows = fetchall(
            conn,
            "SELECT id FROM app.ai_generation_runs WHERE chat_id = %s",
            (chat_id,),
        )
        branch_count = int(counts.get("branches") or 0)
        message_count = int(counts.get("messages") or 0)
        match_count = int(counts.get("matches") or 0)
        conn.execute(
            """
            INSERT INTO app.chat_deletion_audit
                (user_id, chat_id, branch_count, message_count, match_run_count, request_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_id, chat_id, branch_count, message_count, match_count, request_id),
        )
        conn.execute("DELETE FROM app.chats WHERE id = %s", (chat_id,))
        match_ids = [row["match_run_id"] for row in match_rows]
        if match_ids:
            conn.execute(
                "DELETE FROM app.match_runs WHERE user_id = %s AND id = ANY(%s)",
                (user_id, match_ids),
            )
        generation_ids = [str(row["id"]) for row in generation_rows]
        conn.execute(
            """
            INSERT INTO app.outbox_events
                (topic, aggregate_type, aggregate_id, dedupe_key, payload_json)
            VALUES ('chat_deleted', 'chat', %s, %s, %s)
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            (
                str(chat_id),
                f"chat_deleted:{request_id}",
                Jsonb({"generation_ids": generation_ids}),
            ),
        )
        audit = fetchone(
            conn,
            """
            SELECT chat_id, branch_count, message_count, match_run_count, deleted_at
            FROM app.chat_deletion_audit WHERE request_id = %s
            """,
            (request_id,),
        )
    assert audit is not None
    return {**audit, "idempotent_replay": False}
