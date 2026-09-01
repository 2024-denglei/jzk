from uuid import uuid4

import pytest

from dialogue.state_schema import (
    StateNotRecoverable,
    StateSchemaError,
    dump_state,
    empty_state,
    load_state,
)


def test_state_schema_round_trip_excludes_messages_and_candidates():
    payload = empty_state()
    payload["latest_match_run_id"] = str(uuid4())
    saved = dump_state(payload)
    assert saved["state_schema_version"] == 1
    assert "messages" not in saved
    assert "candidates" not in saved
    assert load_state(saved).latest_match_run_id is not None


def test_state_schema_rejects_unknown_version_and_unrecoverable_node():
    with pytest.raises(StateSchemaError, match="暂不支持状态版本"):
        load_state({"state_schema_version": 99})
    with pytest.raises(StateNotRecoverable, match="没有可靠状态"):
        load_state(empty_state(), recoverable=False)

