"""匹配计算模块：基于余弦相似度 + 欧氏距离融合计算。"""

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity, euclidean_distances

from config import COSINE_WEIGHT, EUCLIDEAN_WEIGHT, MATCH_THRESHOLD


def compute_similarity(
    query_vector: np.ndarray,
    donor_matrix: np.ndarray,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """计算查询向量与所有捐精人特征向量的融合相似度。

    Args:
        query_vector: 查询向量
        donor_matrix: 捐精人特征矩阵
        mask: 布尔数组，标记用户关心的维度（True=关心）。
              None 时自动推断：query_vector 中非默认值(0.5)的维度视为关心。

    返回形状为 (n_donors,) 的得分数组，范围 [0, 1]。
    """
    if mask is None:
        # 自动生成 mask：非零且非默认值(0.5)的维度
        mask = ~np.isclose(query_vector, 0.0)
        # 数值特征（前4维）中 0.5 是默认值，也排除
        for i in range(min(4, len(query_vector))):
            if np.isclose(query_vector[i], 0.5):
                mask[i] = False

    # 如果没有任何有效维度，返回均匀分数
    if not mask.any():
        return np.full(donor_matrix.shape[0], 0.5)

    # 仅取关心的维度
    q_masked = query_vector[mask].reshape(1, -1)
    d_masked = donor_matrix[:, mask]

    # 余弦相似度
    cos_sim = cosine_similarity(q_masked, d_masked)[0]
    cos_sim = np.clip(cos_sim, 0.0, 1.0)

    # 欧氏距离 → 归一化
    euc_dist = euclidean_distances(q_masked, d_masked)[0]
    euc_max = euc_dist.max() if euc_dist.max() > 0 else 1.0
    euc_norm = euc_dist / euc_max

    # 融合得分
    scores = COSINE_WEIGHT * cos_sim + EUCLIDEAN_WEIGHT * (1.0 - euc_norm)
    return scores


"""有序属性的等级映射（值越大越"好"）。"""
EDUCATION_RANK = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}
SKIN_RANK = {"小麦": 1, "一般": 2, "偏白": 3}

# 可被"向上兼容"放宽的有序字段
BROADABLE_FIELDS = {"education", "height", "skin_color"}


