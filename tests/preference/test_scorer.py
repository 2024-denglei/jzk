from datetime import date, timedelta

from jzk.domain.preference.scorer import score_field
from jzk.domain.preference.validate import parse_profile


def _attr(field, payload):
    p = parse_profile({"schema_version": "1.0", "attributes": {field: payload}})
    return p.attributes[field]


def test_height_min_only_order():
    attr = _attr("height_cm", {"constraint": "must", "weight": 1, "range": {"min": 175}})
    s185 = score_field("height_cm", attr, {"height_cm": 185})
    s180 = score_field("height_cm", attr, {"height_cm": 180})
    s175 = score_field("height_cm", attr, {"height_cm": 175})
    s170 = score_field("height_cm", attr, {"height_cm": 170})
    assert s185 > s180 > s175 > s170
    assert abs(s175 - 0.8) < 1e-6
    assert abs(s185 - 1.0) < 1e-6


def test_education_symmetric_distance():
    attr = _attr("education", {"constraint": "prefer", "weight": 1, "values": ["硕士"]})
    s_m = score_field("education", attr, {"education": "硕士"})
    s_d = score_field("education", attr, {"education": "博士"})
    s_b = score_field("education", attr, {"education": "本科"})
    s_c = score_field("education", attr, {"education": "大专"})
    assert s_m > s_d
    assert abs(s_d - s_b) < 1e-6
    assert s_b > s_c


def test_abo_hit_or_miss():
    attr = _attr("abo_blood", {"constraint": "must", "weight": 1, "values": ["O"]})
    assert score_field("abo_blood", attr, {"abo_blood": "O"}) == 1.0
    assert score_field("abo_blood", attr, {"abo_blood": "A"}) == 0.0


def test_keyword_any():
    attr = _attr(
        "smoke_history",
        {"constraint": "must", "weight": 1, "keywords": ["无", "不吸"], "match": "any"},
    )
    assert score_field("smoke_history", attr, {"smoke_history": "无吸烟史"}) == 1.0
    assert score_field("smoke_history", attr, {"smoke_history": "偶尔吸烟"}) == 0.0


def test_rh_normalize_plus():
    attr = _attr("rh_blood", {"constraint": "must", "weight": 1, "values": ["阳性"]})
    assert score_field("rh_blood", attr, {"rh_blood": "+"}) == 1.0


def test_age_from_birth_date():
    attr = _attr("age", {"constraint": "prefer", "weight": 1, "range": {"min": 20, "max": 30}})
    born = date.today() - timedelta(days=365 * 25 + 10)
    s = score_field("age", attr, {"birth_date": born.isoformat()})
    assert s == 1.0


def test_null_prefer_is_zero():
    attr = _attr("hometown", {"constraint": "prefer", "weight": 0.5, "keywords": ["四川"]})
    assert score_field("hometown", attr, {"hometown": None}) == 0.0


def test_weighted_average_and_tie_break_specimen():
    from jzk.domain.preference.scorer import HeuristicRanker

    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "height_cm": {"constraint": "prefer", "weight": 0.9, "range": {"min": 175}},
        },
    })
    ranker = HeuristicRanker()
    a = {"abo_blood": "O", "height_cm": 185, "specimen_count": 1, "code": "A"}
    b = {"abo_blood": "O", "height_cm": 175, "specimen_count": 9, "code": "B"}
    sa, _ = ranker.score(profile, a)
    sb, _ = ranker.score(profile, b)
    assert sa > sb
    ranked = ranker.rank(profile, [b, a])
    assert ranked[0][0]["code"] == "A"


def test_same_score_higher_specimen_first():
    from jzk.domain.preference.scorer import HeuristicRanker

    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
        },
    })
    ranker = HeuristicRanker()
    low = {"abo_blood": "O", "specimen_count": 1, "code": "L"}
    high = {"abo_blood": "O", "specimen_count": 8, "code": "H"}
    ranked = ranker.rank(profile, [low, high])
    assert ranked[0][0]["code"] == "H"
