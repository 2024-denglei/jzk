from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


TYPE_TO_ID_DEFAULT = {"pad": 0, "range": 1, "enum": 2, "keyword": 3, "boolean": 4}
CONSTRAINT_TO_ID_DEFAULT = {"pad": 0, "prefer": 1, "must": 2}
BOOLEAN_TOKENS = {"有", "无", "是", "否", "阳性", "阴性"}
ORDERED_VALUES = {
    "education": ["高中", "中专", "大专", "本科", "硕士", "博士"],
    "skin_color": ["偏白", "一般", "偏黑"],
    "hair_volume": ["稀疏", "一般", "浓密"],
    "nose_bridge": ["低塌", "中直", "高直"],
    "lip_shape": ["薄", "一般", "厚"],
}
NUMERIC_DECAY = {
    "age": 5.0,
    "height_cm": 8.0,
    "weight_kg": 10.0,
    "bmi": 4.0,
    "partners_6m": 3.0,
    "marriage_age": 5.0,
    "specimen_count": 3.0,
}


class ScoringError(ValueError):
    """The request cannot be scored with the loaded model contract."""


@dataclass(frozen=True)
class FeatureMatch:
    name: str
    feature_type: str
    constraint: str
    weight: float
    similarity: float
    weighted_mismatch: float
    donor_value: Any
    requirement: Any
    must_pass: bool


@dataclass(frozen=True)
class EncodedCandidate:
    donor: dict[str, Any]
    heuristic_score: float
    max_weighted_mismatch: float
    feature_matches: tuple[FeatureMatch, ...]
    arrays: dict[str, np.ndarray]


def is_missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, float) and np.isnan(value)
    ) or str(value).strip().lower() in {"", "nan", "none", "null"}


def stable_bucket(value: Any, buckets: int) -> int:
    if is_missing(value):
        return 0
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % buckets + 1


def target_value(spec: Mapping[str, Any]) -> Any:
    if spec.get("type") == "range":
        return dict(spec.get("range", {}))
    if spec.get("type") == "keyword":
        return list(spec.get("keywords", []))
    return list(spec.get("values", []))


def target_text(spec: Mapping[str, Any]) -> str:
    if spec.get("type") == "range":
        bounds = spec.get("range", {})
        return f"{bounds.get('min')}..{bounds.get('max')}"
    values = (
        spec.get("keywords", [])
        if spec.get("type") == "keyword"
        else spec.get("values", [])
    )
    return "|".join(map(str, values))


def effective_type(spec: Mapping[str, Any], actual: Any) -> str:
    declared = str(spec.get("type", "enum"))
    if declared != "enum":
        return declared if declared in TYPE_TO_ID_DEFAULT else "enum"
    values = {str(value) for value in spec.get("values", [])}
    if values and values.issubset(BOOLEAN_TOKENS) and str(actual) in BOOLEAN_TOKENS:
        return "boolean"
    return "enum"


def strict_must_pass(spec: Mapping[str, Any], actual: Any) -> bool:
    if is_missing(actual):
        return False
    feature_type = str(spec.get("type", "enum"))
    if feature_type == "range":
        try:
            value = float(actual)
        except (TypeError, ValueError):
            return False
        bounds = spec.get("range", {})
        lower, upper = bounds.get("min"), bounds.get("max")
        return (
            (lower is None or value >= float(lower))
            and (upper is None or value <= float(upper))
        )
    if feature_type == "keyword":
        text = str(actual)
        keywords = [str(value) for value in spec.get("keywords", [])]
        hits = [keyword in text for keyword in keywords]
        return all(hits) if spec.get("match", "any") == "all" else any(hits)
    return str(actual) in {str(value) for value in spec.get("values", [])}


def field_similarity(
    field: str,
    spec: Mapping[str, Any],
    actual: Any,
    numeric_stats: Mapping[str, tuple[float, float]],
) -> tuple[float, float, float, float, float, float, float]:
    if is_missing(actual):
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
    feature_type = str(spec.get("type", "enum"))
    if feature_type == "range":
        try:
            value = float(actual)
        except (TypeError, ValueError):
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
        bounds = spec.get("range", {})
        lower, upper = bounds.get("min"), bounds.get("max")
        below = max(float(lower) - value, 0.0) if lower is not None else 0.0
        above = max(value - float(upper), 0.0) if upper is not None else 0.0
        distance = below + above
        decay = NUMERIC_DECAY.get(
            field,
            max(numeric_stats.get(field, (0.0, 1.0))[1], 1.0),
        )
        similarity = math.exp(-distance / decay)
        mean, std = numeric_stats.get(field, (0.0, 1.0))
        donor_z = (value - mean) / std
        lower_z = 0.0 if lower is None else (float(lower) - mean) / std
        upper_z = 0.0 if upper is None else (float(upper) - mean) / std
        exact = float(distance == 0.0)
        return similarity, exact, exact, donor_z, lower_z, upper_z, 0.0
    if feature_type == "keyword":
        text = str(actual)
        keywords = [str(value) for value in spec.get("keywords", [])]
        if not keywords:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        hits = np.array(
            [keyword in text for keyword in keywords], dtype=np.float32
        )
        similarity = float(
            hits.min() if spec.get("match", "any") == "all" else hits.max()
        )
        return similarity, similarity, similarity, 0.0, 0.0, 0.0, 0.0
    actual_text = str(actual)
    targets = [str(value) for value in spec.get("values", [])]
    exact = float(actual_text in targets)
    ordinal = exact
    order = ORDERED_VALUES.get(field)
    if order and actual_text in order and targets:
        similarities = []
        for target in targets:
            if target in order:
                distance = abs(order.index(actual_text) - order.index(target))
                similarities.append(1.0 - distance / max(len(order) - 1, 1))
        if similarities:
            ordinal = max(similarities)
    return max(exact, ordinal), exact, ordinal, 0.0, 0.0, 0.0, 0.0


