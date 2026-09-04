import pytest

import config
from core.preference.schema import (
    CORE_FIELDS,
    EXTENDED_FIELDS,
    FIELD_REGISTRY,
    field_catalog_text,
    openai_tool_schema,
)
from core.preference.validate import ProfileValidationError, parse_profile
from dialogue.agent_tools import (
    AGENT_SYSTEM_PROMPT,
    AGENT_TOOLS,
    SUBMIT_PROFILE_EXTENDED_TOOL,
    SUBMIT_PROFILE_TOOL,
    apply_match_api_response,
    build_agent_system_prompt,
    build_preference_snapshot_message,
    run_preference_match,
    slim_assistant_for_llm,
    tool_failure_payload,
)
from dialogue.session import SessionContext


def test_tool_name_and_schema():
    assert SUBMIT_PROFILE_TOOL["function"]["name"] == "submit_preference_profile"
    assert SUBMIT_PROFILE_EXTENDED_TOOL["function"]["name"] == (
        "submit_preference_profile_extended"
    )
    assert AGENT_TOOLS == [SUBMIT_PROFILE_TOOL, SUBMIT_PROFILE_EXTENDED_TOOL]
    params = SUBMIT_PROFILE_TOOL["function"]["parameters"]
    assert "schema_version" in params["properties"]
    attrs = params["properties"]["attributes"]["properties"]
    assert set(attrs) == set(CORE_FIELDS)
    assert "硕士" in str(attrs["education"])
    assert attrs["education"]["properties"]["values"]["items"]["enum"] == [
        "大专", "本科", "硕士", "博士",
    ]
    assert "smoke_history" not in attrs
    extended_attrs = SUBMIT_PROFILE_EXTENDED_TOOL["function"]["parameters"][
        "properties"
    ]["attributes"]["properties"]
    assert "smoke_history" in extended_attrs
    assert "不抽烟" in extended_attrs["smoke_history"]["description"]
    assert field_catalog_text() not in params["properties"]["attributes"]["description"]


def test_field_catalog_is_generated_from_registry():
    text = field_catalog_text()
    assert "education" in text
    assert "硕士" in text
    assert "smoke_history" in text
    assert "height_cm" in text
    assert text not in AGENT_SYSTEM_PROMPT
    assert "【可填字段 catalog】" not in AGENT_SYSTEM_PROMPT


def test_enum_catalog_matches_donor_db_values():
    """枚举 catalog / 工具 schema 只能暴露库内实际取值，避免硬过滤被幽灵枚举打成 0。"""
    from core.preference.schema import (
        EYELID_ENUM,
        FACE_ENUM,
        FIGURE_ENUM,
        LIP_ENUM,
        openai_tool_schema,
    )

    assert FIGURE_ENUM == ("一般", "瘦弱", "强壮", "肥胖")
    assert FACE_ENUM == ("长方", "长", "椭圆", "瓜子")
    assert EYELID_ENUM == ("单", "双")
    assert LIP_ENUM == ("一般", "厚", "薄")

    attrs = openai_tool_schema(CORE_FIELDS)["properties"]["attributes"]["properties"]
    assert attrs["figure"]["properties"]["values"]["items"]["enum"] == list(FIGURE_ENUM)
    assert attrs["face_shape"]["properties"]["values"]["items"]["enum"] == list(FACE_ENUM)
    assert attrs["eyelid"]["properties"]["values"]["items"]["enum"] == list(EYELID_ENUM)
    assert attrs["lip_shape"]["properties"]["values"]["items"]["enum"] == list(LIP_ENUM)
    assert "可选值" not in attrs["figure"].get("description", "")
    assert "description" not in attrs["figure"]["properties"]["values"]

    text = field_catalog_text()
    assert "可选值：一般、瘦弱、强壮、肥胖" in text
    assert "可选值：长方、长、椭圆、瓜子" in text
    assert "可选值：单、双" in text
    assert "可选值：一般、厚、薄" in text
    assert "禁止自造近义词" in AGENT_SYSTEM_PROMPT
    assert "瘦/偏瘦/瘦点/苗条→瘦弱" in attrs["figure"]["description"]


def test_core_and_extended_field_partition():
    assert len(CORE_FIELDS) == 18
    assert set(CORE_FIELDS).isdisjoint(EXTENDED_FIELDS)
    assert set(CORE_FIELDS) | set(EXTENDED_FIELDS) == set(FIELD_REGISTRY)
    assert "smoke_history" in EXTENDED_FIELDS
    assert "abo_blood" in CORE_FIELDS


def test_invalid_profile_keeps_previous():
    session = SessionContext(owner_user_id=1)
    good = {"schema_version": "1.0", "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}}}
    session.replace_profile(good)
    candidates, payload = run_preference_match(
        session,
        {"schema_version": "1.0", "attributes": {"code": {"constraint": "must", "weight": 1, "keywords": ["x"]}}},
        fetch_rows=lambda _profile: [],
        log=False,
    )
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert payload["ok"] is False
    assert payload["retry"] is True
    assert "code" in payload["error"]
    assert candidates == []


def test_valid_profile_replaces_and_matches():
    from core.preference.scorer import HeuristicRanker

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
        fetch_rows=lambda _profile: rows,
        ranker=HeuristicRanker(),
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
    assert "top_preview" not in AGENT_SYSTEM_PROMPT
    assert "ranked_count" in AGENT_SYSTEM_PROMPT
    assert "filtered_count" in AGENT_SYSTEM_PROMPT
    assert "submit_preference_profile_extended" in AGENT_SYSTEM_PROMPT


def test_prompt_uses_configured_candidate_pool():
    assert str(config.MATCH_SCORER_CANDIDATE_POOL) in AGENT_SYSTEM_PROMPT
    assert "最多 5000" in build_agent_system_prompt(5000)


def test_validation_error_payload_tells_model_how_to_fix():
    payload = tool_failure_payload("education: 取值非法 ['小学']。该字段是枚举，允许值：['大专', '本科', '硕士', '博士']")
    assert payload["ok"] is False
    assert payload["retry"] is True
    assert "博士" in payload["error"]
    assert "再次调用" in payload["note"]


def test_validation_error_payload_includes_allowed_values():
    with pytest.raises(ProfileValidationError) as ei:
        parse_profile(
            {
                "schema_version": "1.0",
                "attributes": {
                    "figure": {
                        "constraint": "must",
                        "weight": 1,
                        "values": ["偏瘦型"],
                    }
                },
            }
        )
    err = ei.value
    assert err.field == "figure"
    assert err.allowed_values == ["一般", "瘦弱", "强壮", "肥胖"]
    payload = tool_failure_payload(err)
    assert payload["field"] == "figure"
    assert payload["allowed_values"] == ["一般", "瘦弱", "强壮", "肥胖"]


def test_preference_snapshot_message_helper():
    empty = build_preference_snapshot_message(None)
    assert empty["role"] == "system"
    assert empty["content"].startswith("【当前完整偏好画像】")
    assert '"attributes":{}' in empty["content"].replace(" ", "")


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
    assert field_catalog_text() not in schema["properties"]["attributes"]["description"]
