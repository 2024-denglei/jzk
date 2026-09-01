"""将尚未迁移的 V1 JSON 会话只读投影为统一 V2 DTO。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from db.chat_models import BranchSummary, ChatMessageView, ChatSummary
from dialogue.chat_migration import (
    legacy_branch_id,
    legacy_message_id,
    normalize_legacy_messages,
    normalize_legacy_state,
)


def _messages(row: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_legacy_messages(row.get("legacy_messages_json"))[0]


def project_legacy_summary(row: dict[str, Any]) -> ChatSummary:
    messages = _messages(row)
    preview = next(
        (str(item.get("content") or "")[:120] for item in reversed(messages) if item.get("content")),
        "",
    )
    return ChatSummary(
        id=int(row["id"]),
        title=str(row.get("title") or "对话"),
        storage_version=1,
        active_branch_id=legacy_branch_id(int(row["id"])),
        active_branch_name="主分支（待迁移）",
        branch_count=1,
        message_count=len(messages),
        last_message_preview=preview,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def project_legacy_branch(row: dict[str, Any]) -> BranchSummary:
    summary = project_legacy_summary(row)
    count = summary.message_count
    return BranchSummary(
        id=summary.active_branch_id,
        parent_branch_id=None,
        forked_from_message_id=None,
        derived_from_message_id=None,
        name="主分支（待迁移）",
        system_name="V1 兼容只读分支",
        fork_reason="root",
        head_message_id=legacy_message_id(summary.id, count - 1) if count else None,
        message_count=count,
        last_message_preview=summary.last_message_preview,
        is_active=True,
        is_archived=False,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def project_legacy_messages(row: dict[str, Any]) -> list[ChatMessageView]:
    chat_id = int(row["id"])
    branch_id = legacy_branch_id(chat_id)
    messages = _messages(row)
    _state, final_recoverable, _warnings = normalize_legacy_state(
        row.get("legacy_state_json"),
        None,
    )
    created_at = row["created_at"]
    return [
        ChatMessageView(
            id=legacy_message_id(chat_id, index),
            parent_message_id=legacy_message_id(chat_id, index - 1) if index else None,
            derived_from_message_id=None,
            created_in_branch_id=branch_id,
            role=message["role"],
            status="completed",
            content=message["content"],
            content_format="markdown",
            depth=index,
            state_recoverable=bool(index == len(messages) - 1 and final_recoverable),
            generation_id=None,
            match_run=None,
            created_at=created_at + timedelta(microseconds=index),
            completed_at=created_at + timedelta(microseconds=index),
        )
        for index, message in enumerate(messages)
    ]
