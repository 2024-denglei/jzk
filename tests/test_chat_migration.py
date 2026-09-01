"""旧会话迁移的纯函数契约。"""

from __future__ import annotations

from uuid import UUID

from dialogue.chat_migration import (
    legacy_branch_id,
    legacy_message_id,
    normalize_legacy_messages,
    normalize_legacy_state,
)


def test_legacy_ids_are_deterministic_and_scoped_to_chat():
    assert legacy_branch_id(7) == legacy_branch_id(7)
    assert legacy_branch_id(7) != legacy_branch_id(8)
    assert legacy_message_id(7, 0) != legacy_message_id(7, 1)


def test_legacy_message_roles_are_normalized_without_losing_content():
    messages, warnings = normalize_legacy_messages(
        '[{"role":"bot","content":"结果"},{"role":"custom","content":"备注"}]'
    )
    assert [item["role"] for item in messages] == ["assistant", "system"]
    assert [item["content"] for item in messages] == ["结果", "备注"]
    assert "message:1:unknown_role:custom" in warnings

    malformed, malformed_warnings = normalize_legacy_messages("{broken")
    assert malformed == []
    assert malformed_warnings == ["messages_json:invalid_json"]


def test_legacy_state_only_keeps_v2_recoverable_fields():
    match_id = UUID("11111111-1111-1111-1111-111111111111")
    state, recoverable, warnings = normalize_legacy_state(
        {
            "parsed_features": {"height": 180},
            "constraints": {"height": "must", "bad": "invalid"},
            "dialogue_state": "matching",
            "pending_relaxations": ["height"],
            "history": [{"role": "user", "content": "不应复制"}],
        },
        match_id,
    )
    assert recoverable is True
    assert state["latest_match_run_id"] == str(match_id)
    assert state["constraints"] == {"height": "must"}
    assert "history" not in state
    assert "state_json:invalid_constraints_removed" in warnings
