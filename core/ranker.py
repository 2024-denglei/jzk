"""排序与推荐理由生成模块。"""

import pandas as pd

from config import MATCH_TOP_K
from core.data_loader import get_donor_display_info
from core.matcher import compute_field_match


def rank_and_explain(
    candidates: list[tuple[int, float]],
    df: pd.DataFrame,
    parsed_features: dict,
    top_k: int | None = None,
    match_level: str = "full",
) -> list[dict]:
    """对候选捐精人排序并生成推荐理由。

    Args:
        candidates: [(df_index, score), ...] 已按得分降序
        df: 可用捐精人 DataFrame
        parsed_features: 用户需求解析结果
        top_k: 返回条数
        match_level: "full" | "relaxed" | "similarity_only"

    Returns:
        [{"donor_info": {...}, "score": float, "reason": str,
          "match_level": str, "field_match": {...}}, ...]
    """
    if top_k is None:
        top_k = MATCH_TOP_K

    # 软加分：文本偏好字段命中提升排名
    candidates = _apply_text_bonus(candidates, df, parsed_features)

    results = []
    for idx, score in candidates[:top_k]:
        row = df.iloc[idx]
        donor_info = get_donor_display_info(row)
        field_match = compute_field_match(row, parsed_features)
        reason = _generate_reason(donor_info, parsed_features, score, match_level, field_match)

        # 条件命中率：匹配条件数 / 总条件数
        total_fields = len(field_match)
        matched_fields = sum(1 for v in field_match.values() if v["match"])
        match_pct = round(matched_fields / total_fields * 100, 1) if total_fields > 0 else 0

        results.append({
            "donor_info": donor_info,
            "score": round(score, 4),
            "match_pct": match_pct,
            "reason": reason,
            "match_level": match_level,
            "field_match": field_match,
        })
    return results


_FIELD_LABEL = {
    "education": "学历", "blood_type": "血型", "height": "身高",
    "age": "年龄", "figure": "体型", "skin_color": "肤色",
    "face_shape": "脸型", "eyelid": "眼皮", "appearance": "形象气质",
    "lip_shape": "唇形", "constellation": "星座", "rh_blood": "RH血型",
    "ethnicity": "民族", "hometown": "籍贯", "occupation": "职业",
    "personality": "性格", "specimen_min": "标本数量",
}

# 纯文本字段（不在特征向量中，通过关键词软加分提升排名）
_TEXT_FIELD_COL = {
    "personality": "性格",
    "occupation": "职业",
    "hometown": "籍贯",
    "ethnicity": "民族",
}
_TEXT_BONUS = 0.06  # 每个匹配文本字段的加分幅度


def _apply_text_bonus(
    candidates: list[tuple[int, float]],
    df,
    parsed_features: dict,
) -> list[tuple[int, float]]:
    """对文本偏好字段(personality/occupation/hometown/ethnicity)命中时给分数加成。"""
    boosted = []
    for idx, score in candidates:
        row = df.iloc[idx]
        bonus = 0.0
        for field, col in _TEXT_FIELD_COL.items():
            val = parsed_features.get(field)
            if not val:
                continue
            val_list = val if isinstance(val, list) else [val]
            actual = str(row.get(col, ""))
            if any(v in actual for v in val_list):
                bonus += _TEXT_BONUS
        boosted.append((idx, min(1.0, score + bonus)))
    boosted.sort(key=lambda x: x[1], reverse=True)
    return boosted


def _generate_reason(
    donor: dict,
    parsed_features: dict,
    score: float,
    match_level: str = "full",
    field_match: dict | None = None,
) -> str:
    """基于匹配特征生成自然语言推荐理由。"""
    matched = []
    unmatched = []

    if field_match:
        for field, info in field_match.items():
            label = _FIELD_LABEL.get(field, field)
            if info["match"]:
                matched.append(f"{label}({info['actual']})✓")
            else:
                unmatched.append(f"{label}(您要求{info['user']}，实际{info['actual']})")

    parts = []
    if matched:
        parts.append("符合条件：" + "、".join(matched))
    if unmatched:
        parts.append("未完全符合：" + "、".join(unmatched))

    # 补充无关条件的亮点
    if donor.get("appearance") and "appearance" not in (field_match or {}):
        parts.append(f"形象气质{donor['appearance']}")
    if donor.get("personality"):
        parts.append(f"性格{donor['personality']}")

    if not parts:
        parts.append("综合特征较为匹配")

    # 条件命中率
    total = len(field_match) if field_match else 0
    matched_cnt = sum(1 for v in (field_match or {}).values() if v["match"])
    match_pct = round(matched_cnt / total * 100, 1) if total > 0 else 0

    level_hint = ""
    if match_level == "relaxed":
        level_hint = "（已放宽部分条件）"
    elif match_level == "similarity_only":
        level_hint = "（按综合相似度排序）"

    reason = f"综合匹配度 {match_pct}%{level_hint}。" + "；".join(parts) + "。"
    return reason
