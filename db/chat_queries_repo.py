"""分支化会话的只读查询仓储；用户端和管理端共享这些 SQL。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from db.pg import fetchall, fetchone


def list_chats(
    conn,
    user_id: int,
    *,
    before_updated_at: datetime | None,
    before_chat_id: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    cursor_sql = ""
    params: list[Any] = [user_id]
    if before_updated_at is not None and before_chat_id is not None:
        cursor_sql = "AND (c.updated_at, c.id) < (%s, %s)"
        params.extend([before_updated_at, before_chat_id])
    params.append(limit)
    return fetchall(
        conn,
        f"""
        SELECT c.id, c.title, c.storage_version, c.active_branch_id,
               c.branch_count, c.message_count,
               c.created_at, c.updated_at, b.name AS active_branch_name,
               left(COALESCE(NULLIF(head.content, ''), parent.content, ''), 120)
                 AS last_message_preview
        FROM app.chats c
        LEFT JOIN app.chat_branches b
          ON b.chat_id = c.id AND b.id = c.active_branch_id
        LEFT JOIN app.chat_messages head
          ON head.chat_id = c.id AND head.id = b.head_message_id
        LEFT JOIN app.chat_messages parent
          ON parent.chat_id = c.id AND parent.id = head.parent_message_id
        WHERE c.user_id = %s
          {cursor_sql}
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT %s
        """,
        params,
    )


def get_chat(conn, user_id: int, chat_id: int) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT c.id, c.title, c.storage_version, c.active_branch_id,
               c.branch_count, c.message_count,
               c.created_at, c.updated_at, b.name AS active_branch_name,
               left(COALESCE(NULLIF(head.content, ''), parent.content, ''), 120)
                 AS last_message_preview
        FROM app.chats c
        LEFT JOIN app.chat_branches b
          ON b.chat_id = c.id AND b.id = c.active_branch_id
        LEFT JOIN app.chat_messages head
          ON head.chat_id = c.id AND head.id = b.head_message_id
        LEFT JOIN app.chat_messages parent
          ON parent.chat_id = c.id AND parent.id = head.parent_message_id
        WHERE c.id = %s AND c.user_id = %s
        """,
        (chat_id, user_id),
    )


def get_chat_path_source(conn, user_id: int, chat_id: int) -> dict[str, Any] | None:
    """消息翻页只读取归属校验所需字段，避免摘要 join。"""
    return fetchone(
        conn,
        """
        SELECT c.id, c.title, c.storage_version, c.created_at, c.updated_at
        FROM app.chats c
        WHERE c.id = %s AND c.user_id = %s
        """,
        (chat_id, user_id),
    )


def list_branches(conn, chat_id: int, active_branch_id: UUID | None) -> list[dict[str, Any]]:
    return fetchall(
        conn,
        """
        SELECT b.id, b.parent_branch_id, b.forked_from_message_id,
               b.derived_from_message_id, b.name, b.system_name, b.fork_reason,
               b.head_message_id, COALESCE(head.depth + 1, 0) AS message_count,
               left(COALESCE(NULLIF(head.content, ''), parent.content, ''), 120)
                 AS last_message_preview,
               (b.id = %s) AS is_active, b.is_archived, b.created_at, b.updated_at
        FROM app.chat_branches b
        LEFT JOIN app.chat_messages head
          ON head.chat_id = b.chat_id AND head.id = b.head_message_id
        LEFT JOIN app.chat_messages parent
          ON parent.chat_id = b.chat_id AND parent.id = head.parent_message_id
        WHERE b.chat_id = %s
        ORDER BY b.created_at, b.id
        """,
        (active_branch_id, chat_id),
    )


def get_branch_for_user(
    conn,
    user_id: int,
    chat_id: int,
    branch_id: UUID,
) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT b.id, b.head_message_id
        FROM app.chat_branches b
        JOIN app.chats c ON c.id = b.chat_id
        WHERE b.chat_id = %s AND b.id = %s
          AND c.user_id = %s AND c.storage_version = 2
        """,
        (chat_id, branch_id, user_id),
    )


def message_is_on_path(
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
        WITH RECURSIVE target AS (
          SELECT id, depth FROM app.chat_messages
          WHERE chat_id = %s AND id = %s
        ), path AS (
          SELECT head.id, head.parent_message_id, head.depth
          FROM app.chat_messages head
          CROSS JOIN target
          WHERE head.chat_id = %s AND head.id = %s
          UNION ALL
          SELECT parent.id, parent.parent_message_id, parent.depth
          FROM app.chat_messages parent
          JOIN path child ON child.parent_message_id = parent.id
          CROSS JOIN target
          WHERE parent.chat_id = %s
            AND child.id <> target.id
            AND parent.depth >= target.depth
        )
        SELECT EXISTS (SELECT 1 FROM path WHERE id = %s) AS present
        """,
        (chat_id, message_id, chat_id, branch_head_id, chat_id, message_id),
    )
    return bool(row and row["present"])


