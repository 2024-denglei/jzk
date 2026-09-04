"""捐精人行 → 前端展示字段。不再负责从库里取数。"""

from __future__ import annotations

from datetime import date


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


def _val(row, *keys, default: str = "") -> str:
    for key in keys:
        v = row.get(key, "") if hasattr(row, "get") else (
            row[key] if key in getattr(row, "index", []) else ""
        )
        s = str(v) if v is not None else ""
        if s not in ("nan", "NaT", "None", ""):
            return s
    return default


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
    "status",
)


def to_card_donor_info(info: dict) -> dict:
    """从完整展示信息中只保留公开卡片字段。"""
    return {k: info.get(k) for k in CARD_DONOR_KEYS}


def get_donor_display_info(row) -> dict:
    """提取用于前端展示的捐精人信息。同时认中文列名和库列名。"""
    data = row

    def g(*keys, default=""):
        return _val(data, *keys, default=default)

    hobby_pairs = [
        (("爱好运动", "hobby_sports"), "运动健身"),
        (("爱好艺术", "hobby_arts"), "文化艺术"),
        (("爱好休闲", "hobby_leisure"), "休闲娱乐"),
        (("爱好旅游", "hobby_travel"), "旅游度假"),
        (("爱好阅读", "hobby_reading"), "小说书籍"),
        (("爱好美食", "hobby_food"), "美食饮品"),
    ]
    hobby_parts: list[str] = []
    for keys, label in hobby_pairs:
        v = g(*keys)
        if v == "有":
            hobby_parts.append(label)
        elif v and v not in ("无",):
            hobby_parts.append(f"{label}·{v}")
    single_hobby = g("爱好", "hobby")
    hobby = "；".join(hobby_parts) if hobby_parts else single_hobby

    height = g("身高", "height_cm", "height") or 0
    weight = g("体重", "weight_kg", "weight") or 0
    bmi = g("BMI", "体征指数", "bmi") or 0
    specimen = g("标本数量", "specimen_count") or 0
    birth = None
    if hasattr(data, "get"):
        birth = data.get("出生日期") or data.get("birth_date")

    return {
        "id": g("编号", "id") or g("代号", "code"),
        "code": g("代号", "code"),
        "blood_type": g("ABO血型", "血型", "abo_blood"),
        "rh_blood": g("Rh血型", "RH血型", "rh_blood"),
        "ethnicity": g("民族", "ethnicity"),
        "height": int(float(height or 0)),
        "age": _calc_age(birth),
        "constellation": g("星座", "constellation"),
        "hometown": g("籍贯", "hometown"),
        "occupation": g("职业", "occupation"),
        "education": g("学历", "education"),
        "face_shape": g("脸型", "face_shape"),
        "eyelid": g("眼皮", "eyelid"),
        "skin_color": g("肤色", "skin_color"),
        "lip_shape": g("唇型", "唇形", "lip_shape"),
        "nose_bridge": g("鼻梁", "nose_bridge"),
        "hair_color": g("发色", "头发颜色", "hair_color"),
        "hair_style": g("发型", "hair_style"),
        "hair_volume": g("发量", "hair_volume"),
        "beard": g("络腮胡", "络腓胡", "sideburns"),
        "mustache": g("胡须", "mustache"),
        "figure": g("体型", "figure"),
        "weight": _float_safe(weight),
        "bmi": _float_safe(bmi),
        "personality": g("性格", "personality"),
        "hobby": hobby,
        "hobby_sports": g("爱好运动", "hobby_sports"),
        "hobby_arts": g("爱好艺术", "hobby_arts"),
        "hobby_leisure": g("爱好休闲", "hobby_leisure"),
        "hobby_travel": g("爱好旅游", "hobby_travel"),
        "hobby_reading": g("爱好阅读", "hobby_reading"),
        "hobby_food": g("爱好美食", "hobby_food"),
        "drink_history": g("喝酒史", "drink_history"),
        "smoke_history": g("吸烟史", "smoke_history"),
        "personal_disease": g("个人病史", "personal_disease"),
        "present_illness": g("现病史", "present_illness"),
        "past_illness": g("既往病史", "past_illness"),
        "surgery_history": g("手术史", "surgery_history"),
        "personal_life_hist": g("个人生活史", "personal_life_hist"),
        "partners_6m": g("性伴侣数", "partners_6m"),
        "std_history": g("性传播疾病史", "std_history"),
        "marital_fertility": g("婚育史", "marital_fertility"),
        "marriage_age": g("结婚年龄", "marriage_age"),
        "children_info": g("生育子女", "children_info"),
        "genetic_history": g("遗传病史", "genetic_history"),
        "chromosome_disease": g("染色体病", "chromosome_disease"),
        "monogenic_disease": g("单基因遗传病", "monogenic_disease"),
        "polygenic_disease": g("多基因遗传病", "polygenic_disease"),
        "consanguinity": g("近亲婚配", "consanguinity"),
        "specimen_count": int(float(specimen or 0)),
        "status": g("状态", "status") or "active",
    }
