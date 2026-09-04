import json
from decimal import Decimal

from core.preference.pipeline import match_profile
from core.preference.scorer import FieldScore, HeuristicRanker
from core.preference.validate import parse_profile


def test_match_profile_requires_injected_fetch():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
        },
    })
    try:
        match_profile(profile)
        assert False, "expected TypeError"
    except TypeError as exc:
        assert "fetch_rows" in str(exc)


def test_empty_attributes_does_not_query():
    called = []
    profile = parse_profile({"schema_version": "1.0", "attributes": {}})
    result = match_profile(profile, fetch_rows=lambda profile: called.append(profile) or [])
    assert result.candidates == []
    assert result.skipped is True
    assert result.prefer_hits == []
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
        fetch_rows=lambda _profile: [],
        count_rows=lambda _profile: 0,
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
    result = match_profile(
        profile, fetch_rows=lambda _profile: rows, ranker=HeuristicRanker(), log=False
    )
    assert result.candidates[0]["donor_info"]["code"] == "T"
    assert result.candidates[0]["score"] > result.candidates[1]["score"]
    assert "field_scores" in result.candidates[0]
    assert result.prefer_hits == [
        {"field": "height_cm", "label": "身高", "hits": 2, "of": 2},
    ]


def test_prefer_hits_counts_without_filtering():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            "hometown": {
                "constraint": "prefer",
                "weight": 0.5,
                "keywords": ["重庆"],
                "match": "any",
            },
        },
    })
    rows = [
        {"code": "A", "abo_blood": "O", "hometown": "重庆市渝北区", "specimen_count": 1, "status": "active"},
        {"code": "B", "abo_blood": "O", "hometown": "成都市", "specimen_count": 1, "status": "active"},
        {"code": "C", "abo_blood": "O", "hometown": "重庆南岸", "specimen_count": 1, "status": "active"},
    ]
    result = match_profile(
        profile, fetch_rows=lambda _profile: rows, ranker=HeuristicRanker(), log=False
    )
    assert result.filtered_count == 3
    assert result.prefer_hits == [
        {"field": "hometown", "label": "籍贯", "hits": 2, "of": 3},
    ]
    assert result.candidates[0]["donor_info"]["code"] in ("A", "C")


class _DecimalWeightRanker:
    def rank(self, profile, rows):
        return [
            (
                rows[0],
                0.9,
                [
                    FieldScore(
                        "weight_kg",
                        Decimal("68.50"),
                        {"min": None, "max": 70.0},
                        1.0,
                        0.5,
                        "prefer",
                    )
                ],
            )
        ]


def test_decimal_weight_is_json_serializable(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCH_LOG_DIR", str(tmp_path))
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "weight_kg": {"constraint": "prefer", "weight": 0.5, "range": {"max": 70}},
        },
    })
    rows = [{"code": "W", "weight_kg": Decimal("68.50"), "status": "active"}]
    result = match_profile(
        profile,
        fetch_rows=lambda _profile: rows,
        ranker=_DecimalWeightRanker(),
        log=True,
    )
    payload = json.dumps(result.candidates, ensure_ascii=False)
    assert "68.5" in payload
    actual = result.candidates[0]["field_scores"][0]["actual"]
    assert isinstance(actual, float)
    assert not isinstance(actual, Decimal)
    turns = (tmp_path / "turns.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(turns)["candidates"][0]["attrs"]["weight_kg"] == 68.5