def get_message_path(
    conn,
    chat_id: int,
    start_message_id: UUID,
    *,
    user_id: int | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    return fetchall(
        conn,
        """
        WITH RECURSIVE path AS (
          SELECT m.*, 1 AS hop FROM app.chat_messages m
          WHERE m.chat_id = %s AND m.id = %s
          UNION ALL
          SELECT parent.*, child.hop + 1
          FROM app.chat_messages parent
          JOIN path child ON child.parent_message_id = parent.id
          WHERE parent.chat_id = %s AND child.hop < %s
        )
        SELECT p.id, p.parent_message_id, p.derived_from_message_id,
               p.created_in_branch_id, p.role, p.status, p.content,
               p.content_format, p.depth, p.state_recoverable,
               p.created_at, p.completed_at, generation.id AS generation_id,
               feedback.message_id AS feedback_message_id,
               feedback.rating AS feedback_rating,
               feedback.updated_at AS feedback_updated_at,
               mr.total AS match_total, mr.model_version,
               mr.dataset_version, mr.snapshot_schema_version,
               mr.snapshot_source, mr.created_at AS match_created_at
        FROM path p
        LEFT JOIN app.match_runs mr
          ON mr.id = p.match_run_id AND mr.status = 'ready'
        LEFT JOIN app.ai_generation_runs generation
          ON generation.chat_id = p.chat_id
         AND generation.assistant_message_id = p.id
        LEFT JOIN app.chat_message_feedback feedback
          ON feedback.message_id = p.id AND feedback.user_id = %s
        ORDER BY p.depth DESC, p.created_at DESC, p.id DESC
        LIMIT %s
        """,
        (chat_id, start_message_id, chat_id, limit, user_id, limit),
    )


def get_message_context(
    conn,
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    message_id: UUID,
    *,
    radius: int = 25,
) -> list[dict[str, Any]]:
    """返回目标消息在指定分支父链中的有界上下文。"""
    return fetchall(
        conn,
        """
        WITH RECURSIVE source AS (
          SELECT branch.head_message_id
          FROM app.chat_branches branch
          JOIN app.chats chat ON chat.id = branch.chat_id
          WHERE branch.chat_id = %s AND branch.id = %s
            AND chat.user_id = %s AND chat.storage_version = 2
        ), path AS (
          SELECT message.*
          FROM app.chat_messages message
          JOIN source ON source.head_message_id = message.id
          WHERE message.chat_id = %s
          UNION ALL
          SELECT parent.*
          FROM app.chat_messages parent
          JOIN path child ON child.parent_message_id = parent.id
          WHERE parent.chat_id = %s
        ), target AS (
          SELECT depth FROM path WHERE id = %s
        )
        SELECT p.id, p.parent_message_id, p.derived_from_message_id,
               p.created_in_branch_id, p.role, p.status, p.content,
               p.content_format, p.depth, p.state_recoverable,
               p.created_at, p.completed_at, generation.id AS generation_id,
               feedback.message_id AS feedback_message_id,
               feedback.rating AS feedback_rating,
               feedback.updated_at AS feedback_updated_at,
               mr.total AS match_total, mr.model_version,
               mr.dataset_version, mr.snapshot_schema_version,
               mr.snapshot_source, mr.created_at AS match_created_at
        FROM path p
        CROSS JOIN target
        LEFT JOIN app.match_runs mr
          ON mr.id = p.match_run_id AND mr.status = 'ready'
        LEFT JOIN app.ai_generation_runs generation
          ON generation.chat_id = p.chat_id
         AND generation.assistant_message_id = p.id
        LEFT JOIN app.chat_message_feedback feedback
          ON feedback.message_id = p.id AND feedback.user_id = %s
        WHERE p.depth BETWEEN GREATEST(0, target.depth - %s) AND target.depth + %s
        ORDER BY p.depth, p.created_at, p.id
        """,
        (chat_id, branch_id, user_id, chat_id, chat_id, message_id, user_id, radius, radius),
    )


def get_message_match_snapshot(
    conn,
    user_id: int,
    message_id: UUID,
) -> dict[str, Any] | None:
    return fetchone(
        conn,
        """
        SELECT cm.chat_id, cm.match_run_id
        FROM app.chat_messages cm
        JOIN app.chats c ON c.id = cm.chat_id
        JOIN app.match_runs mr ON mr.id = cm.match_run_id AND mr.status = 'ready'
        WHERE cm.id = %s AND c.user_id = %s AND c.storage_version = 2
        """,
        (message_id, user_id),
    )
