"""结构化条件搜索 API（不经过 LLM）。

匹配策略：
  1. 所有用户选中的条件初始均为硬约束（must）。
  2. 若无结果，按用户优先级**从低到高**逐步放宽：
     - 先将最低优先级的字段从 must → prefer（仅影响排序不做硬过滤）。
     - 仍无结果则继续放宽上一级，直到有匹配。
  3. 阈值也会在放宽后降低，最终兜底为纯相似度排序。
"""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

LABEL_TO_FIELD = {
    "学历": "education", "身高": "height", "血型": "blood_type",
    "体型": "figure", "肤色": "skin_color", "脸型": "face_shape",
    "眼皮": "eyelid", "形象气质": "appearance",
    "唇形": "lip_shape", "星座": "constellation", "RH血型": "rh_blood",
    "民族": "ethnicity", "籍贯": "hometown", "职业": "occupation",
    "性格": "personality", "年龄": "age", "标本数量": "specimen_min",
}
FIELD_TO_LABEL = {v: k for k, v in LABEL_TO_FIELD.items()}


class SearchRequest(BaseModel):
    education: list[str] | None = None
    blood_type: list[str] | None = None
    height: str | None = None               # "170cm以上" | "170-180cm"
    age: str | None = None                  # "20-30岁" | "25岁以下"
    figure: list[str] | None = None
    skin_color: list[str] | None = None
    face_shape: list[str] | None = None
    eyelid: list[str] | None = None
    appearance: list[str] | None = None
    lip_shape: list[str] | None = None
    constellation: list[str] | None = None
    rh_blood: list[str] | None = None
    ethnicity: list[str] | None = None      # 民族关键词
    hometown: list[str] | None = None       # 籍贯关键词（如 四川, 重庆）
    occupation: list[str] | None = None     # 职业关键词
    personality: list[str] | None = None    # 性格关键词（如 开朗, 活泼）
    specimen_min: int | None = None         # 标本数量最少要求
    priority: list[str] = []
    top_k: int = 10


def _parse_height(h_str: str) -> dict:
    """将前端身高选项转为 {min, max} 字典。"""
    if not h_str:
        return {}
    m = re.match(r"(\d+)cm以上", h_str)
    if m:
        return {"min": int(m.group(1)), "max": None}
    m = re.match(r"(\d+)-(\d+)cm", h_str)
    if m:
        return {"min": int(m.group(1)), "max": int(m.group(2))}
    return {}


def _parse_age(a_str: str) -> dict:
    """将前端年龄选项转为 {min, max} 字典。"""
    if not a_str:
        return {}
    m = re.match(r"(\d+)岁以下", a_str)
    if m:
        return {"min": None, "max": int(m.group(1))}
    m = re.match(r"(\d+)岁以上", a_str)
    if m:
        return {"min": int(m.group(1)), "max": None}
    m = re.match(r"(\d+)[-~～](\d+)岁", a_str)
    if m:
        return {"min": int(m.group(1)), "max": int(m.group(2))}
    return {}


def _build_relax_order(priority_labels: list[str], active_fields: set[str]) -> list[str]:
    """根据用户优先级构建放宽顺序（低优先级在前，优先被放宽）。

    只返回用户实际选中的字段。
    """
    # 将优先级标签映射为字段名
    ordered = []
    for label in priority_labels:
        field = LABEL_TO_FIELD.get(label)
        if field and field in active_fields:
            ordered.append(field)
    # 补上不在优先级列表中但被选中的字段（放在最低优先级 → 最先放宽）
    for f in active_fields:
        if f not in ordered:
            ordered.append(f)
    # 反转：低优先级先放宽
    ordered.reverse()
    return ordered


