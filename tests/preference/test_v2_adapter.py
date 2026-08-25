from datetime import date

from core.preference.v2_adapter import donor_row_to_v2, profile_to_v2_spec
from core.preference.validate import parse_profile


def test_profile_to_v2_keeps_keyword_hometown():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "hometown": {
                "constraint": "must",
                "weight": 1.0,
                "keywords": ["重庆"],
                "match": "any",
            },
            "height_cm": {
                "constraint": "prefer",
                "weight": 0.8,
                "range": {"min": 175, "max": None},
            },
            "abo_blood": {
                "constraint": "must",
                "weight": 1.0,
                "values": ["O"],
            },
        },
    })
    spec = profile_to_v2_spec(profile)
    hometown = spec["attributes"]["hometown"]
    assert hometown["type"] == "keyword"
    assert hometown["keywords"] == ["重庆"]
    assert hometown["match_mode"] == "any"
    assert "values" not in hometown
    assert spec["attributes"]["height_cm"]["type"] == "range"
    assert spec["attributes"]["abo_blood"]["type"] == "enum"


def test_donor_row_age_from_birth_date():
    row = {
        "code": "A1",
        "abo_blood": "O",
        "rh_blood": "+",
        "height_cm": 180,
        "birth_date": date(2000, 1, 1),
        "sideburns": "无",
    }
    out = donor_row_to_v2(row)
    assert out["age"] >= 25
    assert out["rh_blood"] == "阳性"
    assert out["height_cm"] == 180
    assert out["code"] == "A1"
