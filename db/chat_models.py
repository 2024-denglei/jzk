"""分支化长期对话 V2 的稳定领域契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

import config


STATE_SCHEMA_VERSION = 1


class ChatErrorCode(StrEnum):
    CHAT_NOT_FOUND = "CHAT_NOT_FOUND"
    BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    GENERATION_NOT_FOUND = "GENERATION_NOT_FOUND"
    MATCH_SNAPSHOT_NOT_FOUND = "MATCH_SNAPSHOT_NOT_FOUND"
    STATE_NOT_RECOVERABLE = "STATE_NOT_RECOVERABLE"
    CHAT_BRANCH_LIMIT_REACHED = "CHAT_BRANCH_LIMIT_REACHED"
    CHAT_MESSAGE_LIMIT_REACHED = "CHAT_MESSAGE_LIMIT_REACHED"
    BRANCH_GENERATION_ACTIVE = "BRANCH_GENERATION_ACTIVE"
    BRANCH_ARCHIVED = "BRANCH_ARCHIVED"
    INVALID_TURN_COMMAND = "INVALID_TURN_COMMAND"
    INVALID_CHAT_CURSOR = "INVALID_CHAT_CURSOR"
    INVALID_MESSAGE_CURSOR = "INVALID_MESSAGE_CURSOR"


class TurnAction(StrEnum):
    APPEND = "append"
    REWIND_CONTINUE = "rewind_continue"
    EDIT_RESEND = "edit_resend"


class ForkReason(StrEnum):
    ROOT = "root"
    REWIND_CONTINUE = "rewind_continue"
    EDIT_RESEND = "edit_resend"
    REGENERATE = "regenerate"
    CONCURRENT_SEND = "concurrent_send"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(StrEnum):
    GENERATING = "generating"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class MessageFeedbackRating(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class MatchRunStatus(StrEnum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class SnapshotSource(StrEnum):
    NATIVE = "native"
    LEGACY_BACKFILL = "legacy_backfill"


TERMINAL_MESSAGE_STATUSES = frozenset({
    MessageStatus.COMPLETED,
    MessageStatus.STOPPED,
    MessageStatus.FAILED,
})
TERMINAL_GENERATION_STATUSES = frozenset({
    GenerationStatus.COMPLETED,
    GenerationStatus.STOPPED,
    GenerationStatus.FAILED,
})


def message_status_transition_allowed(current: MessageStatus, target: MessageStatus) -> bool:
    if current == target:
        return True
    return current == MessageStatus.GENERATING and target in TERMINAL_MESSAGE_STATUSES


def generation_status_transition_allowed(current: GenerationStatus, target: GenerationStatus) -> bool:
    if current == target:
        return True
    if current == GenerationStatus.QUEUED:
        return target in {
            GenerationStatus.RUNNING,
            GenerationStatus.STOPPED,
            GenerationStatus.FAILED,
        }
    if current == GenerationStatus.RUNNING:
        return target == GenerationStatus.QUEUED or target in TERMINAL_GENERATION_STATUSES
    return False


class DialogueStateSnapshotV1(BaseModel):
    """消息提交后可恢复的最小状态；不含消息历史和候选详情。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_schema_version: int = Field(default=STATE_SCHEMA_VERSION, frozen=True)
    parsed_features: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, str] = Field(default_factory=dict)
    dialogue_state: str = "collecting"
    pending_relaxations: list[str] = Field(default_factory=list)
    preference_profile: dict[str, Any] | None = None
    latest_match_run_id: UUID | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "DialogueStateSnapshotV1":
        if self.state_schema_version != STATE_SCHEMA_VERSION:
            raise ValueError(f"仅支持状态版本 {STATE_SCHEMA_VERSION}")
        invalid = {value for value in self.constraints.values() if value not in {"must", "prefer"}}
        if invalid:
            raise ValueError("constraints 仅允许 must 或 prefer")
        return self


class TurnCommand(BaseModel):
    """创建一轮对话的幂等命令。"""

    model_config = ConfigDict(extra="forbid")

    branch_id: UUID | None = None
    parent_message_id: UUID | None = None
    action: TurnAction = TurnAction.APPEND
    derived_from_message_id: UUID | None = None
    content: str = Field(default="", max_length=config.CHAT_MESSAGE_MAX_CHARS)
    client_request_id: UUID

    @model_validator(mode="after")
    def validate_action(self) -> "TurnCommand":
        content = self.content.strip()
        if not content:
            raise ValueError("消息正文不能为空")
        if self.action == TurnAction.EDIT_RESEND and self.derived_from_message_id is None:
            raise ValueError("编辑重发必须指定 derived_from_message_id")
        if self.action in {TurnAction.APPEND, TurnAction.REWIND_CONTINUE} and self.derived_from_message_id:
            raise ValueError("追加或回溯继续不能指定 derived_from_message_id")
        return self


class MatchRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    total: int = Field(ge=0)
    model_version: str
    dataset_version: str
    snapshot_schema_version: int = Field(ge=1)
    snapshot_source: SnapshotSource
    created_at: datetime


class MessageFeedbackView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    rating: MessageFeedbackRating
    updated_at: datetime


class ChatMessageView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    parent_message_id: UUID | None
    derived_from_message_id: UUID | None
    created_in_branch_id: UUID
    role: MessageRole
    status: MessageStatus
    content: str
    content_format: str = "markdown"
    depth: int = Field(ge=0)
    state_recoverable: bool = True
    generation_id: UUID | None = None
    feedback: MessageFeedbackView | None = None
    match_run: MatchRunSummary | None = None
    created_at: datetime
    completed_at: datetime | None = None
class BranchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    parent_branch_id: UUID | None
    forked_from_message_id: UUID | None
    derived_from_message_id: UUID | None
    name: str
    system_name: str
    fork_reason: ForkReason
    head_message_id: UUID | None
    message_count: int = Field(ge=0)
    last_message_preview: str = ""
    is_active: bool = False
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime


class ChatSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int
    title: str
    storage_version: Literal[2] = 2
    active_branch_id: UUID | None
    active_branch_name: str | None = None
    branch_count: int = Field(ge=0)
    message_count: int = Field(ge=0)
    last_message_preview: str = ""
    created_at: datetime
    updated_at: datetime


class MessagePathPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    branch_id: UUID
    items: list[ChatMessageView]
    next_before: str | None = None
    has_more: bool = False


class ChatListPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ChatSummary]
    next_cursor: str | None = None
    has_more: bool = False


class ConversationTreeView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat: ChatSummary
    branches: list[BranchSummary]


class TurnCreationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    branch_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    generation_id: UUID
    branch_created: bool
    fork_reason: ForkReason
    idempotent_replay: bool = False


class GenerationRunView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    user_id: int
    chat_id: int
    branch_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    status: GenerationStatus
    model: str | None = None
    prompt_version: str | None = None
    cancel_requested_at: datetime | None = None
    attempt_count: int = Field(ge=0)
    error_type: str | None = None
    error_message_safe: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