@router.post("/api/search")
async def search_donors(request: SearchRequest, req: Request):
    """根据结构化条件直接搜索匹配的捐精人（不经过 LLM）。"""
    from core.matcher import compute_similarity, hard_filter, filter_candidates
    from core.ranker import rank_and_explain

    app = req.app
    donor_df = app.state.donor_df
    encoder = app.state.encoder

    if donor_df is None or encoder is None:
        raise HTTPException(status_code=500, detail="系统未就绪")

    # ── 1. 构建 parsed_features ──
    # 多选字段存为 list，身高存为 dict
    parsed_features = {}
    if request.education:
        parsed_features["education"] = request.education
    if request.blood_type:
        parsed_features["blood_type"] = request.blood_type
    if request.height:
        h = _parse_height(request.height)
        if h:
            parsed_features["height"] = h
    if request.figure:
        parsed_features["figure"] = request.figure
    if request.skin_color:
        parsed_features["skin_color"] = request.skin_color
    if request.face_shape:
        parsed_features["face_shape"] = request.face_shape
    if request.eyelid:
        parsed_features["eyelid"] = request.eyelid
    if request.appearance:
        parsed_features["appearance"] = request.appearance
    if request.lip_shape:
        parsed_features["lip_shape"] = request.lip_shape
    if request.constellation:
        parsed_features["constellation"] = request.constellation
    if request.rh_blood:
        parsed_features["rh_blood"] = request.rh_blood
    if request.ethnicity:
        parsed_features["ethnicity"] = request.ethnicity
    if request.hometown:
        parsed_features["hometown"] = request.hometown
    if request.occupation:
        parsed_features["occupation"] = request.occupation
    if request.personality:
        parsed_features["personality"] = request.personality
    if request.age:
        a = _parse_age(request.age)
        if a:
            parsed_features["age"] = a
    if request.specimen_min:
        parsed_features["specimen_min"] = request.specimen_min

    if not parsed_features:
        raise HTTPException(status_code=400, detail="请至少选择一个筛选条件")

    # ── 2. 初始约束：所有已选条件 = must ──
    constraints = {f: "must" for f in parsed_features}

    # ── 3. 计算相似度（贯穿始终，用于排序） ──
    query_vec, mask = encoder.encode_query(parsed_features)
    scores = compute_similarity(query_vec, encoder.feature_matrix, mask=mask)

    # ── 4. 基于优先级的三级渐进放宽 ──
    #   每个字段有三种状态：strict(精确) → broadened(向上兼容) → removed(移除)
    #   有序字段(学历/身高/肤色)先 broaden 再 remove；无序字段直接 remove。
    from core.matcher import BROADABLE_FIELDS

    relax_order = _build_relax_order(request.priority, set(parsed_features.keys()))
    broadened_set = set()         # 当前处于 broadened 状态的字段
    relaxed_fields = []           # 被放宽的字段（含 broadened 和 removed）
    relaxed_details = {}          # field → "broadened" | "removed"
    match_level = "full"
    # 条件筛选模式：硬约束由 hard_filter 保证，相似度仅用于排序
    # 初始阈值低一些，放宽后进一步降低
    threshold = 0.3
    relaxed_threshold = 0.0

    # 第一轮：全部 strict must
    h_mask = hard_filter(donor_df, parsed_features, constraints, broadened=broadened_set)
    cands = filter_candidates(scores, threshold=threshold, hard_mask=h_mask)

    if not cands:
        # 第二轮：按优先级从低到高，逐个字段做三级放宽
        for field in relax_order:
            if constraints.get(field) != "must":
                continue

            # Step A：若为有序字段，先尝试 broaden（向上兼容）
            if field in BROADABLE_FIELDS:
                broadened_set.add(field)
                h_mask = hard_filter(donor_df, parsed_features, constraints, broadened=broadened_set)
                cands = filter_candidates(scores, threshold=relaxed_threshold, hard_mask=h_mask)
                if cands:
                    relaxed_fields.append(field)
                    relaxed_details[field] = "broadened"
                    match_level = "relaxed"
                    break
                broadened_set.discard(field)

            # Step B：broaden 不够 → 彻底移除约束
            constraints[field] = "prefer"
            relaxed_fields.append(field)
            relaxed_details[field] = "removed"
            h_mask = hard_filter(donor_df, parsed_features, constraints, broadened=broadened_set)
            cands = filter_candidates(scores, threshold=relaxed_threshold, hard_mask=h_mask)
            if cands:
                match_level = "relaxed"
                break

    if not cands:
        # 第三轮：降低阈值到 0
        h_mask = hard_filter(donor_df, parsed_features, constraints, broadened=broadened_set)
        cands = filter_candidates(scores, threshold=0.0, hard_mask=h_mask)
        if cands:
            match_level = "relaxed"

    if not cands:
        # 第四轮：兜底，纯相似度排序
        import numpy as np
        all_idx = np.argsort(-scores)
        cands = [(int(i), float(scores[i])) for i in all_idx[:request.top_k]]
        match_level = "similarity_only"
        relaxed_fields = list(parsed_features.keys())
        relaxed_details = {f: "removed" for f in relaxed_fields}

    # ── 5. 排序 & 生成推荐理由 ──
    results = rank_and_explain(
        cands, donor_df, parsed_features,
        top_k=request.top_k,
        match_level=match_level,
    )

    # 构建放宽说明（区分 broadened 和 removed）
    BROADEN_HINT = {
        "education": "学历(含更高学历)",
        "height": "身高(下限降低5cm)",
        "skin_color": "肤色(含更优肤色)",
    }
    hint_parts = []
    for f in relaxed_fields:
        label = FIELD_TO_LABEL.get(f, f)
        if relaxed_details.get(f) == "broadened":
            hint_parts.append(BROADEN_HINT.get(f, f"{label}(向上兼容)"))
        else:
            hint_parts.append(f"{label}(已移除)")

    return {
        "items": results,
        "total": len(results),
        "parsed_features": parsed_features,
        "match_level": match_level,
        "relaxed_fields": relaxed_fields,
        "relaxed_details": relaxed_details,
        "relaxed_hint": f"已放宽：{'、'.join(hint_parts)}" if hint_parts else "",
    }