def hard_filter(
    donor_df,
    parsed_features: dict,
    constraints: dict | None = None,
    broadened: set | None = None,
) -> np.ndarray:
    """根据用户的硬约束条件生成布尔 mask（True=符合条件）。

    constraints 字典中每个字段标记为 "must" 或 "prefer"：
      - must:   硬约束，不满足直接排除
      - prefer: 软偏好，不参与硬过滤（仅影响相似度排序）

    broadened 集合中的字段使用"向上兼容"放宽匹配：
      - education: 匹配用户所选及更高学历
      - height:    下限降低 5cm（更高的仍保留）
      - skin_color: 匹配用户所选及更优肤色
      - 无序字段（血型/体型/脸型/眼皮/气质）: 直接跳过过滤

    如果 constraints 未提供或某字段未标记，使用默认规则：
      - education, blood_type, height → 默认 must
      - 其余 → 默认 prefer
    """
    if constraints is None:
        constraints = {}
    if broadened is None:
        broadened = set()

    # 默认约束级别
    DEFAULT_CONSTRAINTS = {
        "education": "must",
        "blood_type": "must",
        "height": "must",
        "ethnicity": "must",
        "hometown": "must",
        "rh_blood": "must",
        "age": "must",
        "specimen_min": "prefer",
        "figure": "prefer",
        "skin_color": "prefer",
        "face_shape": "prefer",
        "eyelid": "prefer",
        "appearance": "prefer",
        "lip_shape": "prefer",
        "constellation": "prefer",
        "occupation": "prefer",
        "personality": "prefer",
    }

    def _is_must(field: str) -> bool:
        return constraints.get(field, DEFAULT_CONSTRAINTS.get(field, "prefer")) == "must"

    def _is_broadened(field: str) -> bool:
        return field in broadened

    def _to_list(val):
        """统一转为 list：兼容单值(str)和多选(list)。"""
        if val is None:
            return []
        return val if isinstance(val, list) else [val]

    mask = np.ones(len(donor_df), dtype=bool)

    # 学历（有序，支持多选 + broadened 向上兼容）
    edu_vals = _to_list(parsed_features.get("education"))
    if edu_vals and _is_must("education"):
        if _is_broadened("education"):
            min_rank = min(EDUCATION_RANK.get(e, 0) for e in edu_vals)
            mask &= donor_df["学历"].map(
                lambda x: EDUCATION_RANK.get(x, 0) >= min_rank
            ).values
        else:
            mask &= donor_df["学历"].isin(edu_vals).values

    # 血型（无序，broadened = 跳过）
    blood_vals = _to_list(parsed_features.get("blood_type"))
    blood_col = "ABO血型" if "ABO血型" in donor_df.columns else "血型"
    if blood_vals and _is_must("blood_type") and not _is_broadened("blood_type"):
        mask &= donor_df[blood_col].isin(blood_vals).values

    # 身高（单选范围，不变）
    height_spec = parsed_features.get("height")
    if height_spec and isinstance(height_spec, dict) and _is_must("height"):
        h_min = height_spec.get("min")
        h_max = height_spec.get("max")
        if _is_broadened("height"):
            if h_min:
                mask &= (donor_df["身高"] >= max(h_min - 5, 160)).values
        else:
            if h_min:
                mask &= (donor_df["身高"] >= h_min).values
            if h_max:
                mask &= (donor_df["身高"] <= h_max).values

    # 体型（无序，broadened = 跳过）
    figure_vals = _to_list(parsed_features.get("figure"))
    if figure_vals and _is_must("figure") and not _is_broadened("figure"):
        mask &= donor_df["体型"].isin(figure_vals).values

    # 肤色（有序，支持多选 + broadened 向上兼容）
    skin_vals = _to_list(parsed_features.get("skin_color"))
    if skin_vals and _is_must("skin_color"):
        if _is_broadened("skin_color"):
            min_rank = min(SKIN_RANK.get(s, 0) for s in skin_vals)
            mask &= donor_df["肤色"].map(
                lambda x: SKIN_RANK.get(x, 0) >= min_rank
            ).values
        else:
            mask &= donor_df["肤色"].isin(skin_vals).values

    # 脸型（无序，broadened = 跳过）
    face_vals = _to_list(parsed_features.get("face_shape"))
    if face_vals and _is_must("face_shape") and not _is_broadened("face_shape"):
        mask &= donor_df["脸型"].isin(face_vals).values

    # 眼皮（无序，broadened = 跳过）
    eyelid_vals = _to_list(parsed_features.get("eyelid"))
    if eyelid_vals and _is_must("eyelid") and not _is_broadened("eyelid"):
        mask &= donor_df["眼皮"].isin(eyelid_vals).values

    # 唇型（无序）
    lip_vals = _to_list(parsed_features.get("lip_shape"))
    lip_col = "唇型" if "唇型" in donor_df.columns else "唇形"
    if lip_vals and _is_must("lip_shape") and not _is_broadened("lip_shape"):
        mask &= donor_df[lip_col].isin(lip_vals).values

    # 星座（无序）
    const_vals = _to_list(parsed_features.get("constellation"))
    if const_vals and _is_must("constellation") and not _is_broadened("constellation"):
        mask &= donor_df["星座"].isin(const_vals).values if "星座" in donor_df.columns else mask

    # RH血型
    rh_vals = _to_list(parsed_features.get("rh_blood"))
    rh_col = "Rh血型" if "Rh血型" in donor_df.columns else "RH血型"
    if rh_vals and _is_must("rh_blood") and not _is_broadened("rh_blood") and rh_col in donor_df.columns:
        mask &= donor_df[rh_col].isin(rh_vals).values

    # 民族（关键词包含匹配）
    eth_vals = _to_list(parsed_features.get("ethnicity"))
    if eth_vals and _is_must("ethnicity"):
        mask &= donor_df["民族"].apply(lambda x: any(v in str(x) for v in eth_vals)).values

    # 籍贯（关键词包含匹配）
    ht_vals = _to_list(parsed_features.get("hometown"))
    if ht_vals and _is_must("hometown") and "籍贯" in donor_df.columns:
        mask &= donor_df["籍贯"].apply(lambda x: any(v in str(x) for v in ht_vals)).values

    # 职业（关键词包含匹配）
    occ_vals = _to_list(parsed_features.get("occupation"))
    if occ_vals and _is_must("occupation") and "职业" in donor_df.columns:
        mask &= donor_df["职业"].apply(lambda x: any(v in str(x) for v in occ_vals)).values

    # 性格（关键词包含匹配）
    pers_vals = _to_list(parsed_features.get("personality"))
    if pers_vals and _is_must("personality"):
        mask &= donor_df["性格"].apply(lambda x: any(v in str(x) for v in pers_vals)).values

    # 年龄范围
    age_spec = parsed_features.get("age")
    if age_spec and isinstance(age_spec, dict) and _is_must("age") and "出生日期" in donor_df.columns:
        from core.data_loader import _calc_age
        ages = donor_df["出生日期"].apply(_calc_age)
        a_min = age_spec.get("min")
        a_max = age_spec.get("max")
        if a_min:
            mask &= (ages >= a_min).values
        if a_max:
            mask &= (ages <= a_max).values

    # 标本数量下限
    spec_min = parsed_features.get("specimen_min")
    if spec_min and _is_must("specimen_min"):
        mask &= (donor_df["标本数量"] >= int(spec_min)).values

    return mask


