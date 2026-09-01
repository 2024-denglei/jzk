"""客户端与管理端共享的分支化会话查询服务。"""

from __future__ import annotations

from functools import partial
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

import config
from db import chat_queries_repo
from db.chat_models import (
    BranchSummary,
    ChatErrorCode,
    ChatListPage,
    ChatMessageView,
    ChatSummary,
    ConversationTreeView,
    MatchRunSummary,
    MessagePathPage,
)
from db.pg import db_session
from dialogue.conversation_cursors import (
    InvalidConversationCursor,
    decode_chat_list_cursor,
    decode_message_cursor,
    encode_chat_list_cursor,
    encode_message_cursor,
)


class ConversationQueryError(RuntimeError):
    def __init__(self, code: ChatErrorCode, message: str):
        super().__init__(message)
        self.code = code


def _chat_summary(row: dict[str, Any]) -> ChatSummary:
    return ChatSummary.model_validate(row)


def _message_view(row: dict[str, Any]) -> ChatMessageView:
    match_run = None
    if row.get("match_total") is not None:
        match_run = MatchRunSummary(
            message_id=row["id"],
            total=row["match_total"],
            model_version=row["model_version"],
            dataset_version=row["dataset_version"],
            snapshot_schema_version=row["snapshot_schema_version"],
            snapshot_source=row["snapshot_source"],
            created_at=row["match_created_at"],
        )
    payload = {
        key: row[key]
        for key in (
            "id",
            "parent_message_id",
            "derived_from_message_id",
            "created_in_branch_id",
            "role",
            "status",
            "content",
            "content_format",
            "depth",
            "state_recoverable",
            "created_at",
            "completed_at",
        )
    }
    payload["match_run"] = match_run
    return ChatMessageView.model_validate(payload)


class ConversationQueryService:
    """同一服务按连接角色读取；DTO 和消息路径语义保持一致。"""

    def __init__(self, *, admin: bool = False):
        self.admin = admin

    def list_chats(
        self,
        user_id: int,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> ChatListPage:
        page_size = min(
            max(1, limit or config.CHAT_LIST_PAGE_SIZE_DEFAULT),
            config.CHAT_LIST_PAGE_SIZE_MAX,
        )
        before_updated_at = None
        before_chat_id = None
        if cursor:
            try:
                before_updated_at, before_chat_id = decode_chat_list_cursor(cursor, user_id)
            except InvalidConversationCursor as exc:
                raise ConversationQueryError(ChatErrorCode.INVALID_CHAT_CURSOR, str(exc)) from exc

        with db_session(admin=self.admin) as conn:
            rows = chat_queries_repo.list_chats(
                conn,
                user_id,
                before_updated_at=before_updated_at,
                before_chat_id=before_chat_id,
                limit=page_size + 1,
            )
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        next_cursor = None
        if has_more and visible:
            last = visible[-1]
            next_cursor = encode_chat_list_cursor(user_id, last["updated_at"], int(last["id"]))
        return ChatListPage(
            items=[_chat_summary(row) for row in visible],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_conversation(self, user_id: int, chat_id: int) -> ConversationTreeView:
        with db_session(admin=self.admin) as conn:
            chat = chat_queries_repo.get_chat(conn, user_id, chat_id)
            if chat is None:
                raise ConversationQueryError(ChatErrorCode.CHAT_NOT_FOUND, "会话不存在")
            branches = chat_queries_repo.list_branches(
                conn,
                chat_id,
                UUID(str(chat["active_branch_id"])) if chat.get("active_branch_id") else None,
            )
        return ConversationTreeView(
            chat=_chat_summary(chat),
            branches=[BranchSummary.model_validate(row) for row in branches],
        )

    def get_message_path(
        self,
        user_id: int,
        chat_id: int,
        branch_id: UUID,
        *,
        before: str | None = None,
        limit: int | None = None,
    ) -> MessagePathPage:
        page_size = min(
            max(1, limit or config.CHAT_MESSAGE_PAGE_SIZE_DEFAULT),
            config.CHAT_MESSAGE_PAGE_SIZE_MAX,
        )
        with db_session(admin=self.admin) as conn:
            branch = chat_queries_repo.get_branch_for_user(conn, user_id, chat_id, branch_id)
            if branch is None:
                raise ConversationQueryError(ChatErrorCode.BRANCH_NOT_FOUND, "分支不存在")
            head_id = UUID(str(branch["head_message_id"])) if branch.get("head_message_id") else None
            if head_id is None:
                return MessagePathPage(chat_id=chat_id, branch_id=branch_id, items=[])
            start_id = head_id
            if before:
                try:
                    start_id = decode_message_cursor(before, user_id, chat_id, branch_id)
                except InvalidConversationCursor as exc:
                    raise ConversationQueryError(
                        ChatErrorCode.INVALID_MESSAGE_CURSOR, str(exc)
                    ) from exc
                if not chat_queries_repo.message_is_on_path(conn, chat_id, head_id, start_id):
                    raise ConversationQueryError(
                        ChatErrorCode.INVALID_MESSAGE_CURSOR,
                        "消息游标不属于当前分支路径",
                    )
            rows = chat_queries_repo.get_message_path(
                conn,
                chat_id,
                start_id,
                limit=page_size + 1,
            )

        has_more = len(rows) > page_size
        visible_desc = rows[:page_size]
        next_before = None
        if has_more:
            next_before = encode_message_cursor(
                user_id,
                chat_id,
                branch_id,
                UUID(str(rows[page_size]["id"])),
            )
        return MessagePathPage(
            chat_id=chat_id,
            branch_id=branch_id,
            items=[_message_view(row) for row in reversed(visible_desc)],
            next_before=next_before,
            has_more=has_more,
        )

    async def alist_chats(self, user_id: int, **kwargs: Any) -> ChatListPage:
        return await run_in_threadpool(partial(self.list_chats, user_id, **kwargs))

    async def aget_conversation(self, user_id: int, chat_id: int) -> ConversationTreeView:
        return await run_in_threadpool(self.get_conversation, user_id, chat_id)

    async def aget_message_path(
        self,
        user_id: int,
        chat_id: int,
        branch_id: UUID,
        **kwargs: Any,
    ) -> MessagePathPage:
        return await run_in_threadpool(
            partial(self.get_message_path, user_id, chat_id, branch_id, **kwargs)
        )
