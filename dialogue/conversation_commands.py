"""分支化长期对话命令：追加、显式分叉、当前线路编辑和幂等生成。"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation

import config
from db import chats_repo
from db.chat_models import (
    ChatErrorCode,
    ForkReason,
    MessageRole,
    MessageStatus,
    TurnAction,
    TurnCommand,
    TurnCreationResult,
)
from db.pg import db_session
from dialogue.state_schema import STATE_SCHEMA_VERSION, dump_state, empty_state


class ConversationCommandError(RuntimeError):
    def __init__(self, code: ChatErrorCode, message: str):
        super().__init__(message)
        self.code = code


def _result_from_existing(row: dict[str, Any]) -> TurnCreationResult:
    return TurnCreationResult(
        chat_id=int(row["chat_id"]),
        branch_id=UUID(str(row["branch_id"])),
        user_message_id=UUID(str(row["user_message_id"])),
        assistant_message_id=UUID(str(row["assistant_message_id"])),
        generation_id=UUID(str(row["generation_id"])),
        branch_created=ForkReason(str(row["fork_reason"])) != ForkReason.ROOT,
        fork_reason=ForkReason(str(row["fork_reason"])),
        idempotent_replay=True,
    )


def _title_from_content(content: str) -> str:
    compact = " ".join(content.strip().split())
    return compact[:40] or "对话"


def _branch_name(branch_count: int) -> str:
    """根线路计入 branch_count，因此下一条显式分支从 1 开始编号。"""
    return f"分支{max(1, branch_count)}"


def _require_message(
    conn,
    *,
    chat_id: int,
    message_id: UUID | None,
    branch_head_id: UUID | None,
) -> dict[str, Any]:
    if message_id is None:
        raise ConversationCommandError(ChatErrorCode.MESSAGE_NOT_FOUND, "缺少目标消息")
    message = chats_repo.get_message(conn, chat_id, message_id)
    if message is None or not chats_repo.message_is_on_branch_path(
        conn, chat_id, branch_head_id, message_id
    ):
        raise ConversationCommandError(ChatErrorCode.MESSAGE_NOT_FOUND, "目标消息不在当前分支")
    return message


def _state_after(message: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if message is None:
        return empty_state(), True
    if not message.get("state_recoverable", True):
        raise ConversationCommandError(
            ChatErrorCode.STATE_NOT_RECOVERABLE,
            "该历史节点没有可靠状态，不能从此处继续",
        )
    return dump_state(message.get("state_after_json") or {}), True


def _require_complete_branch_point(message: dict[str, Any]) -> None:
    """分支只能接在一个完整的 AI 回复单元之后。

    候选人工具结果通过 match_run_id 绑定在 assistant 消息上，因此该消息同时也是
    “AI 回复 + 候选人快照”的不可拆分尾节点。
    """
    if (
        message.get("role") != MessageRole.ASSISTANT.value
        or message.get("status") != MessageStatus.COMPLETED.value
    ):
        raise ConversationCommandError(
            ChatErrorCode.INVALID_TURN_COMMAND,
            "只能从已完成的 AI 回复或其候选人结果后创建分支",
        )


def create_turn(
    user_id: int,
    command: TurnCommand,
    *,
    chat_id: int | None = None,
) -> TurnCreationResult:
    """原子创建用户消息、AI 占位消息和持久生成任务。"""
    try:
        return _create_turn(user_id, command, chat_id=chat_id)
    except UniqueViolation:
        # 客户端并发重试可能同时越过第一次幂等读取；唯一索引决定胜者。
        with db_session() as conn:
            existing = chats_repo.find_turn_by_request(conn, user_id, command.client_request_id)
        if existing is not None:
            return _result_from_existing(existing)
        raise


def _create_turn(
    user_id: int,
    command: TurnCommand,
    *,
    chat_id: int | None,
) -> TurnCreationResult:
    with db_session() as conn:
        existing = chats_repo.find_turn_by_request(conn, user_id, command.client_request_id)
        if existing is not None:
            return _result_from_existing(existing)

        branch_created = False
        source_message: dict[str, Any] | None = None

        if chat_id is None:
            if (
                command.action != TurnAction.APPEND
                or command.branch_id is not None
                or command.parent_message_id is not None
            ):
                raise ConversationCommandError(
                    ChatErrorCode.INVALID_TURN_COMMAND,
                    "新会话只能提交无父节点的追加消息",
                )
            chat_id = chats_repo.create_chat(
                conn,
                user_id,
                title=_title_from_content(command.content),
            )
            branch_id = uuid4()
            fork_reason = ForkReason.ROOT
            chats_repo.insert_branch(
                conn,
                branch_id=branch_id,
                chat_id=chat_id,
                parent_branch_id=None,
                forked_from_message_id=None,
                derived_from_message_id=None,
                name="主线",
                system_name="主线",
                fork_reason=fork_reason,
                head_message_id=None,
                created_by="system",
            )
            branch = {"id": branch_id, "head_message_id": None, "version": 0, "is_archived": False}
            parent_message = None
            # 根分支是新会话的固有结构；branch_created 只提示本次操作额外分叉。
            branch_created = False
            branch_delta = 1
        else:
            chat = chats_repo.lock_chat(conn, user_id, chat_id)
            if chat is None or int(chat.get("storage_version") or 1) != 2:
                raise ConversationCommandError(ChatErrorCode.CHAT_NOT_FOUND, "会话不存在")
            selected_branch_id = command.branch_id or chat.get("active_branch_id")
            if selected_branch_id is None:
                raise ConversationCommandError(ChatErrorCode.BRANCH_NOT_FOUND, "会话没有可用分支")
            selected_branch_id = UUID(str(selected_branch_id))
            branch = chats_repo.lock_branch(conn, chat_id, selected_branch_id)
            if branch is None:
                raise ConversationCommandError(ChatErrorCode.BRANCH_NOT_FOUND, "分支不存在")
            if branch.get("is_archived"):
                raise ConversationCommandError(ChatErrorCode.BRANCH_ARCHIVED, "请先恢复已归档分支")

            selected_head = (
                UUID(str(branch["head_message_id"])) if branch.get("head_message_id") else None
            )
            # 普通追加沿用当前分支的来源；只有实际分叉时才覆盖原因。
            fork_reason = ForkReason(str(branch["fork_reason"]))
            fork_parent_id: UUID | None

            if command.action == TurnAction.APPEND:
                fork_parent_id = command.parent_message_id or selected_head
                parent_message = _require_message(
                    conn,
                    chat_id=chat_id,
                    message_id=fork_parent_id,
                    branch_head_id=selected_head,
                )
                if fork_parent_id != selected_head:
                    fork_reason = ForkReason.CONCURRENT_SEND
                else:
                    # 用户已点终止但 worker 尚未收尾时，先落地取消，避免立刻追问被挡住
                    chats_repo.force_stop_branch_generations(
                        conn,
                        selected_branch_id,
                        only_cancel_requested=True,
                    )
                    if chats_repo.branch_has_active_generation(conn, selected_branch_id):
                        raise ConversationCommandError(
                            ChatErrorCode.BRANCH_GENERATION_ACTIVE,
                            "当前分支已有正在运行的生成任务",
                        )
            elif command.action == TurnAction.REWIND_CONTINUE:
                fork_reason = ForkReason.REWIND_CONTINUE
                fork_parent_id = command.parent_message_id
                parent_message = _require_message(
                    conn,
                    chat_id=chat_id,
                    message_id=fork_parent_id,
                    branch_head_id=selected_head,
                )
                source_message = parent_message
            elif command.action == TurnAction.EDIT_RESEND:
                # 编辑会替换后续线路（含进行中的助手消息），直接强制收尾活跃生成
                chats_repo.force_stop_branch_generations(conn, selected_branch_id)
                source_message = _require_message(
                    conn,
                    chat_id=chat_id,
                    message_id=command.derived_from_message_id,
                    branch_head_id=selected_head,
                )
                if source_message["role"] != MessageRole.USER.value:
                    raise ConversationCommandError(
                        ChatErrorCode.INVALID_TURN_COMMAND,
                        "只能编辑用户消息",
                    )
                fork_parent_id = (
                    UUID(str(source_message["parent_message_id"]))
                    if source_message.get("parent_message_id")
                    else None
                )
                if command.parent_message_id is not None and command.parent_message_id != fork_parent_id:
                    raise ConversationCommandError(
                        ChatErrorCode.INVALID_TURN_COMMAND,
                        "编辑消息的父节点不一致",
                    )
                parent_message = (
                    chats_repo.get_message(conn, chat_id, fork_parent_id)
                    if fork_parent_id
                    else None
                )

            needs_branch = (
                command.action == TurnAction.REWIND_CONTINUE
                or fork_reason == ForkReason.CONCURRENT_SEND
            )
            if needs_branch:
                _require_complete_branch_point(parent_message)
                if int(chat["branch_count"]) >= config.CHAT_BRANCH_MAX_PER_CHAT:
                    raise ConversationCommandError(
                        ChatErrorCode.CHAT_BRANCH_LIMIT_REACHED,
                        "会话分支数量已达上限",
                    )
                branch_id = uuid4()
                system_name = _branch_name(int(chat["branch_count"]))
                chats_repo.insert_branch(
                    conn,
                    branch_id=branch_id,
                    chat_id=chat_id,
                    parent_branch_id=selected_branch_id,
                    forked_from_message_id=fork_parent_id,
                    derived_from_message_id=command.derived_from_message_id,
                    name=system_name,
                    system_name=system_name,
                    fork_reason=fork_reason,
                    head_message_id=fork_parent_id,
                    created_by="user",
                )
                branch = {
                    "id": branch_id,
                    "head_message_id": fork_parent_id,
                    "version": 0,
                    "is_archived": False,
                }
                branch_created = True
                branch_delta = 1
            else:
                branch_id = selected_branch_id
                branch_delta = 0

        state_after, state_recoverable = _state_after(parent_message)
        parent_depth = int(parent_message["depth"]) if parent_message is not None else -1

        user_message_id = uuid4()
        chats_repo.insert_message(
            conn,
            message_id=user_message_id,
            chat_id=chat_id,
            branch_id=branch_id,
            parent_message_id=(
                UUID(str(parent_message["id"])) if parent_message is not None else None
            ),
            derived_from_message_id=None,
            role=MessageRole.USER,
            status=MessageStatus.COMPLETED,
            content=command.content.strip(),
            state_schema_version=STATE_SCHEMA_VERSION,
            state_after=state_after,
            state_recoverable=state_recoverable,
            depth=parent_depth + 1,
            client_request_id=command.client_request_id,
        )
        assistant_parent_id = user_message_id
        assistant_depth = parent_depth + 2
        message_delta = 2

        chat = chats_repo.lock_chat(conn, user_id, chat_id)
        assert chat is not None
        if (
            command.action != TurnAction.EDIT_RESEND
            and int(chat["message_count"]) + message_delta > config.CHAT_MESSAGE_MAX_PER_CHAT
        ):
            raise ConversationCommandError(
                ChatErrorCode.CHAT_MESSAGE_LIMIT_REACHED,
                "会话消息数量已达上限",
            )

        assistant_message_id = uuid4()
        chats_repo.insert_message(
            conn,
            message_id=assistant_message_id,
            chat_id=chat_id,
            branch_id=branch_id,
            parent_message_id=assistant_parent_id,
            derived_from_message_id=None,
            role=MessageRole.ASSISTANT,
            status=MessageStatus.GENERATING,
            content="",
            state_schema_version=STATE_SCHEMA_VERSION,
            state_after=state_after,
            state_recoverable=state_recoverable,
            depth=assistant_depth,
        )
        generation_id = uuid4()
        chats_repo.insert_generation(
            conn,
            generation_id=generation_id,
            user_id=user_id,
            chat_id=chat_id,
            branch_id=branch_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            client_request_id=command.client_request_id,
        )
        if not chats_repo.update_branch_head(
            conn,
            chat_id=chat_id,
            branch_id=branch_id,
            head_message_id=assistant_message_id,
            expected_version=int(branch["version"]),
        ):
            raise ConversationCommandError(
                ChatErrorCode.INVALID_TURN_COMMAND,
                "分支已发生变化，请重新加载",
            )
        chats_repo.update_chat_after_turn(
            conn,
            chat_id=chat_id,
            branch_id=branch_id,
            message_delta=message_delta,
            branch_delta=branch_delta,
        )
        if command.action == TurnAction.EDIT_RESEND:
            chats_repo.prune_unreachable_messages(
                conn,
                chat_id=chat_id,
                request_id=command.client_request_id,
            )

    return TurnCreationResult(
        chat_id=chat_id,
        branch_id=branch_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        generation_id=generation_id,
        branch_created=branch_created,
        fork_reason=fork_reason,
    )
