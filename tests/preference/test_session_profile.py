from dialogue.session import SessionContext


def test_replace_profile_is_snapshot_not_merge():
    s = SessionContext()
    s.replace_profile({"schema_version": "1.0", "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}}})
    s.replace_profile({"schema_version": "1.0", "attributes": {"height_cm": {"constraint": "prefer", "weight": 0.5, "range": {"min": 175}}}})
    assert "abo_blood" not in s.preference_profile["attributes"]
    assert "height_cm" in s.preference_profile["attributes"]


def test_checkpoint_includes_profile():
    s = SessionContext()
    s.replace_profile({"schema_version": "1.0", "attributes": {}})
    cp = s.export_checkpoint()
    s.replace_profile({"schema_version": "1.0", "attributes": {"education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]}}})
    s.restore_checkpoint(cp)
    assert s.preference_profile["attributes"] == {}
