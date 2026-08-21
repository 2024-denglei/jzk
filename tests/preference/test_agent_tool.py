from dialogue.agent_tools import SUBMIT_PROFILE_TOOL, run_preference_match
from dialogue.session import SessionContext


def test_tool_name_and_schema():
    assert SUBMIT_PROFILE_TOOL["function"]["name"] == "submit_preference_profile"
    params = SUBMIT_PROFILE_TOOL["function"]["parameters"]
    assert "schema_version" in params["properties"]
    assert "attributes" in params["properties"]


def test_invalid_profile_keeps_previous():
    session = SessionContext()
    good = {"schema_version": "1.0", "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}}}
    session.replace_profile(good)
    candidates, payload = run_preference_match(
        session,
        {"schema_version": "1.0", "attributes": {"code": {"constraint": "must", "weight": 1, "keywords": ["x"]}}},
        fetch_rows=lambda s, p: [],
        log=False,
    )
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert payload["ok"] is False
    assert candidates == []


def test_valid_profile_replaces_and_matches():
    session = SessionContext()
    rows = [{"code": "T", "abo_blood": "O", "height_cm": 180, "specimen_count": 2}]
    candidates, payload = run_preference_match(
        session,
        {
            "schema_version": "1.0",
            "attributes": {
                "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            },
        },
        fetch_rows=lambda s, p: rows,
        log=False,
    )
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert candidates[0]["donor_info"]["code"] == "T"
