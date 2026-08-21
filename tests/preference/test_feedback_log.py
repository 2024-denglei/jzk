import json

from api.feedback import record_feedback


def test_record_feedback_writes_event(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCH_LOG_DIR", str(tmp_path))
    record_feedback("s1", "A", "like")
    record_feedback("s1", "B", "dislike")
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(x)["event"] for x in lines]
    assert events == ["like", "dislike"]
