from core.preference.validate import parse_profile

from dialogue.agent_tools import describe_empty_tool_arguments_error, parse_tool_arguments


def test_parses_standard_json_arguments():
    raw = '{"schema_version":"1.0","attributes":{"abo_blood":{"constraint":"must","weight":1,"values":["O"]}}}'
    args = parse_tool_arguments(raw, None)
    assert args["schema_version"] == "1.0"
    assert args["attributes"]["abo_blood"]["values"] == ["O"]


def test_empty_arguments_recovers_json_from_content():
    content = (
        "好的，我来提交。\n"
        '{"schema_version":"1.0","attributes":{"height_cm":{"constraint":"prefer","weight":0.9,"range":{"min":175}}}}'
    )
    args = parse_tool_arguments("", content)
    assert args["attributes"]["height_cm"]["range"]["min"] == 175


def test_empty_arguments_without_json_returns_empty_dict():
    assert parse_tool_arguments("", "好的，我来整理您的要求并提交偏好画像。") == {}
    assert parse_tool_arguments(None, None) == {}


def test_unwraps_arguments_wrapper_from_model():
    raw = (
        '{"arguments": {"schema_version": "1.0", "attributes": {'
        '"education": {"constraint": "must", "weight": 1.0, "values": ["硕士"]}, '
        '"height_cm": {"constraint": "must", "weight": 1.0, "range": {"min": 175, "max": null}'
        "}}}}"
    )
    args = parse_tool_arguments(raw, None)
    profile = parse_profile(args)
    assert args["schema_version"] == "1.0"
    assert profile.attributes["education"].values == ["硕士"]
    assert profile.attributes["height_cm"].range.min == 175


def test_describe_empty_tool_arguments_error_for_wrapper():
    raw = '{"arguments": {"schema_version": "1.0", "attributes": {}}}'
    message = describe_empty_tool_arguments_error(raw)
    assert "不要多包一层 arguments" in message
