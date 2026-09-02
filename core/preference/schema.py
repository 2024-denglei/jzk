from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["range", "enum", "keyword"]
Constraint = Literal["must", "prefer"]


@dataclass(frozen=True)
class FieldSpec:
    kind: Kind
    db_column: str
    enums: tuple[str, ...] = ()
    sigma: float = 0.0
    ordered_ranks: dict[str, int] | None = None


# 枚举必须与 donor.donors 当前实际取值对齐；禁止写入库中不存在的值。
EDUCATION_ENUM = ("大专", "本科", "硕士", "博士")
ABO_ENUM = ("A", "B", "O", "AB")
RH_ENUM = ("阳性", "阴性")
FIGURE_ENUM = ("一般", "瘦弱", "强壮", "肥胖")
SKIN_ENUM = ("偏白", "一般", "偏黑")
FACE_ENUM = ("长方", "长", "椭圆", "瓜子")
EYELID_ENUM = ("单", "双")
LIP_ENUM = ("一般", "厚", "薄")
CONST_ENUM = (
    "白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
    "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
)

KEYWORD_FIELDS = (
    "ethnicity", "hometown", "occupation", "personality",
    "hair_color", "hair_style", "hair_volume", "nose_bridge",
    "sideburns", "mustache",
    "hobby_sports", "hobby_arts", "hobby_leisure", "hobby_travel",
    "hobby_reading", "hobby_food",
    "drink_history", "smoke_history",
    "personal_disease", "present_illness", "past_illness", "surgery_history",
    "personal_life_hist", "partners_6m", "std_history",
    "marital_fertility", "marriage_age", "children_info",
    "genetic_history", "chromosome_disease", "monogenic_disease",
    "polygenic_disease", "consanguinity",
)

FIELD_REGISTRY: dict[str, FieldSpec] = {
    "height_cm": FieldSpec("range", "height_cm", sigma=10),
    "weight_kg": FieldSpec("range", "weight_kg", sigma=8),
    "bmi": FieldSpec("range", "bmi", sigma=3),
    "age": FieldSpec("range", "birth_date", sigma=5),
    "specimen_count": FieldSpec("range", "specimen_count", sigma=3),
    "education": FieldSpec(
        "enum", "education", enums=EDUCATION_ENUM,
        ordered_ranks={"大专": 1, "本科": 2, "硕士": 3, "博士": 4},
    ),
    "abo_blood": FieldSpec("enum", "abo_blood", enums=ABO_ENUM),
    "rh_blood": FieldSpec("enum", "rh_blood", enums=RH_ENUM),
    "figure": FieldSpec("enum", "figure", enums=FIGURE_ENUM),
    "skin_color": FieldSpec(
        "enum", "skin_color", enums=SKIN_ENUM,
        ordered_ranks={"偏黑": 1, "一般": 2, "偏白": 3},
    ),
    "face_shape": FieldSpec("enum", "face_shape", enums=FACE_ENUM),
    "eyelid": FieldSpec("enum", "eyelid", enums=EYELID_ENUM),
    "lip_shape": FieldSpec("enum", "lip_shape", enums=LIP_ENUM),
    "constellation": FieldSpec("enum", "constellation", enums=CONST_ENUM),
}
for _name in KEYWORD_FIELDS:
    FIELD_REGISTRY[_name] = FieldSpec("keyword", _name)

BLOCKED_FIELDS = frozenset({
    "code", "serial_no", "status",
})

# 给模型看的中文说明；取值来自 FIELD_REGISTRY，不在这里另维护一份枚举。
FIELD_GUIDE: dict[str, str] = {
    "height_cm": "身高（cm）。175 以上 → range.min=175, range.max=null；170–180 → min=170,max=180",
    "weight_kg": "体重（kg）。70kg 以下 → range.max=70；60–70 → min=60,max=70",
    "bmi": "BMI。单边或区间，写法同身高",
    "age": "年龄（周岁，由出生日期计算）。30 岁以下 → range.max=30",
    "specimen_count": "冻存标本管数。至少 5 管 → range.min=5",
    "education": "学历。「学历高/成绩好」→本科及以上（本科/硕士/博士）",
    "abo_blood": "ABO 血型，不要写「型」字",
    "rh_blood": "Rh 血型，用「阳性/阴性」不要用 +/-",
    "figure": "体型。口语映射：瘦/偏瘦/瘦点/苗条→瘦弱；胖/偏胖→肥胖；壮/精壮→强壮；匀称/标准/正常→一般。禁止编造偏瘦型/匀称型/精壮型",
    "skin_color": "肤色。「白皙」→偏白，「正常」→一般",
    "face_shape": "脸型。仅长方/长/椭圆/瓜子；圆脸→椭圆，方脸→长方",
    "eyelid": "眼皮。「双眼皮」→双，「单眼皮」→单。禁止写内双",
    "lip_shape": "唇型。厚唇→厚，薄唇/适中→薄/一般。禁止写厚唇/薄唇/适中字面值",
    "constellation": "星座",
    "ethnicity": "民族，如 汉族",
    "hometown": "籍贯。重庆或四川都可以 → keywords:[重庆,四川], match:any",
    "occupation": "职业",
    "personality": "性格",
    "hair_color": "发色",
    "hair_style": "发型",
    "hair_volume": "发量",
    "nose_bridge": "鼻梁",
    "sideburns": "络腮胡",
    "mustache": "胡须",
    "hobby_sports": "爱好运动，有/无",
    "hobby_arts": "爱好艺术，有/无",
    "hobby_leisure": "爱好休闲，有/无",
    "hobby_travel": "爱好旅游，有/无",
    "hobby_reading": "爱好阅读，有/无",
    "hobby_food": "爱好美食，有/无",
    "drink_history": "喝酒史。不喝酒 → keywords:[无]",
    "smoke_history": "吸烟史。不抽烟/无吸烟史 → keywords:[无] 或 [不吸]，match:any",
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
}


