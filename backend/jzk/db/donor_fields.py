"""捐精人字段定义：Excel《文本信息》列 ↔ 数据库列 ↔ 匹配/展示用中文列名。"""

from __future__ import annotations

# 规范化表头关键字 → DB 列（按最长匹配）
HEADER_RULES: list[tuple[str, str]] = [
    ("代号", "code"),
    ("ABO血型", "abo_blood"),
    ("Rh血型", "rh_blood"),
    ("RH血型", "rh_blood"),
    ("血型", "abo_blood"),
    ("民族", "ethnicity"),
    ("籍贯", "hometown"),
    ("学历", "education"),
    ("职业", "occupation"),
    ("出生日期", "birth_date"),
    ("星座", "constellation"),
    ("身高", "height_cm"),
    ("体重", "weight_kg"),
    ("BMI", "bmi"),
    ("体征指数", "bmi"),
    ("体型", "figure"),
    ("脸型", "face_shape"),
    ("肤色", "skin_color"),
    ("发色", "hair_color"),
    ("头发颜色", "hair_color"),
    ("发型", "hair_style"),
    ("发量", "hair_volume"),
    ("眼皮", "eyelid"),
    ("鼻梁", "nose_bridge"),
    ("唇型", "lip_shape"),
    ("唇形", "lip_shape"),
    ("络腮胡", "sideburns"),
    ("络腓胡", "sideburns"),
    ("胡须", "mustache"),
    ("性格", "personality"),
    ("爱好运动健身", "hobby_sports"),
    ("爱好文化艺术", "hobby_arts"),
    ("爱好休闲娱乐", "hobby_leisure"),
    ("爱好旅游度假", "hobby_travel"),
    ("爱好小说书籍", "hobby_reading"),
    ("爱好美食饮品", "hobby_food"),
    ("喝酒史", "drink_history"),
    ("吸烟史", "smoke_history"),
    ("个人病史", "personal_disease"),
    ("现病史", "present_illness"),
    ("既往病史", "past_illness"),
    ("手术史", "surgery_history"),
    ("个人生活史", "personal_life_hist"),
    ("性伴侣", "partners_6m"),
    ("性传播疾病史", "std_history"),
    ("婚育史", "marital_fertility"),
    ("结婚年龄", "marriage_age"),
    ("生育子女", "children_info"),
    ("遗传病史", "genetic_history"),
    ("染色体病", "chromosome_disease"),
    ("单基因遗传病", "monogenic_disease"),
    ("多基因遗传病", "polygenic_disease"),
    ("近亲婚配", "consanguinity"),
    ("编号", "serial_no"),
    ("标本数量", "specimen_count"),
]


def normalize_excel_header(name: str) -> str:
    s = str(name).replace("\n", "").replace("\r", "")
    s = "".join(s.split())
    return s


def resolve_header_to_db(header: str) -> str | None:
    norm = normalize_excel_header(header)
    if not norm or norm.lower() == "nan":
        return None
    # 爱好六类优先
    if norm.startswith("爱好"):
        for token, db in [
            ("运动", "hobby_sports"),
            ("文化", "hobby_arts"),
            ("休闲", "hobby_leisure"),
            ("旅游", "hobby_travel"),
            ("小说", "hobby_reading"),
            ("美食", "hobby_food"),
        ]:
            if token in norm:
                return db
        return "hobby_sports"
    # 按规则最长前缀/包含匹配
    best: tuple[int, str] | None = None
    for key, db in HEADER_RULES:
        if norm == key or norm.startswith(key):
            score = len(key)
            if best is None or score > best[0]:
                best = (score, db)
    if best:
        return best[1]
    return None


def map_excel_columns(columns: list) -> dict[str, str]:
    """原始 Excel 列名 → DB 列名。"""
    mapping: dict[str, str] = {}
    for col in columns:
        db = resolve_header_to_db(str(col))
        if db:
            mapping[str(col)] = db
    return mapping


# DB → 匹配引擎使用的中文列名（DataFrame）
DB_TO_MATCH_CN: dict[str, str] = {
    "serial_no": "编号",
    "code": "代号",
    "abo_blood": "ABO血型",
    "rh_blood": "Rh血型",
    "ethnicity": "民族",
    "hometown": "籍贯",
    "education": "学历",
    "occupation": "职业",
    "birth_date": "出生日期",
    "constellation": "星座",
    "height_cm": "身高",
    "weight_kg": "体重",
    "bmi": "BMI",
    "figure": "体型",
    "face_shape": "脸型",
    "skin_color": "肤色",
    "hair_color": "发色",
    "hair_style": "发型",
    "hair_volume": "发量",
    "eyelid": "眼皮",
    "nose_bridge": "鼻梁",
    "lip_shape": "唇型",
    "sideburns": "络腮胡",
    "mustache": "胡须",
    "personality": "性格",
    "hobby_sports": "爱好运动",
    "hobby_arts": "爱好艺术",
    "hobby_leisure": "爱好休闲",
    "hobby_travel": "爱好旅游",
    "hobby_reading": "爱好阅读",
    "hobby_food": "爱好美食",
    "drink_history": "喝酒史",
    "smoke_history": "吸烟史",
    "personal_disease": "个人病史",
    "present_illness": "现病史",
    "past_illness": "既往病史",
    "surgery_history": "手术史",
    "personal_life_hist": "个人生活史",
    "partners_6m": "性伴侣数",
    "std_history": "性传播疾病史",
    "marital_fertility": "婚育史",
    "marriage_age": "结婚年龄",
    "children_info": "生育子女",
    "genetic_history": "遗传病史",
    "chromosome_disease": "染色体病",
    "monogenic_disease": "单基因遗传病",
    "polygenic_disease": "多基因遗传病",
    "consanguinity": "近亲婚配",
    "status": "状态",
    "specimen_count": "标本数量",
}

DONOR_DB_COLUMNS = [
    "serial_no",
    "code",
    "abo_blood",
    "rh_blood",
    "ethnicity",
    "hometown",
    "education",
    "occupation",
    "birth_date",
    "constellation",
    "height_cm",
    "weight_kg",
    "bmi",
    "figure",
    "face_shape",
    "skin_color",
    "hair_color",
    "hair_style",
    "hair_volume",
    "eyelid",
    "nose_bridge",
    "lip_shape",
    "sideburns",
    "mustache",
    "personality",
    "hobby_sports",
    "hobby_arts",
    "hobby_leisure",
    "hobby_travel",
    "hobby_reading",
    "hobby_food",
    "drink_history",
    "smoke_history",
    "personal_disease",
    "present_illness",
    "past_illness",
    "surgery_history",
    "personal_life_hist",
    "partners_6m",
    "std_history",
    "marital_fertility",
    "marriage_age",
    "children_info",
    "genetic_history",
    "chromosome_disease",
    "monogenic_disease",
    "polygenic_disease",
    "consanguinity",
    "status",
    "specimen_count",
]