def filter_candidates(
    scores: np.ndarray,
    threshold: float | None = None,
    hard_mask: np.ndarray | None = None,
) -> list[tuple[int, float]]:
    """过滤有效匹配（得分 >= 阈值 + 硬约束），返回 [(index, score), ...] 降序。"""
    if threshold is None:
        threshold = MATCH_THRESHOLD

    candidates = []
    for i in range(len(scores)):
        # 硬约束不满足则跳过
        if hard_mask is not None and not hard_mask[i]:
            continue
        if scores[i] >= threshold:
            candidates.append((int(i), float(scores[i])))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


# ============ 渐进式放宽匹配 ============

# 约束放宽优先级（越靠后越先被放宽）
_RELAX_ORDER = [
    "constellation", "personality", "occupation", "lip_shape",
    "appearance", "eyelid", "face_shape", "skin_color",
    "ethnicity", "hometown", "figure", "specimen_min",
    "height", "blood_type", "rh_blood", "age", "education",
]


def match_with_relaxation(
    donor_df,
    parsed_features: dict,
    scores: np.ndarray,
    constraints: dict | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
) -> tuple[list[tuple[int, float]], str, list[str]]:
    """渐进式放宽硬约束匹配。

    top_k <= 0 或 None 且配置 MATCH_TOP_K<=0 时：返回全部符合条件者（不截断）。

    返回:
        (candidates, match_level, relaxed_fields)
        match_level: "full" | "relaxed" | "similarity_only"
        relaxed_fields: 被放宽的字段列表（full 时为空）
    """
    from config import MATCH_TOP_K as _CFG_TOP_K

    if threshold is None:
        threshold = MATCH_THRESHOLD
    if top_k is None:
        top_k = _CFG_TOP_K

    def _take(cands: list[tuple[int, float]]) -> list[tuple[int, float]]:
        if not top_k or top_k <= 0:
            return cands
        return cands[:top_k]

    # 第一步：全部硬约束
    h_mask = hard_filter(donor_df, parsed_features, constraints)
    cands = filter_candidates(scores, threshold=threshold, hard_mask=h_mask)
    if len(cands) >= 1:
        return _take(cands), "full", []

    # 第二步：逐步放宽硬约束（按 _RELAX_ORDER 从尾部开始放宽）
    relaxed_constraints = dict(constraints) if constraints else {}
    relaxed_fields = []
    for field in _RELAX_ORDER:
        if relaxed_constraints.get(field) == "must" or (
            field not in relaxed_constraints
            and field in ("education", "blood_type", "height")
        ):
            relaxed_constraints[field] = "prefer"
            relaxed_fields.append(field)
            h_mask = hard_filter(donor_df, parsed_features, relaxed_constraints)
            cands = filter_candidates(scores, threshold=threshold, hard_mask=h_mask)
            if len(cands) >= 1:
                return _take(cands), "relaxed", relaxed_fields

    # 第三步：去掉阈值限制，仍用放宽后的约束
    h_mask = hard_filter(donor_df, parsed_features, relaxed_constraints)
    cands = filter_candidates(scores, threshold=0.0, hard_mask=h_mask)
    if len(cands) >= 1:
        return _take(cands), "relaxed", relaxed_fields

    # 第四步：完全不过滤，纯相似度排序
    all_cands = [(int(i), float(scores[i])) for i in range(len(scores))]
    all_cands.sort(key=lambda x: x[1], reverse=True)
    return _take(all_cands), "similarity_only", relaxed_fields


