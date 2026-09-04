from jzk.scorer.encoding import (
    CONSTRAINT_TO_ID_DEFAULT,
    TYPE_TO_ID_DEFAULT,
    CandidateEncoder,
    field_similarity,
    stable_bucket,
    strict_must_pass,
)


def _encoder() -> CandidateEncoder:
    return CandidateEncoder(
        field_to_id={"abo_blood": 1, "height_cm": 2},
        type_to_id=TYPE_TO_ID_DEFAULT,
        constraint_to_id=CONSTRAINT_TO_ID_DEFAULT,
        numeric_stats={"height_cm": (178, 4)},
        max_attr=11,
        max_must=2,
        max_prefer=11,
        hash_buckets=4096,
        numeric_token_dim=10,
    )


def test_stable_bucket_is_repeatable_and_reserves_zero_for_missing():
    assert stable_bucket(None, 4096) == 0
    assert stable_bucket("重庆", 4096) == stable_bucket("重庆", 4096)
    assert 1 <= stable_bucket("重庆", 4096) <= 4096


def test_must_range_is_strict():
    spec = {
        "type": "range",
        "constraint": "must",
        "weight": 1.0,
        "range": {"min": 175, "max": None},
    }
    assert strict_must_pass(spec, 175)
    assert strict_must_pass(spec, 185)
    assert not strict_must_pass(spec, 174.9)


def test_training_aligned_one_sided_similarity():
    spec = {
        "type": "range",
        "constraint": "prefer",
        "weight": 0.8,
        "range": {"min": 175, "max": None},
    }
    inside = field_similarity("height_cm", spec, 180, {"height_cm": (178, 4)})[0]
    outside = field_similarity("height_cm", spec, 170, {"height_cm": (178, 4)})[0]
    assert inside == 1.0
    assert 0.0 < outside < 1.0


def test_encoded_shapes_and_context():
    profile = {"attributes": {
        "abo_blood": {
            "type": "enum", "constraint": "must", "weight": 1.0,
            "values": ["O"],
        },
        "height_cm": {
            "type": "range", "constraint": "prefer", "weight": 0.8,
            "range": {"min": 175, "max": None},
        },
    }}
    result = _encoder().encode(
        profile, {"code": "A1", "abo_blood": "O", "height_cm": 180}
    )
    assert result.arrays["numeric"].shape == (11, 10)
    assert result.arrays["global"].shape == (7,)
    assert result.heuristic_score == 1.0
