from core.preference.v2_ranker import V2CalibratedRanker, get_default_ranker
from core.preference.validate import parse_profile


def test_checkpoint_ranks_taller_higher():
    ranker = get_default_ranker()
    assert isinstance(ranker, V2CalibratedRanker)
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "education": {"constraint": "prefer", "weight": 0.7, "values": ["硕士", "博士"]},
            "height_cm": {"constraint": "prefer", "weight": 0.8, "range": {"min": 175, "max": None}},
        },
    })
    rows = [
        {"code": "SHORT", "abo_blood": "O", "education": "硕士", "height_cm": 175, "specimen_count": 1},
        {"code": "TALL", "abo_blood": "O", "education": "硕士", "height_cm": 195, "specimen_count": 1},
    ]
    out = ranker.rank(profile, rows)
    assert out[0][0]["code"] == "TALL"
    assert out[0][1] >= out[1][1]
