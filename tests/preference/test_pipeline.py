from core.preference.pipeline import match_profile
from core.preference.validate import parse_profile


def test_empty_attributes_does_not_query():
    called = []
    profile = parse_profile({"schema_version": "1.0", "attributes": {}})
    result = match_profile(profile, fetch_rows=lambda s, p: called.append((s, p)) or [])
    assert result.candidates == []
    assert result.skipped is True
    assert called == []


def test_zero_rows_returns_bottlenecks_not_relaxed():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
        },
    })
    result = match_profile(
        profile,
        fetch_rows=lambda s, p: [],
        count_rows=lambda s, p: 0,
        log=False,
    )
    assert result.candidates == []
    assert result.match_level == "none"
    assert result.bottlenecks


def test_ranks_by_score():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
        },
    })
    rows = [
        {"code": "S", "abo_blood": "O", "height_cm": 175, "specimen_count": 3, "status": "active"},
        {"code": "T", "abo_blood": "O", "height_cm": 185, "specimen_count": 3, "status": "active"},
    ]
    result = match_profile(profile, fetch_rows=lambda s, p: rows, log=False)
    assert result.candidates[0]["donor_info"]["code"] == "T"
    assert result.candidates[0]["score"] > result.candidates[1]["score"]
    assert "field_scores" in result.candidates[0]
