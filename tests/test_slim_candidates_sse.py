from api.chat_stream import _slim_candidates_for_sse


def test_slim_candidates_for_sse_keeps_all_rows_but_drops_heavy_fields():
    items = [
        {
            "donor_info": {
                "id": "A1",
                "code": "A1",
                "education": "硕士",
                "height": 180,
                "blood_type": "A",
                "age": 28,
                "ethnicity": "汉族",
                "hometown": "四川",
                "figure": "一般",
                "personality": "开朗",
                "occupation": "工程师",
                "specimen_count": 3,
                "availability": "可用",
                "genetic_history": "机密",
                "weight": 70,
            },
            "score": 0.9,
            "match_pct": 90.0,
            "reason": "很长的解释" * 20,
            "match_level": "high",
            "field_match": {
                "education": {"match": True, "actual": "硕士"},
                "height_cm": {"match": True, "actual": 180},
            },
            "field_scores": [{"field": "education", "s": 1.0, "constraint": "prefer"}],
            "rank": 1,
        },
        {
            "donor_info": {"id": "A2", "code": "A2", "education": "本科", "height": 175},
            "score": 0.8,
            "match_pct": 80.0,
            "reason": "x",
            "match_level": "medium",
            "field_match": {"education": {"match": False}},
            "field_scores": [{"field": "education", "s": 0.2}],
            "rank": 2,
        },
    ]
    prefer_hits = [{"field": "education", "label": "学历", "hits": 1, "of": 2}]

    slimmed = _slim_candidates_for_sse(items, prefer_hits)

    assert len(slimmed) == 2
    assert slimmed[0]["donor_info"]["code"] == "A1"
    assert "genetic_history" not in slimmed[0]["donor_info"]
    assert "weight" not in slimmed[0]["donor_info"]
    assert "field_scores" not in slimmed[0]
    assert slimmed[0]["reason"] == ""
    assert slimmed[0]["field_match"] == {
        "education": {"match": True, "actual": "硕士"},
    }
    assert "height_cm" not in slimmed[0]["field_match"]
    assert slimmed[1]["rank"] == 2