class CandidateEncoder:
    def __init__(
        self,
        field_to_id: Mapping[str, int],
        type_to_id: Mapping[str, int],
        constraint_to_id: Mapping[str, int],
        numeric_stats: Mapping[str, Any],
        max_attr: int,
        max_must: int,
        max_prefer: int,
        hash_buckets: int,
        numeric_token_dim: int,
    ):
        self.field_to_id = dict(field_to_id)
        self.type_to_id = dict(type_to_id)
        self.constraint_to_id = dict(constraint_to_id)
        self.numeric_stats = {
            str(key): (float(value[0]), max(float(value[1]), 1e-6))
            for key, value in numeric_stats.items()
        }
        self.max_attr = int(max_attr)
        self.max_must = max(int(max_must), 1)
        self.max_prefer = max(int(max_prefer), 1)
        self.hash_buckets = int(hash_buckets)
        self.numeric_token_dim = int(numeric_token_dim)

    def score_only(
        self,
        profile: Mapping[str, Any],
        donor: Mapping[str, Any],
    ) -> tuple[float, float]:
        attrs = profile.get("attributes", {})
        weighted_sum = 0.0
        weight_sum = 0.0
        max_mismatch = 0.0
        for field, spec in attrs.items():
            similarity = field_similarity(
                field, spec, donor.get(field), self.numeric_stats
            )[0]
            weight = float(np.clip(spec.get("weight", 0.0), 0.0, 1.0))
            weighted_sum += weight * similarity
            weight_sum += weight
            max_mismatch = max(max_mismatch, weight * (1.0 - similarity))
        if weight_sum <= 0:
            raise ScoringError("有效字段权重总和必须大于0。")
        return float(weighted_sum / weight_sum), float(max_mismatch)

    def encode(
        self,
        profile: Mapping[str, Any],
        donor: dict[str, Any],
    ) -> EncodedCandidate:
        attrs = profile.get("attributes", {})
        if len(attrs) > self.max_attr:
            raise ScoringError(
                f"输入包含{len(attrs)}个字段，超过模型训练上限{self.max_attr}。"
            )
        numeric = np.zeros((self.max_attr, self.numeric_token_dim), np.float32)
        arrays = {
            "numeric": numeric,
            "field_ids": np.zeros(self.max_attr, np.int64),
            "type_ids": np.zeros(self.max_attr, np.int64),
            "constraint_ids": np.zeros(self.max_attr, np.int64),
            "target_ids": np.zeros(self.max_attr, np.int64),
            "actual_ids": np.zeros(self.max_attr, np.int64),
            "mask": np.zeros(self.max_attr, np.bool_),
        }
        weighted_sum = 0.0
        weight_sum = 0.0
        max_mismatch = 0.0
        matches = []
        for position, (field, spec) in enumerate(attrs.items()):
            actual = donor.get(field)
            similarity, exact, ordinal, donor_z, lower_z, upper_z, missing = (
                field_similarity(field, spec, actual, self.numeric_stats)
            )
            weight = float(np.clip(spec.get("weight", 0.0), 0.0, 1.0))
            mismatch = weight * (1.0 - similarity)
            feature_type = effective_type(spec, actual)
            numeric[position] = np.array([
                similarity,
                weight,
                weight * similarity,
                mismatch,
                np.clip(donor_z, -5.0, 5.0),
                np.clip(lower_z, -5.0, 5.0),
                np.clip(upper_z, -5.0, 5.0),
                exact,
                ordinal,
                missing,
            ], dtype=np.float32)
            arrays["field_ids"][position] = self.field_to_id.get(field, 0)
            arrays["type_ids"][position] = self.type_to_id[feature_type]
            arrays["constraint_ids"][position] = self.constraint_to_id.get(
                str(spec.get("constraint", "prefer")), 1
            )
            arrays["target_ids"][position] = stable_bucket(
                target_text(spec), self.hash_buckets
            )
            arrays["actual_ids"][position] = stable_bucket(
                actual, self.hash_buckets
            )
            arrays["mask"][position] = True
            must_pass = (
                spec.get("constraint") != "must"
                or strict_must_pass(spec, actual)
            )
            matches.append(FeatureMatch(
                field,
                feature_type,
                str(spec.get("constraint", "prefer")),
                weight,
                float(similarity),
                float(mismatch),
                actual,
                target_value(spec),
                bool(must_pass),
            ))
            weighted_sum += weight * similarity
            weight_sum += weight
            max_mismatch = max(max_mismatch, mismatch)
        if weight_sum <= 0:
            raise ScoringError("有效字段权重总和必须大于0。")
        heuristic = weighted_sum / weight_sum
        active = len(attrs)
        must_count = sum(
            spec.get("constraint") == "must" for spec in attrs.values()
        )
        prefer_count = active - must_count
        arrays["global"] = np.array([
            heuristic,
            max_mismatch,
            heuristic,
            max_mismatch,
            active / max(self.max_attr, 1),
            must_count / self.max_must,
            prefer_count / self.max_prefer,
        ], dtype=np.float32)
        return EncodedCandidate(
            donor=donor,
            heuristic_score=float(heuristic),
            max_weighted_mismatch=float(max_mismatch),
            feature_matches=tuple(matches),
            arrays=arrays,
        )
