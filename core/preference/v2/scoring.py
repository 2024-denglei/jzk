from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np

from .settings import RuleConfig


class ScoringError(ValueError):
    """需求或捐精人字段无法按 V2 规则评分。"""


@dataclass(frozen=True)
class FeatureMatch:
    name: str
    feature_type: str
    constraint: str
    weight: float
    similarity: float
    weighted_match: float
    weighted_mismatch: float
    donor_value: Any
    requirement: Any
    must_pass: bool


@dataclass(frozen=True)
class PairRuleScore:
    heuristic_score: float
    max_weighted_mismatch: float
    weight_sum: float
    must_pass: bool
    feature_matches: tuple[FeatureMatch, ...]

    def to_dict(self, include_details: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "heuristic_score": self.heuristic_score,
            "max_weighted_mismatch": self.max_weighted_mismatch,
            "weight_sum": self.weight_sum,
            "must_pass": self.must_pass,
        }
        if include_details:
            result["feature_matches"] = [asdict(x) for x in self.feature_matches]
        return result


def parse_profile(profile: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(profile, str):
        try:
            value = json.loads(profile)
        except json.JSONDecodeError as exc:
            raise ScoringError(f"profile_json 不是有效 JSON：{exc}") from exc
    else:
        value = dict(profile)
    attributes = value.get("attributes")
    if not isinstance(attributes, dict) or not attributes:
        raise ScoringError("profile_json 必须包含非空对象 attributes。")
    return value


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == ""


def _as_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringError(f"字段 {field_name!r} 的值 {value!r} 不是数值。") from exc
    if not math.isfinite(number):
        raise ScoringError(f"字段 {field_name!r} 的值必须为有限数值。")
    return number


def _exp_decay(distance: float, scale: float) -> float:
    return float(math.exp(-max(distance, 0.0) / max(scale, 1e-8)))


def range_similarity(
    actual: Any,
    requirement: Mapping[str, Any],
    field_name: str,
    rules: RuleConfig,
) -> float:
    if _is_missing(actual):
        return 0.0
    x = _as_float(actual, field_name)
    lower_raw = requirement.get("min")
    upper_raw = requirement.get("max")
    lower = None if lower_raw is None else _as_float(lower_raw, field_name)
    upper = None if upper_raw is None else _as_float(upper_raw, field_name)
    if lower is None and upper is None:
        raise ScoringError(f"range 字段 {field_name!r} 的 min/max 不能同时为空。")
    if lower is not None and upper is not None and lower > upper:
        raise ScoringError(f"range 字段 {field_name!r} 的 min 不能大于 max。")

    scale = float(rules.range_scales.get(field_name, rules.default_range_scale))
    boundary = float(rules.single_range_boundary_score)

    if lower is not None and upper is not None:
        if lower <= x <= upper:
            return 1.0
        distance = lower - x if x < lower else x - upper
        return _exp_decay(distance, scale)

    # 单边范围：边界得分为 0.8，沿偏好方向渐近 1，反方向连续衰减。
    if lower is not None:
        distance = x - lower
    else:
        distance = upper - x  # type: ignore[operator]
    if distance >= 0:
        score = boundary + (1.0 - boundary) * (1.0 - _exp_decay(distance, scale))
    else:
        score = boundary * _exp_decay(-distance, scale)
    return float(np.clip(score, 0.0, 1.0))


def _ordinal_similarity(
    actual: Any,
    wanted: list[Any],
    order: list[str],
    step_penalty: float,
) -> float:
    if _is_missing(actual):
        return 0.0
    index = {str(value): i for i, value in enumerate(order)}
    actual_text = str(actual)
    if actual_text not in index:
        return 1.0 if actual_text in {str(x) for x in wanted} else 0.0
    scores = []
    for value in wanted:
        wanted_text = str(value)
        if wanted_text not in index:
            scores.append(1.0 if actual_text == wanted_text else 0.0)
        else:
            distance = abs(index[actual_text] - index[wanted_text])
            scores.append(max(0.0, 1.0 - step_penalty * distance))
    return float(max(scores, default=0.0))


def enum_similarity(
    actual: Any,
    values: list[Any],
    field_name: str,
    rules: RuleConfig,
) -> float:
    if not values or _is_missing(actual):
        return 0.0
    if field_name == "education":
        return _ordinal_similarity(
            actual, values, rules.education_order, rules.education_step_penalty
        )
    if field_name == "skin_color":
        return _ordinal_similarity(
            actual, values, rules.skin_color_order, rules.skin_color_step_penalty
        )
    return float(str(actual) in {str(x) for x in values})


def keyword_similarity(
    actual: Any,
    spec: Mapping[str, Any],
    rules: RuleConfig,
) -> float:
    if _is_missing(actual):
        return 0.0
    raw_keywords = spec.get("keywords", spec.get("values", spec.get("text", [])))
    if isinstance(raw_keywords, str):
        keywords = [raw_keywords]
    else:
        keywords = list(raw_keywords or [])
    keywords = [str(x).strip() for x in keywords if str(x).strip()]
    if not keywords:
        return 0.0
    text = str(actual)
    mode = str(spec.get("match_mode", rules.keyword_mode)).lower()
    matches = [keyword in text for keyword in keywords]
    if mode == "all":
        return float(all(matches))
    if mode != "any":
        raise ScoringError(f"未知 keyword match_mode：{mode!r}，仅支持 any/all。")
    return float(any(matches))


def match_attribute(
    field_name: str,
    spec: Mapping[str, Any],
    donor_value: Any,
    rules: RuleConfig,
) -> float:
    feature_type = str(spec.get("type", "")).lower()
    if feature_type == "range":
        requirement = spec.get("range")
        if not isinstance(requirement, Mapping):
            raise ScoringError(f"range 字段 {field_name!r} 缺少 range 对象。")
        return range_similarity(donor_value, requirement, field_name, rules)
    if feature_type == "enum":
        values = spec.get("values", [])
        if isinstance(values, (str, int, float)):
            values = [values]
        return enum_similarity(donor_value, list(values), field_name, rules)
    if feature_type == "keyword":
        return keyword_similarity(donor_value, spec, rules)
    raise ScoringError(f"字段 {field_name!r} 使用了未知 type：{feature_type!r}。")


def score_profile_against_donor(
    profile: str | Mapping[str, Any],
    donor: Mapping[str, Any],
    rules: RuleConfig | None = None,
) -> PairRuleScore:
    rules = rules or RuleConfig()
    profile_obj = parse_profile(profile)
    matches: list[FeatureMatch] = []
    weighted_sum = 0.0
    weight_sum = 0.0
    max_mismatch = 0.0
    all_must_pass = True

    for field_name, raw_spec in profile_obj["attributes"].items():
        if not isinstance(raw_spec, Mapping):
            raise ScoringError(f"字段 {field_name!r} 的规则必须是对象。")
        spec = dict(raw_spec)
        weight = _as_float(spec.get("weight"), field_name)
        if not 0.0 <= weight <= 1.0:
            raise ScoringError(f"字段 {field_name!r} 的 weight 必须位于 [0,1]。")
        constraint = str(spec.get("constraint", "prefer")).lower()
        if constraint not in {"must", "prefer"}:
            raise ScoringError(
                f"字段 {field_name!r} 的 constraint 必须为 must/prefer。"
            )
        similarity = float(
            np.clip(
                match_attribute(field_name, spec, donor.get(field_name), rules),
                0.0,
                1.0,
            )
        )
        weighted_match = weight * similarity
        weighted_mismatch = weight * (1.0 - similarity)
        must_pass = (
            constraint != "must"
            or similarity >= 1.0 - float(rules.must_match_tolerance)
        )
        all_must_pass = all_must_pass and must_pass
        weighted_sum += weighted_match
        weight_sum += weight
        max_mismatch = max(max_mismatch, weighted_mismatch)
        requirement = (
            spec.get("range") if spec.get("type") == "range" else spec.get("values", spec.get("keywords"))
        )
        matches.append(
            FeatureMatch(
                name=field_name,
                feature_type=str(spec.get("type")),
                constraint=constraint,
                weight=weight,
                similarity=similarity,
                weighted_match=weighted_match,
                weighted_mismatch=weighted_mismatch,
                donor_value=donor.get(field_name),
                requirement=requirement,
                must_pass=must_pass,
            )
        )

    if weight_sum <= 0.0:
        raise ScoringError("有效字段权重总和必须大于 0。")
    return PairRuleScore(
        heuristic_score=float(np.clip(weighted_sum / weight_sum, 0.0, 1.0)),
        max_weighted_mismatch=float(np.clip(max_mismatch, 0.0, 1.0)),
        weight_sum=float(weight_sum),
        must_pass=all_must_pass,
        feature_matches=tuple(matches),
    )

