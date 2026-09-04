"""分支化长期对话的写仓储；调用方负责单个数据库事务。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from jzk.db.chat_contracts import ForkReason, GenerationStatus, MessageRole, MessageStatus
from jzk.db.pg import db_session, fetchall, fetchone


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


def create_chat(conn, user_id: int, *, title: str) -> int:
    row = fetchone(
        conn,
        """
        INSERT INTO app.chats
            (user_id, title, storage_version, branch_count, message_count)
        VALUES (%s, %s, 2, 0, 0)
        RETURNING id
        """,
        (user_id, title),
    )
    assert row is not None
    return int(row["id"])


def lock_chat(conn, user_id: int, chat_id: int) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT id, user_id, title, active_branch_id, branch_count, message_count,
               storage_version
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


def force_stop_branch_generations(
    conn,
    branch_id: UUID,
    *,
    only_cancel_requested: bool = False,
) -> int:
    """将分支上未完成的生成任务直接标为 stopped。

    - edit_resend：替换当前线路，应强制收尾所有 queued/running
    - append：仅收尾已请求取消的 running，避免「终止后立刻发送」被挡住
    """
    rows = fetchall(
        conn,
        """
        SELECT id, assistant_message_id, status, cancel_requested_at
        FROM app.ai_generation_runs
        WHERE branch_id = %s AND status IN ('queued', 'running')
        FOR UPDATE
        """,
        (branch_id,),
    )
    stopped = 0
    for row in rows:
        if only_cancel_requested:
            if row["status"] != "running" or row.get("cancel_requested_at") is None:
                continue
        conn.execute(
            """
            UPDATE app.chat_messages
            SET status = 'stopped', completed_at = now()
            WHERE id = %s AND status = 'generating'
            """,
            (row["assistant_message_id"],),
        )
        conn.execute(
            """
            UPDATE app.ai_generation_runs
            SET status = 'stopped',
                cancel_requested_at = COALESCE(cancel_requested_at, now()),
                finished_at = now(),
                lease_expires_at = NULL
            WHERE id = %s AND status IN ('queued', 'running')
            """,
            (row["id"],),
        )
        stopped += 1
    return stopped


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


def prune_unreachable_messages(
    conn,
    *,
    chat_id: int,
    request_id: UUID,
) -> int:
    """删除不再被任何显式分支引用的消息、生成记录和匹配快照。"""
    doomed = fetchall(
        conn,
        """
        WITH RECURSIVE retained AS (
          SELECT message.id, message.parent_message_id, message.derived_from_message_id
          FROM app.chat_messages message
          JOIN (
            SELECT head_message_id AS id FROM app.chat_branches
            WHERE chat_id = %s AND head_message_id IS NOT NULL
            UNION
            SELECT forked_from_message_id FROM app.chat_branches
            WHERE chat_id = %s AND forked_from_message_id IS NOT NULL
            UNION
            SELECT derived_from_message_id FROM app.chat_branches
            WHERE chat_id = %s AND derived_from_message_id IS NOT NULL
          ) root ON root.id = message.id
          WHERE message.chat_id = %s
        UNION
          SELECT related.id, related.parent_message_id, related.derived_from_message_id
          FROM retained child
          JOIN LATERAL (
            VALUES (child.parent_message_id), (child.derived_from_message_id)
          ) reference(id) ON reference.id IS NOT NULL
          JOIN app.chat_messages related
            ON related.chat_id = %s AND related.id = reference.id
        )
        SELECT message.id, message.match_run_id
        FROM app.chat_messages message
        WHERE message.chat_id = %s
          AND NOT EXISTS (SELECT 1 FROM retained WHERE retained.id = message.id)
        """,
        (chat_id, chat_id, chat_id, chat_id, chat_id, chat_id),
    )
    if not doomed:
        return 0

    message_ids = [row["id"] for row in doomed]
    match_run_ids = [str(row["match_run_id"]) for row in doomed if row.get("match_run_id")]
    generations = fetchall(
        conn,
        """
        DELETE FROM app.ai_generation_runs
        WHERE chat_id = %s
          AND (user_message_id = ANY(%s) OR assistant_message_id = ANY(%s))
        RETURNING id
        """,
        (chat_id, message_ids, message_ids),
    )
    generation_ids = [str(row["id"]) for row in generations]

    # 触发器只为当前事务中的“分支头已切换后清理”开放单节点删除。
    conn.execute("SELECT set_config('app.allow_message_prune', 'on', true)")
    conn.execute(
        "DELETE FROM app.chat_messages WHERE chat_id = %s AND id = ANY(%s)",
        (chat_id, message_ids),
    )
    conn.execute(
        """
        UPDATE app.chats
        SET message_count = (
              SELECT COUNT(*) FROM app.chat_messages WHERE chat_id = %s
            ),
            updated_at = now()
        WHERE id = %s
        """,
        (chat_id, chat_id),
    )
    if generation_ids:
        conn.execute(
            """
            INSERT INTO app.outbox_events
                (topic, aggregate_type, aggregate_id, dedupe_key, payload_json)
            VALUES ('generation_event_cleanup', 'chat_edit', %s, %s, %s)
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            (
                str(chat_id),
                f"generation_event_cleanup:edit:{request_id}",
                Jsonb({"generation_ids": generation_ids}),
            ),
        )
    if match_run_ids:
        conn.execute(
            """
            INSERT INTO app.outbox_events
                (topic, aggregate_type, aggregate_id, dedupe_key, payload_json)
            VALUES ('orphan_match_run_cleanup', 'chat_edit', %s, %s, %s)
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            (
                str(chat_id),
                f"orphan_match_run_cleanup:edit:{request_id}",
                Jsonb({"match_run_ids": match_run_ids}),
            ),
        )
    return len(doomed)


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
    is_archived: bool,
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
        conn.execute(
            """
            UPDATE app.chat_branches
            SET is_archived = %s, updated_at = now()
            WHERE chat_id = %s AND id = %s
            """,
            (is_archived, chat_id, branch_id),
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
        if chat is None:
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
