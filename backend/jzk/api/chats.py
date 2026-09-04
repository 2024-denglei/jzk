"""用户端分支化长期对话 V2 API。"""

from __future__ import annotations

from functools import partial
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from jzk.api.auth_utils import get_current_user_id
from jzk.db import chat_feedback_repo, chats_repo
from jzk.db.chat_contracts import ChatErrorCode, MessageFeedbackRating, MessageFeedbackView, TurnCommand
from jzk.chat.conversation_commands import ConversationCommandError, create_turn
from jzk.chat.conversation_queries import ConversationQueryError, ConversationQueryService


router = APIRouter(prefix="/api/chats", tags=["chats-v2"])
message_router = APIRouter(prefix="/api/messages", tags=["chats-v2"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _raise_query_error(exc: ConversationQueryError) -> None:
    status = 400 if exc.code in {
        ChatErrorCode.INVALID_CHAT_CURSOR,
        ChatErrorCode.INVALID_MESSAGE_CURSOR,
    } else 404
    raise _error(status, exc.code.value, str(exc)) from exc


def _raise_command_error(exc: ConversationCommandError) -> None:
    if exc.code in {
        ChatErrorCode.CHAT_NOT_FOUND,
        ChatErrorCode.BRANCH_NOT_FOUND,
        ChatErrorCode.MESSAGE_NOT_FOUND,
    }:
        status = 404
    elif exc.code == ChatErrorCode.INVALID_TURN_COMMAND:
        status = 400
    else:
        status = 409
    raise _error(status, exc.code.value, str(exc)) from exc


class ChatPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value


class BranchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_archived: bool


class ChatDeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_irreversible: bool
    request_id: UUID


class MessageFeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: UUID
    rating: MessageFeedbackRating


@router.get("")
async def list_chats_v2(
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await ConversationQueryService().alist_chats(user_id, cursor=cursor, limit=limit)
    except ConversationQueryError as exc:
        _raise_query_error(exc)


@router.post("/turns", status_code=202)
async def create_new_chat_turn(
    body: TurnCommand,
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await run_in_threadpool(create_turn, user_id, body)
    except ConversationCommandError as exc:
        _raise_command_error(exc)


@router.get("/{chat_id}")
async def get_chat_tree(
    chat_id: int,
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await ConversationQueryService().aget_conversation(user_id, chat_id)
    except ConversationQueryError as exc:
        _raise_query_error(exc)


@router.post("/{chat_id}/turns", status_code=202)
async def create_chat_turn(
    chat_id: int,
    body: TurnCommand,
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await run_in_threadpool(partial(create_turn, user_id, body, chat_id=chat_id))
    except ConversationCommandError as exc:
        _raise_command_error(exc)


@router.get("/{chat_id}/branches/{branch_id}/messages")
async def get_branch_messages(
    chat_id: int,
    branch_id: UUID,
    before: str | None = None,
    limit: int | None = Query(default=None, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await ConversationQueryService().aget_message_path(
            user_id,
            chat_id,
            branch_id,
            before=before,
            limit=limit,
        )
    except ConversationQueryError as exc:
        _raise_query_error(exc)


@message_router.get("/{message_id}/match-results")
async def get_message_match_results(
    message_id: UUID,
    page: int = Query(default=1, ge=1),
    limit: int | None = Query(default=None, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return await ConversationQueryService().aget_message_match_results(
            user_id,
            message_id,
            page=page,
            limit=limit,
        )
    except ConversationQueryError as exc:
        _raise_query_error(exc)


@message_router.put("/{message_id}/feedback", response_model=MessageFeedbackView)
async def set_message_feedback(
    message_id: UUID,
    body: MessageFeedbackBody,
    user_id: int = Depends(get_current_user_id),
):
    try:
        row = await run_in_threadpool(
            chat_feedback_repo.set_message_feedback,
            user_id,
            message_id,
            body.branch_id,
            body.rating.value,
        )
    except chat_feedback_repo.MessageFeedbackTargetError as exc:
        raise _error(409, "INVALID_MESSAGE_FEEDBACK_TARGET", str(exc)) from exc
    return MessageFeedbackView.model_validate(row)


@message_router.delete("/{message_id}/feedback")
async def delete_message_feedback(
    message_id: UUID,
    user_id: int = Depends(get_current_user_id),
):
    await run_in_threadpool(chat_feedback_repo.delete_message_feedback, user_id, message_id)
    return {"ok": True}


@router.patch("/{chat_id}")
async def patch_chat(
    chat_id: int,
    body: ChatPatch,
    user_id: int = Depends(get_current_user_id),
):
    changed = await run_in_threadpool(chats_repo.rename_chat, user_id, chat_id, body.title)
    if not changed:
        raise _error(404, ChatErrorCode.CHAT_NOT_FOUND.value, "会话不存在")
    return {"ok": True, "title": body.title.strip()}


@router.patch("/{chat_id}/branches/{branch_id}")
async def patch_branch(
    chat_id: int,
    branch_id: UUID,
    body: BranchPatch,
    user_id: int = Depends(get_current_user_id),
):
    try:
        changed = await run_in_threadpool(
            partial(
                chats_repo.update_branch_metadata,
                user_id,
                chat_id,
                branch_id,
                is_archived=body.is_archived,
            )
        )
    except ValueError as exc:
        raise _error(409, "ACTIVE_BRANCH_CANNOT_ARCHIVE", str(exc)) from exc
    if not changed:
        raise _error(404, ChatErrorCode.BRANCH_NOT_FOUND.value, "分支不存在")
    return {"ok": True}


@router.delete("/{chat_id}")
async def delete_chat_v2(
    chat_id: int,
    body: ChatDeleteBody = Body(...),
    user_id: int = Depends(get_current_user_id),
):
    if not body.confirm_irreversible:
        raise _error(
            400,
            "IRREVERSIBLE_CONFIRMATION_REQUIRED",
            "删除整个会话后不可恢复，请明确确认",
        )
    try:
        result = await run_in_threadpool(
            chats_repo.hard_delete_chat,
            user_id,
            chat_id,
            body.request_id,
        )
    except ValueError as exc:
        raise _error(409, "DELETE_REQUEST_CONFLICT", str(exc)) from exc
    if result is None:
        raise _error(404, ChatErrorCode.CHAT_NOT_FOUND.value, "会话不存在")
    return {"ok": True, **result}
