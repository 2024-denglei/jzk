import json

import config
from dialogue.agent_trace import read_session_traces


def _write_trace(path, **overrides):
    record = {
        "trace_id": "trace-default",
        "session_id": "session-1",
        "user_id": 7,
        "started_at": "2026-08-31T12:00:00+00:00",
        "steps": [{"type": "tool_call", "name": "submit_preference_profile"}],
    }
    record.update(overrides)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def test_reads_session_turns_in_time_order_and_keeps_trace_details(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", str(tmp_path))
    session_dir = tmp_path / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    _write_trace(session_dir / "later.json", trace_id="trace-2", started_at="2026-08-31T12:02:00+00:00")
    _write_trace(session_dir / "earlier.json", trace_id="trace-1", started_at="2026-08-31T12:01:00+00:00")

    turns = read_session_traces("session-1", user_id=7)

    assert [turn["trace_id"] for turn in turns] == ["trace-1", "trace-2"]
    assert turns[0]["steps"][0]["name"] == "submit_preference_profile"


def test_reader_filters_wrong_owner_session_and_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", str(tmp_path))
    session_dir = tmp_path / "sessions" / "session-1"
    session_dir.mkdir(parents=True)
    _write_trace(session_dir / "valid.json", trace_id="valid")
    _write_trace(session_dir / "wrong-user.json", trace_id="wrong-user", user_id=99)
    _write_trace(session_dir / "wrong-session.json", trace_id="wrong-session", session_id="session-2")
    (session_dir / "broken.json").write_text("not json", encoding="utf-8")

    turns = read_session_traces("session-1", user_id=7)

    assert [turn["trace_id"] for turn in turns] == ["valid"]


def test_reader_rejects_path_traversal_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRACE_DIR", str(tmp_path))
    outside = tmp_path / "secret.json"
    _write_trace(outside, session_id="../secret")

    assert read_session_traces("../secret", user_id=7) == []
