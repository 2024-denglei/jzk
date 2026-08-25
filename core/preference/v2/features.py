from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .scoring import parse_profile


CONTEXT_FEATURE_NAMES = [
    "active_attr_count",
    "must_count",
    "prefer_count",
    "range_ratio",
    "enum_ratio",
    "keyword_ratio",
    "single_range_ratio",
    "multi_value_ratio",
    "log1p_eligible_after_must",
    "log1p_selected_candidates",
]


def _safe_stat(values: list[float], fn: str) -> float:
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=np.float64)
    if fn == "sum":
        return float(arr.sum())
    if fn == "mean":
        return float(arr.mean())
    if fn == "std":
        return float(arr.std(ddof=0))
    if fn == "min":
        return float(arr.min())
    if fn == "max":
        return float(arr.max())
    raise ValueError(fn)


def profile_context_features(
    profile: str | Mapping[str, Any],
    eligible_after_must: int | float = 0,
    selected_candidates: int | float = 0,
) -> dict[str, float]:
    obj = parse_profile(profile)
    attributes = obj["attributes"]
    weights: list[float] = []
    must_weights: list[float] = []
    prefer_weights: list[float] = []
    type_counts = {"range": 0, "enum": 0, "keyword": 0}
    single_range_count = 0
    multi_value_count = 0

    for spec in attributes.values():
        weight = float(spec["weight"])
        weights.append(weight)
        constraint = str(spec.get("constraint", "prefer"))
        if constraint == "must":
            must_weights.append(weight)
        else:
            prefer_weights.append(weight)
        feature_type = str(spec.get("type"))
        type_counts[feature_type] = type_counts.get(feature_type, 0) + 1
        if feature_type == "range":
            rr = spec.get("range", {})
            single_range_count += int(rr.get("min") is None or rr.get("max") is None)
        else:
            values = spec.get("values", spec.get("keywords", []))
            if isinstance(values, (list, tuple, set)):
                multi_value_count += int(len(values) > 1)

    n = max(len(weights), 1)
    result = {
        "active_attr_count": float(len(weights)),
        "must_count": float(len(must_weights)),
        "prefer_count": float(len(prefer_weights)),
        "weight_sum": _safe_stat(weights, "sum"),
        "weight_mean": _safe_stat(weights, "mean"),
        "weight_std": _safe_stat(weights, "std"),
        "weight_min": _safe_stat(weights, "min"),
        "weight_max": _safe_stat(weights, "max"),
        "must_weight_sum": _safe_stat(must_weights, "sum"),
        "must_weight_mean": _safe_stat(must_weights, "mean"),
        "prefer_weight_sum": _safe_stat(prefer_weights, "sum"),
        "prefer_weight_mean": _safe_stat(prefer_weights, "mean"),
        "range_ratio": type_counts.get("range", 0) / n,
        "enum_ratio": type_counts.get("enum", 0) / n,
        "keyword_ratio": type_counts.get("keyword", 0) / n,
        "single_range_ratio": single_range_count / n,
        "multi_value_ratio": multi_value_count / n,
        "log1p_eligible_after_must": float(np.log1p(max(float(eligible_after_must), 0.0))),
        "log1p_selected_candidates": float(np.log1p(max(float(selected_candidates), 0.0))),
    }
    # 模型上下文有意不包含 weight_sum/mean/std 等权重统计。
    # 因此仅改变权重时，query 上下文固定，权重影响只经由规则加权分与
    # max_weighted_mismatch 进入模型，避免上下文网络产生反直觉旁路。
    return {name: float(result[name]) for name in CONTEXT_FEATURE_NAMES}


def build_profile_context_table(profiles: pd.DataFrame) -> pd.DataFrame:
    required = {
        "query_id",
        "profile_json",
        "eligible_after_must",
        "selected_candidates",
    }
    missing = sorted(required - set(profiles.columns))
    if missing:
        raise ValueError(f"Profile 表缺少字段：{missing}")
    rows = []
    for row in profiles.itertuples(index=False):
        values = profile_context_features(
            row.profile_json,
            eligible_after_must=row.eligible_after_must,
            selected_candidates=row.selected_candidates,
        )
        values["query_id"] = str(row.query_id)
        rows.append(values)
    return pd.DataFrame(rows, columns=["query_id", *CONTEXT_FEATURE_NAMES])


@dataclass
class ContextScaler:
    feature_names: list[str]
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        feature_names: list[str] | None = None,
    ) -> "ContextScaler":
        names = feature_names or list(CONTEXT_FEATURE_NAMES)
        values = frame[names].to_numpy(dtype=np.float64)
        mean = values.mean(axis=0)
        scale = values.std(axis=0, ddof=0)
        scale[scale < 1e-8] = 1.0
        return cls(feature_names=names, mean=mean, scale=scale)

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        values = frame[self.feature_names].to_numpy(dtype=np.float64)
        transformed = (values - self.mean) / self.scale
        return transformed.astype(np.float32)

    def transform_mapping(self, values: Mapping[str, float]) -> np.ndarray:
        row = np.asarray([float(values[x]) for x in self.feature_names], dtype=np.float64)
        return ((row - self.mean) / self.scale).astype(np.float32)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": list(self.feature_names),
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ContextScaler":
        return cls(
            feature_names=list(raw["feature_names"]),
            mean=np.asarray(raw["mean"], dtype=np.float64),
            scale=np.asarray(raw["scale"], dtype=np.float64),
        )
