from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from db.chat_models import (
    BranchSummary,
    DialogueStateSnapshotV1,
    ForkReason,
    GenerationStatus,
    MessageStatus,
    TurnAction,
    TurnCommand,
    generation_status_transition_allowed,
    message_status_transition_allowed,
)


def test_dialogue_state_snapshot_rejects_unknown_fields_and_invalid_constraints():
    with pytest.raises(ValidationError, match="constraints"):
        DialogueStateSnapshotV1(constraints={"height": "optional"})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DialogueStateSnapshotV1(messages=[])


def test_dialogue_state_snapshot_is_immutable_and_excludes_history():
    snapshot = DialogueStateSnapshotV1(
        parsed_features={"height": 175},
        constraints={"height": "must"},
    )
    assert "history" not in snapshot.model_dump()
    assert "candidates" not in snapshot.model_dump()
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.dialogue_state = "presenting"


def test_turn_command_requires_content_for_every_supported_action():
    command = TurnCommand(
        action=TurnAction.APPEND,
        content="硕士，身高 175 以上",
        client_request_id=uuid4(),
    )
    assert command.content.startswith("硕士")

    with pytest.raises(ValidationError, match="消息正文不能为空"):
        TurnCommand(action=TurnAction.APPEND, content="  ", client_request_id=uuid4())


def test_edit_requires_source_message_and_regenerate_is_not_supported():
    with pytest.raises(ValidationError, match="编辑重发必须指定"):
        TurnCommand(
            action=TurnAction.EDIT_RESEND,
            content="改成必须 O 型",
            client_request_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="Input should be"):
        TurnCommand.model_validate({
            "action": "regenerate",
            "client_request_id": str(uuid4()),
        })


def test_terminal_message_and_generation_statuses_cannot_reopen():
    assert message_status_transition_allowed(MessageStatus.GENERATING, MessageStatus.COMPLETED)
    assert not message_status_transition_allowed(MessageStatus.STOPPED, MessageStatus.GENERATING)
    assert generation_status_transition_allowed(GenerationStatus.QUEUED, GenerationStatus.RUNNING)
    assert generation_status_transition_allowed(GenerationStatus.RUNNING, GenerationStatus.FAILED)
    assert generation_status_transition_allowed(GenerationStatus.RUNNING, GenerationStatus.QUEUED)
    assert not generation_status_transition_allowed(GenerationStatus.COMPLETED, GenerationStatus.RUNNING)


def test_branch_summary_contract_is_flat_and_has_explicit_fork_metadata():
    now = datetime.now(timezone.utc)
    parent = uuid4()
    fork = uuid4()
    branch = BranchSummary(
        id=uuid4(),
        parent_branch_id=parent,
        forked_from_message_id=fork,
        derived_from_message_id=None,
        name="从匹配结果继续",
        system_name="从匹配结果继续",
        fork_reason=ForkReason.REWIND_CONTINUE,
        head_message_id=uuid4(),
        message_count=8,
        created_at=now,
        updated_at=now,
    )
    assert branch.parent_branch_id == parent
    assert branch.forked_from_message_id == fork
    assert not hasattr(branch, "children")
