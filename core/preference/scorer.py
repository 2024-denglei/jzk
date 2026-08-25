"""偏好画像打分与排序。

SQL 硬过滤之后，对剩余捐精人按 PreferenceProfile 打分。
只给 attributes 里出现的字段打分；must / prefer 公式相同，差别只在 weight。

总分：score = Σ (s_f × weight_f) / Σ weight_f
以后换训练模型时，实现 Ranker 即可替换 HeuristicRanker。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.data_loader import _calc_age
from core.preference.schema import FIELD_REGISTRY, EnumAttr, KeywordAttr, RangeAttr


def clamp(x: float, lo: float, hi: float) -> float:
    """把 x 限制在 [lo, hi]。"""
    return max(lo, min(hi, x))


def normalize_rh(value: Any) -> str:
    """Rh 血型统一成「阳性 / 阴性」，兼容库里的 + / -。"""
    s = "" if value is None else str(value).strip()
    if s in ("+", "阳性"):
        return "阳性"
    if s in ("-", "阴性"):
        return "阴性"
    return s


def donor_numeric(field: str, row: dict[str, Any]) -> float | None:
    """从捐精人行取出数值字段。age 由 birth_date 算周岁；缺值返回 None。"""
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
    """从捐精人行取出文本字段。Rh 会先规范化。"""
    spec = FIELD_REGISTRY[field]
    raw = row.get(spec.db_column, row.get(field))
    if field == "rh_blood":
        return normalize_rh(raw)
    if raw is None:
        return ""
    s = str(raw).strip()
    return "" if s in ("None", "nan", "NaT") else s


def score_range(field: str, attr: RangeAttr, x: float | None) -> float:
    """区间字段分 s ∈ [0, 1]。σ 见 FIELD_REGISTRY（身高 10、体重 8 等）。

    双侧 min+max：区间内 1.0；区间外按距边界 / σ 线性掉到 0。
    仅 min（如身高 ≥175）：x≥min 时 0.8～1.0（越高越好，差 1σ 到满分）；
    x<min 时从 0.8 往下掉。仅 max 对称（越小越好）。
    """
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
        # 只设下限：踩线 0.8，再高加分；低于下限扣分
        if x >= lo:
            return 0.8 + 0.2 * clamp((x - lo) / sigma, 0.0, 1.0)
        return 0.8 * max(0.0, 1.0 - (lo - x) / sigma)
    assert hi is not None
    # 只设上限：踩线 0.8，再低加分；高于上限扣分
    if x <= hi:
        return 0.8 + 0.2 * clamp((hi - x) / sigma, 0.0, 1.0)
    return 0.8 * max(0.0, 1.0 - (x - hi) / sigma)


def score_enum(field: str, attr: EnumAttr, actual: str) -> float:
    """枚举字段分。无序枚举：命中 values（或关系）得 1，否则 0。

    有序枚举（学历、肤色）：按等级距离对称打分。
    s = 1 - |rank(实际) - rank(目标)| / max_rank_gap
    多项目标取最高分。例：目标硕士时 硕士>博士=本科>大专。
    """
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
    """关键词字段：子串命中。match=any 命中任一即 1；all 须全部命中。"""
    if not actual:
        return 0.0
    hits = [kw for kw in attr.keywords if kw and kw in actual]
    if attr.match == "all":
        return 1.0 if len(hits) == len(attr.keywords) else 0.0
    return 1.0 if hits else 0.0


def score_field(field: str, attr: RangeAttr | EnumAttr | KeywordAttr, row: dict[str, Any]) -> float:
    """按字段注册表的 kind 分发到 range / enum / keyword。"""
    spec = FIELD_REGISTRY[field]
    if spec.kind == "range":
        return score_range(field, attr, donor_numeric(field, row))
    if spec.kind == "enum":
        return score_enum(field, attr, donor_text(field, row))
    return score_keyword(attr, donor_text(field, row))


@dataclass
class FieldScore:
    """单个字段的打分明细，给前端 field_match 和训练日志用。"""

    field: str
    actual: Any  # 捐精人实际值
    target: Any  # 用户偏好（range / values / keywords）
    s: float  # 该项 0～1
    weight: float
    constraint: str  # must | prefer，打分公式不区分，仅记录


class Ranker:
    """排序层接口。训练模型替换 HeuristicRanker 时实现 score 即可。"""

    def score(self, profile, row: dict[str, Any]) -> tuple[float, list[FieldScore]]:
        raise NotImplementedError

    def rank(self, profile, rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float, list[FieldScore]]]:
        """对硬过滤后的行打分，按总分降序；同分看 specimen_count。"""
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
    """第一期启发式：各字段加权平均。未出现在画像里的字段不参与。"""

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
