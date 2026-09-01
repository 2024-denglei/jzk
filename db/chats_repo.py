"""分支化长期对话的写仓储；调用方负责单个数据库事务。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from db.chat_models import ForkReason, GenerationStatus, MessageRole, MessageStatus
from db.pg import fetchone


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
