"""AI 消息当前反馈的用户写入与管理查询。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from db import chat_queries_repo
from db.pg import db_session, fetchall, fetchone


class MessageFeedbackTargetError(ValueError):
    pass


def set_message_feedback(
    user_id: int,
    message_id: UUID,
    branch_id: UUID,
    rating: str,
) -> dict[str, Any]:
    with db_session() as conn:
        target = fetchone(
            conn,
            """
            SELECT message.chat_id, branch.head_message_id
            FROM app.chat_messages message
            JOIN app.chats chat ON chat.id = message.chat_id
            JOIN app.chat_branches branch
              ON branch.chat_id = message.chat_id AND branch.id = %s
            WHERE message.id = %s AND chat.user_id = %s
              AND chat.storage_version = 2
              AND message.role = 'assistant' AND message.status = 'completed'
            """,
            (branch_id, message_id, user_id),
        )
        if target is None:
            raise MessageFeedbackTargetError("只能评价本人会话中已完成的 AI 回复")
        chat_id = int(target["chat_id"])
        head_id = target.get("head_message_id")
        if not head_id or not chat_queries_repo.message_is_on_path(
            conn, chat_id, UUID(str(head_id)), message_id
        ):
            raise MessageFeedbackTargetError("目标消息不在当前分支路径中")
        row = fetchone(
            conn,
            """
            INSERT INTO app.chat_message_feedback
                (message_id, user_id, chat_id, branch_id, rating)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO UPDATE
            SET branch_id = EXCLUDED.branch_id,
                rating = EXCLUDED.rating,
                updated_at = now()
            WHERE app.chat_message_feedback.user_id = EXCLUDED.user_id
            RETURNING message_id, rating, updated_at
            """,
            (message_id, user_id, chat_id, branch_id, rating),
        )
        if row is None:
            raise MessageFeedbackTargetError("反馈消息归属冲突")
        return row


def delete_message_feedback(user_id: int, message_id: UUID) -> None:
    with db_session() as conn:
        conn.execute(
            "DELETE FROM app.chat_message_feedback WHERE message_id = %s AND user_id = %s",
            (message_id, user_id),
        )


def list_admin_feedback(
    *,
    rating: str | None,
    user_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
    before_updated_at: datetime | None,
    before_message_id: UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[Any] = []
    if rating:
        conditions.append("feedback.rating = %s")
        params.append(rating)
    if user_id is not None:
        conditions.append("feedback.user_id = %s")
        params.append(user_id)
    if date_from is not None:
        conditions.append("feedback.updated_at >= %s")
        params.append(date_from)
    if date_to is not None:
        conditions.append("feedback.updated_at < %s")
        params.append(date_to)
    if before_updated_at is not None and before_message_id is not None:
        conditions.append("(feedback.updated_at, feedback.message_id) < (%s, %s)")
        params.extend([before_updated_at, before_message_id])
    where = " AND ".join(conditions) or "TRUE"
    params.append(limit)
    with db_session(admin=True) as conn:
        return fetchall(
            conn,
            f"""
            SELECT feedback.message_id, feedback.rating, feedback.user_id,
                   feedback.chat_id, feedback.branch_id, branch.name AS branch_name,
                   left(message.content, 180) AS message_preview,
                   feedback.created_at, feedback.updated_at,
                   COALESCE(NULLIF(app_user.nickname, ''), 'UID ' || app_user.id::text)
                     AS user_display
            FROM app.chat_message_feedback feedback
            JOIN app.users app_user ON app_user.id = feedback.user_id
            JOIN app.chat_branches branch
              ON branch.chat_id = feedback.chat_id AND branch.id = feedback.branch_id
            JOIN app.chat_messages message
              ON message.chat_id = feedback.chat_id AND message.id = feedback.message_id
            WHERE {where}
            ORDER BY feedback.updated_at DESC, feedback.message_id DESC
            LIMIT %s
            """,
            params,
        )


def get_admin_feedback_summary() -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            SELECT count(*) FILTER (WHERE rating = 'like') AS likes,
                   count(*) FILTER (WHERE rating = 'dislike') AS dislikes,
                   count(*) FILTER (
                     WHERE rating = 'dislike' AND updated_at >= %s
                   ) AS recent_dislikes
            FROM app.chat_message_feedback
            """,
            (since,),
        ) or {}
    return {key: int(row.get(key) or 0) for key in ("likes", "dislikes", "recent_dislikes")}
