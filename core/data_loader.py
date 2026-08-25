"""数据加载模块：从 PostgreSQL 加载捐精人数据并预处理。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from db.donors_repo import load_donors_dataframe, row_to_match_dict


def load_donor_data(active_only: bool = False) -> pd.DataFrame:
    """从官方库加载捐精人数据（中文列 DataFrame，供匹配使用）。"""
    df = load_donors_dataframe(active_only=active_only)
    required_cols = ["代号", "ABO血型", "民族", "身高", "学历", "体型", "标本数量", "是否可用"]
    # 空库允许启动（管理端后续导入）
    if df.empty:
        return df
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"捐精人数据缺少必要列: {missing}")
    return df


def _calc_age(birth_val) -> int:
    """从出生日期计算年龄，支持字符串和日期对象。"""
    if not birth_val or str(birth_val) in ("nan", "NaT", ""):
        return 0
    try:
        if hasattr(birth_val, "year"):
            born = birth_val.date() if hasattr(birth_val, "date") else birth_val
        else:
            born = date.fromisoformat(str(birth_val)[:10])
    except Exception:
        return 0
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _float_safe(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        import math

        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _val(row, key) -> str:
    v = row.get(key, "") if hasattr(row, "get") else (row[key] if key in row.index else "")
    s = str(v)
    return "" if s in ("nan", "NaT", "None", "") else s


# 未登录列表/筛选允许返回的 donor_info 字段（与 DonorCard 展示一致）
CARD_DONOR_KEYS = (
    "id",
    "code",
    "education",
    "height",
    "blood_type",
    "age",
    "ethnicity",
    "hometown",
    "figure",
    "personality",
    "occupation",
    "specimen_count",
    "availability",
)


def to_card_donor_info(info: dict) -> dict:
    """从完整展示信息中只保留公开卡片字段。"""
    return {k: info.get(k) for k in CARD_DONOR_KEYS}


def get_donor_display_info(row) -> dict:
    """提取用于前端展示的捐精人信息。"""
    # 支持 Series 或 dict
    if isinstance(row, dict):
        data = row
        # DB 行转中文列
        if "code" in data and "代号" not in data:
            data = row_to_match_dict(data)
    else:
        data = row

    def g(*keys, default=""):
        for k in keys:
            if hasattr(data, "get"):
                v = data.get(k)
            else:
                v = data[k] if k in getattr(data, "index", []) else None
            s = str(v) if v is not None else ""
            if s not in ("nan", "NaT", "None", ""):
                return s if default == "" or not isinstance(default, int) else v
        return default

    # 新表六类爱好多为「有/无」：摘要只列出为「有」的类别
    hobby_pairs = [
        ("爱好运动", "运动健身"),
        ("爱好艺术", "文化艺术"),
        ("爱好休闲", "休闲娱乐"),
        ("爱好旅游", "旅游度假"),
        ("爱好阅读", "小说书籍"),
        ("爱好美食", "美食饮品"),
    ]
    hobby_parts: list[str] = []
    for key, label in hobby_pairs:
        v = _val(data, key)
        if v == "有":
            hobby_parts.append(label)
        elif v and v not in ("无",):
            hobby_parts.append(f"{label}·{v}")
    single_hobby = _val(data, "爱好")
    hobby = "；".join(hobby_parts) if hobby_parts else single_hobby

    height = data.get("身高", 0) if hasattr(data, "get") else data.get("身高", 0)
    weight = data.get("体重", 0) if hasattr(data, "get") else 0
    bmi = data.get("BMI", data.get("体征指数", 0)) if hasattr(data, "get") else 0
    specimen = data.get("标本数量", 0) if hasattr(data, "get") else 0

    return {
        "id": _val(data, "编号") or _val(data, "代号"),
        "code": _val(data, "代号"),
        "blood_type": _val(data, "ABO血型") or _val(data, "血型"),
        "rh_blood": _val(data, "Rh血型") or _val(data, "RH血型"),
        "ethnicity": _val(data, "民族"),
        "height": int(height or 0),
        "age": _calc_age(data.get("出生日期") if hasattr(data, "get") else None),
        "constellation": _val(data, "星座"),
        "hometown": _val(data, "籍贯"),
        "occupation": _val(data, "职业"),
        "education": _val(data, "学历"),
        "face_shape": _val(data, "脸型"),
        "eyelid": _val(data, "眼皮"),
        "skin_color": _val(data, "肤色"),
        "lip_shape": _val(data, "唇型") or _val(data, "唇形"),
        "nose_bridge": _val(data, "鼻梁"),
        "hair_color": _val(data, "发色") or _val(data, "头发颜色"),
        "hair_style": _val(data, "发型"),
        "hair_volume": _val(data, "发量"),
        "beard": _val(data, "络腮胡") or _val(data, "络腓胡"),
        "mustache": _val(data, "胡须"),
        "figure": _val(data, "体型"),
        "weight": _float_safe(weight),
        "bmi": _float_safe(bmi),
        "personality": _val(data, "性格"),
        "hobby": hobby,
        "hobby_sports": _val(data, "爱好运动"),
        "hobby_arts": _val(data, "爱好艺术"),
        "hobby_leisure": _val(data, "爱好休闲"),
        "hobby_travel": _val(data, "爱好旅游"),
        "hobby_reading": _val(data, "爱好阅读"),
        "hobby_food": _val(data, "爱好美食"),
        "drink_history": _val(data, "喝酒史"),
        "smoke_history": _val(data, "吸烟史"),
        "personal_disease": _val(data, "个人病史"),
        "present_illness": _val(data, "现病史"),
        "past_illness": _val(data, "既往病史"),
        "surgery_history": _val(data, "手术史"),
        "personal_life_hist": _val(data, "个人生活史"),
        "partners_6m": _val(data, "性伴侣数"),
        "std_history": _val(data, "性传播疾病史"),
        "marital_fertility": _val(data, "婚育史"),
        "marriage_age": _val(data, "结婚年龄"),
        "children_info": _val(data, "生育子女"),
        "genetic_history": _val(data, "遗传病史"),
        "chromosome_disease": _val(data, "染色体病"),
        "monogenic_disease": _val(data, "单基因遗传病"),
        "polygenic_disease": _val(data, "多基因遗传病"),
        "consanguinity": _val(data, "近亲婚配"),
        "semen_test": _val(data, "精液检测"),
        "blood_test": _val(data, "血液检测"),
        "chromosome_test": _val(data, "染色体检测"),
        "microbio_test": _val(data, "微生物检测"),
        "specimen_count": int(specimen or 0),
        "availability": _val(data, "是否可用"),
        "status": _val(data, "状态") or "active",
        "remark": _val(data, "备注"),
    }
