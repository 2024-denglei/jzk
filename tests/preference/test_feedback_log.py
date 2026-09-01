import json

from core.preference.match_log import append_feedback_event


def test_record_feedback_writes_event(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCH_LOG_DIR", str(tmp_path))
    append_feedback_event({"message_id": "m1", "donor_code": "A", "event": "like"})
    append_feedback_event({"message_id": "m1", "donor_code": "B", "event": "dislike"})
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(x)["event"] for x in lines]
    assert events == ["like", "dislike"]