def diagnose_no_match(
    donor_df,
    parsed_features: dict,
    constraints: dict,
    scores: np.ndarray,
    threshold: float | None = None,
) -> list[str]:
    """诊断哪些 must 字段单独导致了零匹配，用于指导用户放宽条件。

    逐一将每个 must 字段放宽，检查放宽后是否有结果，
    若放宽该字段后出现结果则认为该字段是瓶颈。

    返回: 瓶颈字段列表（中文标签）
    """
    from core.ranker import _FIELD_LABEL  # 避免循环导入
    if threshold is None:
        threshold = MATCH_THRESHOLD

    must_fields = [f for f, v in constraints.items() if v == "must" and parsed_features.get(f)]
    bottlenecks = []
    for field in must_fields:
        test_constraints = dict(constraints)
        test_constraints[field] = "prefer"
        h_mask = hard_filter(donor_df, parsed_features, test_constraints)
        cands = filter_candidates(scores, threshold=threshold, hard_mask=h_mask)
        if len(cands) >= 1:
            bottlenecks.append(_FIELD_LABEL.get(field, field))
    return bottlenecks


def compute_field_match(donor_row, parsed_features: dict) -> dict:
    """计算单个捐精人与用户需求的逐字段匹配情况。

    支持多选：字段值为 list 时，actual in list 即为匹配。
    返回 {field_name: {"match": bool, "user": str, "actual": str}} 的字典。
    """
    def _match_cat(val, actual):
        """分类字段匹配：支持 str 或 list。"""
        if isinstance(val, list):
            return actual in val, "/".join(val)
        return actual == val, val

    result = {}

    edu = parsed_features.get("education")
    if edu:
        actual = str(donor_row.get("学历", ""))
        matched, label = _match_cat(edu, actual)
        result["education"] = {"match": matched, "user": label, "actual": actual}

    blood = parsed_features.get("blood_type")
    if blood:
        actual = str(donor_row.get("ABO血型") or donor_row.get("血型", ""))
        matched, label = _match_cat(blood, actual)
        result["blood_type"] = {"match": matched, "user": label, "actual": actual}

    height_spec = parsed_features.get("height")
    if height_spec and isinstance(height_spec, dict):
        h = int(donor_row.get("身高", 0))
        h_min = height_spec.get("min")
        h_max = height_spec.get("max")
        ok = True
        label = ""
        if h_min:
            ok = ok and h >= h_min
            label += f">={h_min}"
        if h_max:
            ok = ok and h <= h_max
            label += f" <={h_max}"
        result["height"] = {"match": ok, "user": label.strip(), "actual": f"{h}cm"}

    figure = parsed_features.get("figure")
    if figure:
        actual = str(donor_row.get("体型", ""))
        matched, label = _match_cat(figure, actual)
        result["figure"] = {"match": matched, "user": label, "actual": actual}

    skin = parsed_features.get("skin_color")
    if skin:
        actual = str(donor_row.get("肤色", ""))
        matched, label = _match_cat(skin, actual)
        result["skin_color"] = {"match": matched, "user": label, "actual": actual}

    face = parsed_features.get("face_shape")
    if face:
        actual = str(donor_row.get("脸型", ""))
        matched, label = _match_cat(face, actual)
        result["face_shape"] = {"match": matched, "user": label, "actual": actual}

    eyelid = parsed_features.get("eyelid")
    if eyelid:
        actual = str(donor_row.get("眼皮", ""))
        matched, label = _match_cat(eyelid, actual)
        result["eyelid"] = {"match": matched, "user": label, "actual": actual}

    lip = parsed_features.get("lip_shape")
    if lip:
        actual = str(donor_row.get("唇型") or donor_row.get("唇形", ""))
        matched, label = _match_cat(lip, actual)
        result["lip_shape"] = {"match": matched, "user": label, "actual": actual}

    const = parsed_features.get("constellation")
    if const:
        actual = str(donor_row.get("星座", ""))
        matched, label = _match_cat(const, actual)
        result["constellation"] = {"match": matched, "user": label, "actual": actual}

    rh = parsed_features.get("rh_blood")
    if rh:
        actual = str(donor_row.get("Rh血型") or donor_row.get("RH血型", ""))
        matched, label = _match_cat(rh, actual)
        result["rh_blood"] = {"match": matched, "user": label, "actual": actual}

    eth = parsed_features.get("ethnicity")
    if eth:
        actual = str(donor_row.get("民族", ""))
        eth_list = eth if isinstance(eth, list) else [eth]
        matched = any(v in actual for v in eth_list)
        result["ethnicity"] = {"match": matched, "user": "/".join(eth_list), "actual": actual}

    ht = parsed_features.get("hometown")
    if ht:
        actual = str(donor_row.get("籍贯", ""))
        ht_list = ht if isinstance(ht, list) else [ht]
        matched = any(v in actual for v in ht_list)
        result["hometown"] = {"match": matched, "user": "/".join(ht_list), "actual": actual}

    occ = parsed_features.get("occupation")
    if occ:
        actual = str(donor_row.get("职业", ""))
        occ_list = occ if isinstance(occ, list) else [occ]
        matched = any(v in actual for v in occ_list)
        result["occupation"] = {"match": matched, "user": "/".join(occ_list), "actual": actual}

    pers = parsed_features.get("personality")
    if pers:
        actual = str(donor_row.get("性格", ""))
        pers_list = pers if isinstance(pers, list) else [pers]
        matched = any(v in actual for v in pers_list)
        result["personality"] = {"match": matched, "user": "/".join(pers_list), "actual": actual}

    age_spec = parsed_features.get("age")
    if age_spec and isinstance(age_spec, dict):
        from core.data_loader import _calc_age
        actual_age = _calc_age(donor_row.get("出生日期"))
        a_min = age_spec.get("min")
        a_max = age_spec.get("max")
        ok = True
        label = ""
        if a_min:
            ok = ok and actual_age >= a_min
            label += f">={a_min}"
        if a_max:
            ok = ok and actual_age <= a_max
            label += f" <={a_max}"
        result["age"] = {"match": ok, "user": label.strip(), "actual": f"{actual_age}岁"}

    spec_min = parsed_features.get("specimen_min")
    if spec_min:
        actual_cnt = int(donor_row.get("标本数量", 0) or 0)
        result["specimen_min"] = {"match": actual_cnt >= int(spec_min), "user": f">={spec_min}", "actual": str(actual_cnt)}

    return result
