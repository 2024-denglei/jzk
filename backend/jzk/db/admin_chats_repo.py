"""管理端分支会话读取的所有权辅助与敏感读取审计。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from jzk.db.pg import db_session, fetchone


def user_exists(user_id: int) -> bool:
    with db_session(admin=True) as conn:
        return fetchone(conn, "SELECT 1 AS present FROM app.users WHERE id = %s", (user_id,)) is not None


def message_belongs_to_chat(user_id: int, chat_id: int, message_id: UUID) -> bool:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            SELECT 1 AS present
            FROM app.chat_messages message
            JOIN app.chats chat ON chat.id = message.chat_id
            WHERE message.id = %s AND message.chat_id = %s
              AND chat.user_id = %s AND chat.storage_version = 2
            """,
            (message_id, chat_id, user_id),
        )
    return row is not None


def write_sensitive_read_audit(
    user_id: int | None,
    operator_id: int,
    action: str,
    *,
    resource_type: str,
    resource_id: str,
    chat_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """只记录资源定位和分页元数据，不复制消息、排名或 Trace 正文。"""
    payload = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "chat_id": chat_id,
        **(metadata or {}),
    }
    with db_session(admin=True) as conn:
        conn.execute(
            """
            INSERT INTO admin.user_audit_logs
                (user_id, action, operator_id, reason, after_data)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                user_id,
                action,
                operator_id,
                f"读取 {resource_type} {resource_id}",
                Jsonb(payload),
            ),
        )
