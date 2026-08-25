import json
from decimal import Decimal

from core.preference.match_log import append_feedback_event, append_match_turn


def test_write_turn_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCH_LOG_DIR", str(tmp_path))
    append_match_turn({
        "schema_version": "1.0",
        "session_id": "s1",
        "preference_profile": {"schema_version": "1.0", "attributes": {}},
        "filtered_count": 2,
        "candidates": [{"code": "A", "score": 0.9, "rank": 1, "field_scores": [], "attrs": {}}],
    })
    append_feedback_event({
        "session_id": "s1",
        "donor_code": "A",
        "event": "like",
    })
    turns = (tmp_path / "turns.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(turns[0])["session_id"] == "s1"
    assert "semen_test" not in turns[0]
    assert json.loads(events[0])["event"] == "like"


def test_decimal_actual_can_be_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCH_LOG_DIR", str(tmp_path))
    append_match_turn({
        "candidates": [{"attrs": {"weight_kg": Decimal("68.50")}}],
    })
    row = json.loads((tmp_path / "turns.jsonl").read_text(encoding="utf-8"))
    assert row["candidates"][0]["attrs"]["weight_kg"] == 68.5
