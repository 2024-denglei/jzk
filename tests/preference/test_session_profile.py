from dialogue.session import SessionContext


def test_replace_profile_is_snapshot_not_merge():
    s = SessionContext(owner_user_id=1)
    s.replace_profile({"schema_version": "1.0", "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}}})
    s.replace_profile({"schema_version": "1.0", "attributes": {"height_cm": {"constraint": "prefer", "weight": 0.5, "range": {"min": 175}}}})
    assert "abo_blood" not in s.preference_profile["attributes"]
    assert "height_cm" in s.preference_profile["attributes"]


def test_checkpoint_includes_profile():
    s = SessionContext(owner_user_id=1)
    s.replace_profile({"schema_version": "1.0", "attributes": {}})
    cp = s.export_checkpoint()
    s.replace_profile({"schema_version": "1.0", "attributes": {"education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]}}})
    s.restore_checkpoint(cp)
    assert s.preference_profile["attributes"] == {}


def test_checkpoint_and_storage_restore_match_result_reference():
    s = SessionContext(owner_user_id=1)
    s.match_result_id = "11111111-1111-1111-1111-111111111111"
    s.match_total = 4303
    s.match_next_cursor = "cursor-2"
    cp = s.export_checkpoint()
    s.match_result_id = "changed"
    s.restore_checkpoint(cp)
    assert (s.match_result_id, s.match_total, s.match_next_cursor) == (
        "11111111-1111-1111-1111-111111111111", 4303, "cursor-2"
    )
    loaded = SessionContext.from_storage_dict(s.to_storage_dict())
    assert (loaded.match_result_id, loaded.match_total, loaded.match_next_cursor) == (
        s.match_result_id, 4303, "cursor-2"
    )
