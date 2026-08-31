from core.preference.schema import field_catalog_text, openai_tool_schema
from dialogue.agent_tools import (
    AGENT_SYSTEM_PROMPT,
    SUBMIT_PROFILE_TOOL,
    apply_match_api_response,
    run_preference_match,
    slim_assistant_for_llm,
    tool_failure_payload,
)
from dialogue.session import SessionContext


def test_tool_name_and_schema():
    assert SUBMIT_PROFILE_TOOL["function"]["name"] == "submit_preference_profile"
    params = SUBMIT_PROFILE_TOOL["function"]["parameters"]
    assert "schema_version" in params["properties"]
    attrs = params["properties"]["attributes"]["properties"]
    assert "硕士" in str(attrs["education"])
    assert attrs["education"]["properties"]["values"]["items"]["enum"] == [
        "大专", "本科", "硕士", "博士",
    ]
    assert "smoke_history" in attrs
    assert "不抽烟" in attrs["smoke_history"]["description"]


def test_field_catalog_is_generated_from_registry():
    text = field_catalog_text()
    assert "education" in text
    assert "硕士" in text
    assert "smoke_history" in text
    assert "height_cm" in text
    assert text in AGENT_SYSTEM_PROMPT


def test_invalid_profile_keeps_previous():
    session = SessionContext(owner_user_id=1)
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
    assert payload["retry"] is True
    assert "code" in payload["error"]
    assert candidates == []


def test_valid_profile_replaces_and_matches():
    session = SessionContext(owner_user_id=1)
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
    assert payload["prefer_hits"] == []
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert candidates[0]["donor_info"]["code"] == "T"


def test_prompt_requires_prefer_rerank_wording():
    assert "prefer_hits" in AGENT_SYSTEM_PROMPT
    assert "已按偏好重排" in AGENT_SYSTEM_PROMPT
    assert "禁止把 prefer 说成筛掉了人" in AGENT_SYSTEM_PROMPT


def test_validation_error_payload_tells_model_how_to_fix():
    payload = tool_failure_payload("education: 取值非法 ['小学']。该字段是枚举，允许值：['大专', '本科', '硕士', '博士']")
    assert payload["ok"] is False
    assert payload["retry"] is True
    assert "博士" in payload["error"]
    assert "再次调用" in payload["note"]


def test_http_400_is_retryable_for_model():
    session = SessionContext(owner_user_id=1)
    good = {
        "schema_version": "1.0",
        "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}},
    }
    session.replace_profile(good)
    cands, payload = apply_match_api_response(
        session,
        {"schema_version": "1.0", "attributes": {"code": {"constraint": "must", "weight": 1, "keywords": ["x"]}}},
        400,
        {"detail": "未知或禁止字段: code"},
    )
    assert cands == []
    assert payload["ok"] is False
    assert payload["retry"] is True
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]


def test_slim_assistant_strips_donor_tables():
    raw = "已匹配 57 位。\n\n| 编号 | 身高 |\n|------|------|\n| A2602588 | 184 |\n\n请问还有其他要求吗？"
    slim = slim_assistant_for_llm(raw)
    assert "A2602588" not in slim
    assert "|" not in slim
    assert "57" in slim


def test_openai_schema_function_exists():
    schema = openai_tool_schema()
    assert schema["properties"]["attributes"]["additionalProperties"] is False
    assert "smoke_history" in schema["properties"]["attributes"]["properties"]