def field_short_label(name: str) -> str:
    """卡片/顾问话术用的短名。"""
    raw = FIELD_GUIDE.get(name, name)
    return raw.split("。")[0].split("（")[0].strip() or name


def field_catalog_text() -> str:
    """从注册表生成字段说明书，供系统提示使用。"""
    lines = ["【可填字段 catalog】未提到的字段不要写进 attributes。"]
    for name, spec in FIELD_REGISTRY.items():
        guide = FIELD_GUIDE.get(name, name)
        if spec.kind == "range":
            lines.append(f"- {name}（数值 range）：{guide}")
        elif spec.kind == "enum":
            allowed = "、".join(spec.enums)
            lines.append(f"- {name}（枚举 values）：{guide}。可选值：{allowed}")
        else:
            lines.append(f"- {name}（关键词 keywords）：{guide}")
    lines.append(f"禁止字段（不可出现）：{', '.join(sorted(BLOCKED_FIELDS))}")
    return "\n".join(lines)


class RangeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def at_least_one_bound(self):
        if self.min is None and self.max is None:
            raise ValueError("range.min and range.max cannot both be null")
        return self


class RangeAttr(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint: Constraint
    weight: float = Field(ge=0, le=1)
    range: RangeSpec


class EnumAttr(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint: Constraint
    weight: float = Field(ge=0, le=1)
    values: list[str] = Field(min_length=1)

    def check_enums(self, allowed: tuple[str, ...]) -> None:
        bad = [v for v in self.values if v not in allowed]
        if bad:
            raise ValueError(f"illegal enum values: {bad}")


class KeywordAttr(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint: Constraint
    weight: float = Field(ge=0, le=1)
    keywords: list[str] = Field(min_length=1, max_length=8)
    match: Literal["any", "all"] = "any"

    @field_validator("keywords")
    @classmethod
    def keyword_len(cls, v: list[str]) -> list[str]:
        for k in v:
            if not k or len(k) > 20:
                raise ValueError("each keyword must be 1..20 chars")
        return v


Attr = RangeAttr | EnumAttr | KeywordAttr


class PreferenceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    attributes: dict[str, Attr]


def openai_tool_schema() -> dict[str, Any]:
    """submit_preference_profile 的 parameters：每字段带说明和可选值。"""

    def _base_props() -> dict[str, Any]:
        return {
            "constraint": {
                "type": "string",
                "enum": ["must", "prefer"],
                "description": "must=必须过滤，prefer=只影响排序",
            },
            "weight": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "must 用 1.0；prefer 默认 0.5",
            },
        }

    attr_props: dict[str, Any] = {}
    for name, spec in FIELD_REGISTRY.items():
        guide = FIELD_GUIDE.get(name, name)
        if spec.kind == "range":
            attr_props[name] = {
                "type": "object",
                "description": guide,
                "properties": {
                    **_base_props(),
                    "range": {
                        "type": "object",
                        "description": "至少填 min 或 max，另一侧用 null",
                        "properties": {
                            "min": {"type": ["number", "null"]},
                            "max": {"type": ["number", "null"]},
                        },
                    },
                },
                "required": ["constraint", "weight", "range"],
            }
        elif spec.kind == "enum":
            allowed = list(spec.enums)
            attr_props[name] = {
                "type": "object",
                "description": f"{guide}。values 只能从可选值中选：{allowed}",
                "properties": {
                    **_base_props(),
                    "values": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": allowed},
                        "description": f"可选值：{allowed}",
                    },
                },
                "required": ["constraint", "weight", "values"],
            }
        else:
            attr_props[name] = {
                "type": "object",
                "description": guide,
                "properties": {
                    **_base_props(),
                    "keywords": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "match": {
                        "type": "string",
                        "enum": ["any", "all"],
                        "description": "any=命中任一关键词；all=全部命中",
                    },
                },
                "required": ["constraint", "weight", "keywords"],
            }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "attributes"],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "attributes": {
                "type": "object",
                "description": "完整偏好画像快照。取消的字段不要出现。未提及不要编造。" + field_catalog_text(),
                "properties": attr_props,
                "additionalProperties": False,
            },
        },
    }
