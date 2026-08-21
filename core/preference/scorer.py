from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.data_loader import _calc_age
from core.preference.schema import FIELD_REGISTRY, EnumAttr, KeywordAttr, RangeAttr


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def normalize_rh(value: Any) -> str:
    s = "" if value is None else str(value).strip()
    if s in ("+", "阳性"):
        return "阳性"
    if s in ("-", "阴性"):
        return "阴性"
    return s


def donor_numeric(field: str, row: dict[str, Any]) -> float | None:
    spec = FIELD_REGISTRY[field]
    if field == "age":
        age = _calc_age(row.get("birth_date") or row.get(spec.db_column))
        return None if not age else float(age)
    raw = row.get(spec.db_column, row.get(field))
    if raw is None or str(raw).strip() in ("", "None", "nan", "NaT"):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def donor_text(field: str, row: dict[str, Any]) -> str:
    spec = FIELD_REGISTRY[field]
    raw = row.get(spec.db_column, row.get(field))
    if field == "rh_blood":
        return normalize_rh(raw)
    if raw is None:
        return ""
    s = str(raw).strip()
    return "" if s in ("None", "nan", "NaT") else s


def score_range(field: str, attr: RangeAttr, x: float | None) -> float:
    if x is None:
        return 0.0
    sigma = FIELD_REGISTRY[field].sigma or 1.0
    lo, hi = attr.range.min, attr.range.max
    if lo is not None and hi is not None:
        if lo <= x <= hi:
            return 1.0
        dist = lo - x if x < lo else x - hi
        return max(0.0, 1.0 - dist / sigma)
    if lo is not None:
        if x >= lo:
            return 0.8 + 0.2 * clamp((x - lo) / sigma, 0.0, 1.0)
        return 0.8 * max(0.0, 1.0 - (lo - x) / sigma)
    assert hi is not None
    if x <= hi:
        return 0.8 + 0.2 * clamp((hi - x) / sigma, 0.0, 1.0)
    return 0.8 * max(0.0, 1.0 - (x - hi) / sigma)


def score_enum(field: str, attr: EnumAttr, actual: str) -> float:
    spec = FIELD_REGISTRY[field]
    if not actual:
        return 0.0
    if spec.ordered_ranks:
        ranks = spec.ordered_ranks
        ar = ranks.get(actual)
        if ar is None:
            return 0.0
        max_gap = max(ranks.values()) - min(ranks.values())
        best = 0.0
        for target in attr.values:
            tr = ranks.get(target)
            if tr is None:
                continue
            best = max(best, 1.0 - abs(ar - tr) / max_gap)
        return best
    return 1.0 if actual in attr.values else 0.0


def score_keyword(attr: KeywordAttr, actual: str) -> float:
    if not actual:
        return 0.0
    hits = [kw for kw in attr.keywords if kw and kw in actual]
    if attr.match == "all":
        return 1.0 if len(hits) == len(attr.keywords) else 0.0
    return 1.0 if hits else 0.0


def score_field(field: str, attr: RangeAttr | EnumAttr | KeywordAttr, row: dict[str, Any]) -> float:
    spec = FIELD_REGISTRY[field]
    if spec.kind == "range":
        return score_range(field, attr, donor_numeric(field, row))
    if spec.kind == "enum":
        return score_enum(field, attr, donor_text(field, row))
    return score_keyword(attr, donor_text(field, row))


@dataclass
class FieldScore:
    field: str
    actual: Any
    target: Any
    s: float
    weight: float
    constraint: str


class Ranker:
    def score(self, profile, row: dict[str, Any]) -> tuple[float, list[FieldScore]]:
        raise NotImplementedError

    def rank(self, profile, rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float, list[FieldScore]]]:
        scored = []
        for row in rows:
            total, parts = self.score(profile, row)
            scored.append((row, total, parts))
        scored.sort(
            key=lambda t: (t[1], float(t[0].get("specimen_count") or 0)),
            reverse=True,
        )
        return scored


class HeuristicRanker(Ranker):
    def score(self, profile, row: dict[str, Any]) -> tuple[float, list[FieldScore]]:
        parts: list[FieldScore] = []
        num = 0.0
        den = 0.0
        for field, attr in profile.attributes.items():
            s = score_field(field, attr, row)
            if isinstance(attr, RangeAttr):
                target: Any = {"min": attr.range.min, "max": attr.range.max}
                actual: Any = donor_numeric(field, row)
            elif isinstance(attr, EnumAttr):
                target = list(attr.values)
                actual = donor_text(field, row)
            else:
                target = {"keywords": attr.keywords, "match": attr.match}
                actual = donor_text(field, row)
            parts.append(FieldScore(field, actual, target, s, attr.weight, attr.constraint))
            num += s * attr.weight
            den += attr.weight
        total = (num / den) if den else 0.0
        return total, parts
