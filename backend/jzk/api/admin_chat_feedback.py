"""管理端 AI 消息反馈列表与统计。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from jzk.api.admin_permissions import USERS_VIEW, require_permission
from jzk.db import admin_chats_repo, chat_feedback_repo
from jzk.chat.conversation_cursors import (
    InvalidConversationCursor,
    decode_admin_feedback_cursor,
    encode_admin_feedback_cursor,
)


router = APIRouter(prefix="/api/admin/chat-feedback", tags=["admin-chat-feedback"])


def _filter_key(
    rating: str | None,
    user_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> str:
    return "|".join((
        rating or "all",
        str(user_id or ""),
        date_from.isoformat() if date_from else "",
        date_to.isoformat() if date_to else "",
    ))


@router.get("/summary")
def get_feedback_summary(admin: dict = Depends(require_permission(USERS_VIEW))):
    result = chat_feedback_repo.get_admin_feedback_summary()
    admin_chats_repo.write_sensitive_read_audit(
        None,
        int(admin["id"]),
        "view_chat_feedback_summary",
        resource_type="chat_feedback_summary",
        resource_id="global",
    )
    return result


@router.get("")
def list_feedback(
    rating: Literal["like", "dislike", "all"] = "dislike",
    user_id: int | None = Query(default=None, ge=1),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    effective_rating = None if rating == "all" else rating
    key = _filter_key(effective_rating, user_id, date_from, date_to)
    before_updated_at = None
    before_message_id = None
    if cursor:
        try:
            before_updated_at, before_message_id = decode_admin_feedback_cursor(cursor, key)
        except InvalidConversationCursor as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_FEEDBACK_CURSOR", "message": str(exc)},
            ) from exc
    rows = chat_feedback_repo.list_admin_feedback(
        rating=effective_rating,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        before_updated_at=before_updated_at,
        before_message_id=before_message_id,
        limit=limit + 1,
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_admin_feedback_cursor(
            key,
            last["updated_at"],
            UUID(str(last["message_id"])),
        )
    admin_chats_repo.write_sensitive_read_audit(
        user_id,
        int(admin["id"]),
        "view_chat_feedback_list",
        resource_type="chat_feedback_list",
        resource_id=str(user_id or "global"),
        metadata={"rating": effective_rating or "all", "limit": limit, "has_cursor": bool(cursor)},
    )
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}
