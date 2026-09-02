"""管理端分支会话、完整排名与数据库 Trace API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

import config
from api.admin_permissions import USERS_VIEW, require_permission
from db import admin_chats_repo
from db.chat_models import ChatErrorCode
from dialogue.conversation_queries import ConversationQueryError, ConversationQueryService


router = APIRouter(
    prefix="/api/admin/users/{user_id}/conversations",
    tags=["admin-conversations-v2"],
)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _require_read() -> None:
    if not config.CHAT_STORAGE_V2_READ_ENABLED:
        raise _error(503, "CHAT_STORAGE_V2_READ_DISABLED", "新版对话读取尚未启用")


def _raise_query_error(exc: ConversationQueryError) -> None:
    status = 400 if exc.code in {
        ChatErrorCode.INVALID_CHAT_CURSOR,
        ChatErrorCode.INVALID_MESSAGE_CURSOR,
    } else 404
    raise _error(status, exc.code.value, str(exc)) from exc


def _audit(
    user_id: int,
    admin: dict,
    action: str,
    resource_type: str,
    resource_id: str,
    *,
    chat_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    admin_chats_repo.write_sensitive_read_audit(
        user_id,
        int(admin["id"]),
        action,
        resource_type=resource_type,
        resource_id=resource_id,
        chat_id=chat_id,
        metadata=metadata,
    )


@router.get("")
def list_admin_conversations(
    user_id: int,
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1),
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    _require_read()
    if not admin_chats_repo.user_exists(user_id):
        raise _error(404, "USER_NOT_FOUND", "用户不存在")
    try:
        page = ConversationQueryService(admin=True).list_chats(user_id, cursor=cursor, limit=limit)
    except ConversationQueryError as exc:
        _raise_query_error(exc)
    _audit(
        user_id,
        admin,
        "view_chat_list",
        "conversation_list",
        str(user_id),
        metadata={"limit": limit, "has_cursor": bool(cursor)},
    )
    return page


@router.get("/{chat_id}")
def get_admin_conversation(
    user_id: int,
    chat_id: int,
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    _require_read()
    try:
        tree = ConversationQueryService(admin=True).get_conversation(user_id, chat_id)
    except ConversationQueryError as exc:
        _raise_query_error(exc)
    _audit(user_id, admin, "view_chat_tree", "conversation_tree", str(chat_id), chat_id=chat_id)
    return tree


@router.get("/{chat_id}/branches/{branch_id}/messages")
def get_admin_message_path(
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    before: str | None = None,
    limit: int | None = Query(default=None, ge=1),
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    _require_read()
    try:
        page = ConversationQueryService(admin=True).get_message_path(
            user_id, chat_id, branch_id, before=before, limit=limit
        )
    except ConversationQueryError as exc:
        _raise_query_error(exc)
    _audit(
        user_id,
        admin,
        "view_chat_path",
        "message_path",
        str(branch_id),
        chat_id=chat_id,
        metadata={"limit": limit, "has_cursor": bool(before)},
    )
    return page


@router.get("/{chat_id}/messages/{message_id}/match-results")
def get_admin_message_match(
    user_id: int,
    chat_id: int,
    message_id: UUID,
    page: int = Query(default=1, ge=1),
    limit: int | None = Query(default=None, ge=1),
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    _require_read()
    if not admin_chats_repo.message_belongs_to_chat(user_id, chat_id, message_id):
        raise _error(404, ChatErrorCode.MESSAGE_NOT_FOUND.value, "消息不存在")
    try:
        result = ConversationQueryService(admin=True).get_message_match_results(
            user_id, message_id, page=page, limit=limit
        )
    except ConversationQueryError as exc:
        _raise_query_error(exc)
    _audit(
        user_id,
        admin,
        "view_chat_match",
        "message_match_snapshot",
        str(message_id),
        chat_id=chat_id,
        metadata={"page": page, "limit": limit},
    )
    return result


@router.get("/{chat_id}/branches/{branch_id}/messages/{message_id}/context")
def get_admin_message_context(
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    message_id: UUID,
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    _require_read()
    try:
        page = ConversationQueryService(admin=True).get_message_context(
            user_id, chat_id, branch_id, message_id
        )
    except ConversationQueryError as exc:
        _raise_query_error(exc)
    _audit(
        user_id,
        admin,
        "view_chat_message_context",
        "message_context",
        str(message_id),
        chat_id=chat_id,
        metadata={"branch_id": str(branch_id)},
    )
    return page


@router.get("/{chat_id}/generations/{generation_id}")
def get_admin_generation_trace(
    user_id: int,
    chat_id: int,
    generation_id: UUID,
    after_order: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=500),
    admin: dict = Depends(require_permission(USERS_VIEW)),
):
    _require_read()
    service = ConversationQueryService(admin=True)
    try:
        generation = service.get_generation(user_id, generation_id)
        if generation.chat_id != chat_id:
            raise _error(404, ChatErrorCode.GENERATION_NOT_FOUND.value, "生成任务不存在")
        steps = service.get_generation_steps(
            user_id, generation_id, after_order=after_order, limit=limit
        )
    except ConversationQueryError as exc:
        _raise_query_error(exc)
    _audit(
        user_id,
        admin,
        "view_chat_trace",
        "generation_trace",
        str(generation_id),
        chat_id=chat_id,
        metadata={"after_order": after_order, "limit": limit},
    )
    return {"generation": generation, "steps": steps}
