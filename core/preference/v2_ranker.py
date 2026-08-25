from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from decimal import Decimal
from typing import Any

import numpy as np

from core.preference.scorer import FieldScore, Ranker
from core.preference.v2.features import profile_context_features
from core.preference.v2.load import load_v2_engine
from core.preference.v2.predict import predict_arrays
from core.preference.v2.scoring import score_profile_against_donor
from core.preference.v2_adapter import donor_row_to_v2, profile_to_v2_spec


class V2RankerUnavailable(Exception):
    pass


def _parts_from_matches(matches, specs: dict) -> list[FieldScore]:
    parts: list[FieldScore] = []
    for match in matches:
        spec = specs[match.name]
        if spec.get("type") == "range":
            target: Any = dict(spec.get("range") or {})
        elif spec.get("type") == "keyword":
            target = {"keywords": spec.get("keywords"), "match": spec.get("match_mode", "any")}
        else:
            target = list(spec.get("values") or [])
        actual = match.donor_value
        if isinstance(actual, Decimal):
            actual = float(actual)
        parts.append(
            FieldScore(
                match.name,
                actual,
                target,
                float(match.similarity),
                float(match.weight),
                match.constraint,
            )
        )
    return parts


class V2CalibratedRanker(Ranker):
    def __init__(self, model, scaler, config, device):
        self.model = model
        self.scaler = scaler
        self.config = config
        self.device = device
        self.last_timings: dict[str, float] = {}

    def score(self, profile, row: dict[str, Any]) -> tuple[float, list[FieldScore]]:
        ranked = self.rank(profile, [row])
        return ranked[0][1], ranked[0][2]

    def rank(self, profile, rows: list[dict[str, Any]]):
        t0 = time.perf_counter()
        v2_profile = profile_to_v2_spec(profile)
        specs = v2_profile["attributes"]
        heuristics = []
        mismatches = []
        parts_list = []
        for row in rows:
            donor = donor_row_to_v2(row)
            rule = score_profile_against_donor(v2_profile, donor, self.config.rules)
            heuristics.append(rule.heuristic_score)
            mismatches.append(rule.max_weighted_mismatch)
            parts_list.append(_parts_from_matches(rule.feature_matches, specs))
        rule_ms = (time.perf_counter() - t0) * 1000
        n = len(rows)
        t1 = time.perf_counter()
        ctx_map = profile_context_features(
            v2_profile, eligible_after_must=n, selected_candidates=n
        )
        ctx_row = self.scaler.transform_mapping(ctx_map)
        context = np.repeat(ctx_row.reshape(1, -1), n, axis=0)
        arrays = predict_arrays(
            self.model,
            np.asarray(heuristics, dtype=np.float32),
            np.asarray(mismatches, dtype=np.float32),
            context,
            self.device,
            self.config.evaluation.prediction_batch_size,
        )
        model_ms = (time.perf_counter() - t1) * 1000
        t2 = time.perf_counter()
        preds = [float(x) for x in arrays["prediction"].tolist()]
        indexed = list(zip(rows, preds, parts_list, heuristics))
        indexed.sort(
            key=lambda t: (t[1], t[3], float(t[0].get("specimen_count") or 0)),
            reverse=True,
        )
        sort_ms = (time.perf_counter() - t2) * 1000
        self.last_timings = {
            "rule_score_ms": round(rule_ms, 1),
            "model_ms": round(model_ms, 1),
            "sort_ms": round(sort_ms, 1),
            "rank_rows": float(n),
        }
        return [(row, score, parts) for row, score, parts, _h in indexed]


_LOCK = threading.Lock()
_RANKER: V2CalibratedRanker | None = None
_LOAD_ERROR: V2RankerUnavailable | None = None


def get_default_ranker() -> Ranker:
    global _RANKER, _LOAD_ERROR
    if _RANKER is not None:
        return _RANKER
    if _LOAD_ERROR is not None:
        raise _LOAD_ERROR
    with _LOCK:
        if _RANKER is not None:
            return _RANKER
        if _LOAD_ERROR is not None:
            raise _LOAD_ERROR
        try:
            import config as app_config

            ckpt = Path(getattr(app_config, "V2_CHECKPOINT_PATH", "") or os.getenv(
                "V2_CHECKPOINT_PATH",
                str(Path(__file__).resolve().parents[2] / "models" / "best_model_v2.pt"),
            ))
            cfg = Path(getattr(app_config, "V2_CONFIG_PATH", "") or os.getenv(
                "V2_CONFIG_PATH",
                str(Path(__file__).resolve().parents[2] / "core" / "preference" / "v2" / "config_v2.json"),
            ))
            force_cpu = getattr(app_config, "V2_FORCE_CPU", True)
            model, scaler, config, device = load_v2_engine(ckpt, cfg, force_cpu=force_cpu)
            _RANKER = V2CalibratedRanker(model, scaler, config, device)
            return _RANKER
        except Exception as exc:
            _LOAD_ERROR = V2RankerUnavailable(str(exc))
            raise _LOAD_ERROR from exc
