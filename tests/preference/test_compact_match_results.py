from jzk.domain.preference import pipeline
from jzk.domain.preference.scorer import HeuristicRanker
from jzk.domain.preference.validate import parse_profile


def test_only_current_page_is_hydrated_while_all_refs_are_ranked(monkeypatch):
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
        },
    })
    rows = [
        {"id": i, "code": f"D{i}", "height_cm": 175 + i % 10,
         "specimen_count": 10, "status": "active"}
        for i in range(1, 4304)
    ]
    original = pipeline._candidate_dict
    hydrated = []

    def tracking_candidate(*args, **kwargs):
        hydrated.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_candidate_dict", tracking_candidate)
    result = pipeline.match_profile(
        profile,
        fetch_rows=lambda _profile: rows,
        ranker=HeuristicRanker(),
        detail_limit=20,
    )

    assert result.filtered_count == 4303
    assert len(result.ranked_refs) == 4303
    assert len(result.candidates) == 20
    assert hydrated == list(range(1, 21))
    assert result.timings["detail_hydrated_count"] == 20.0


def test_hydration_restores_snapshot_order_instead_of_sql_order():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
        },
    })
    refs = [
        pipeline.RankedCandidateRef(2, 21, 0.81),
        pipeline.RankedCandidateRef(1, 22, 0.80),
    ]
    rows = [
        {"id": 1, "code": "A", "height_cm": 180, "status": "active"},
        {"id": 2, "code": "B", "height_cm": 176, "status": "active"},
    ]
    items = pipeline.hydrate_ranked_candidates(
        profile, refs, rows, ranker=HeuristicRanker()
    )
    assert [(item["donor_info"]["code"], item["rank"], item["score"]) for item in items] == [
        ("B", 21, 0.81), ("A", 22, 0.8)
    ]

