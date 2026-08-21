import pytest

from core.preference.validate import ProfileValidationError, parse_profile


def test_valid_example_profile_parses():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "height_cm": {
                "constraint": "prefer",
                "weight": 0.9,
                "range": {"min": 175, "max": None},
            },
            "education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]},
            "smoke_history": {
                "constraint": "must",
                "weight": 1.0,
                "keywords": ["无", "不吸"],
                "match": "any",
            },
        },
    }
    p = parse_profile(raw)
    assert p.schema_version == "1.0"
    assert p.attributes["abo_blood"].constraint == "must"
    assert p.attributes["height_cm"].range.min == 175
    assert p.attributes["smoke_history"].keywords == ["无", "不吸"]


def test_rejects_unknown_field():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "code": {"constraint": "must", "weight": 1.0, "keywords": ["D1"], "match": "any"},
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_illegal_enum():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "education": {"constraint": "prefer", "weight": 0.5, "values": ["小学"]},
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_empty_range():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {
                "constraint": "must",
                "weight": 1.0,
                "range": {"min": None, "max": None},
            },
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_all_zero_weights():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 0, "values": ["O"]},
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_range_payload_on_enum_field():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "education": {
                "constraint": "prefer",
                "weight": 0.5,
                "range": {"min": 1, "max": 2},
            },
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_empty_attributes_ok():
    p = parse_profile({"schema_version": "1.0", "attributes": {}})
    assert p.attributes == {}
