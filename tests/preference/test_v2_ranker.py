import numpy as np

from core.preference.v2_ranker import V2CalibratedRanker
from core.preference.validate import parse_profile


class _Scaler:
    def transform_mapping(self, mapping):
        return np.zeros(10, dtype=np.float32)


def test_rank_all_rows_no_pool_cap(monkeypatch):
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "height_cm": {"constraint": "prefer", "weight": 1.0, "range": {"min": 175}},
        },
    })
    rows = [
        {"code": f"C{i}", "abo_blood": "O", "height_cm": 175 + i, "specimen_count": 1, "birth_date": None}
        for i in range(5)
    ]
    calls = {"n": 0}

    def fake_predict(model, heuristic, mismatch, context, device, batch_size):
        calls["n"] += 1
        return {"prediction": np.asarray(heuristic) * 0.99}

    monkeypatch.setattr("core.preference.v2_ranker.predict_arrays", fake_predict)
    ranker = V2CalibratedRanker.__new__(V2CalibratedRanker)
    ranker.model = object()
    ranker.scaler = _Scaler()
    ranker.config = type("C", (), {
        "rules": None,
        "evaluation": type("E", (), {"prediction_batch_size": 16})(),
    })()
    ranker.device = "cpu"
    out = V2CalibratedRanker.rank(ranker, profile, rows)
    assert len(out) == 5
    assert calls["n"] == 1
    assert out[0][0]["code"] == "C4"
