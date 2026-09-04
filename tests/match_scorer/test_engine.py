from jzk.scorer.api_models import RankRequest


def _request(candidates, *, request_id="rank-test") -> RankRequest:
    return RankRequest.model_validate({
        "contract_version": "1",
        "request_id": request_id,
        "profile": {
            "schema_version": "1.0",
            "attributes": {
                "abo_blood": {
                    "type": "enum", "constraint": "must", "weight": 1.0,
                    "values": ["O"],
                },
                "height_cm": {
                    "type": "range", "constraint": "prefer", "weight": 0.8,
                    "range": {"min": 175, "max": None},
                },
            },
        },
        "candidates": candidates,
    })


def test_real_model_ranks_and_returns_both_scores(scoring_engine):
    response = scoring_engine.rank(_request([
        {"donor_id": 1, "code": "SHORT", "attributes": {"abo_blood": "O", "height_cm": 175}},
        {"donor_id": 2, "code": "TALL", "attributes": {"abo_blood": "O", "height_cm": 195}},
    ]))
    assert response.eligible_count == 2
    assert response.ranked_count == 2
    assert [item.rank for item in response.items] == [1, 2]
    assert {item.donor_id for item in response.items} == {1, 2}
    assert all(0 <= item.match_score <= 1 for item in response.items)
    assert all(0 <= item.ranking_score <= 1 for item in response.items)
    assert all(len(item.field_scores) == 2 for item in response.items)


def test_must_filter_drift_is_rejected(scoring_engine):
    request = _request([
        {"donor_id": 1, "code": "BAD", "attributes": {"abo_blood": "A", "height_cm": 180}},
    ])
    try:
        scoring_engine.rank(request)
    except ValueError as exc:
        assert getattr(exc, "code", None) == "MUST_FILTER_DRIFT"
    else:
        raise AssertionError("must drift was accepted")


def test_candidate_pool_is_capped(scoring_engine, scorer_settings):
    candidates = [
        {
            "donor_id": index,
            "code": f"D{index:04d}",
            "attributes": {"abo_blood": "O", "height_cm": 175 + index % 10},
        }
        for index in range(1, 302)
    ]
    response = scoring_engine.rank(_request(candidates, request_id="pool-test"))
    assert response.eligible_count == 301
    assert response.ranked_count == scorer_settings.candidate_pool
