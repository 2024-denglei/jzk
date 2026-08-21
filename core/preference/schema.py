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


EDUCATION_ENUM = ("大专", "本科", "硕士", "博士")
ABO_ENUM = ("A", "B", "O", "AB")
RH_ENUM = ("阳性", "阴性")
FIGURE_ENUM = ("一般", "瘦弱", "强壮", "肥胖", "匀称型", "精壮型", "偏瘦型")
SKIN_ENUM = ("偏白", "一般", "偏黑")
FACE_ENUM = ("长方", "长", "椭圆", "瓜子", "圆", "方", "菱形")
EYELID_ENUM = ("单", "双", "内双")
LIP_ENUM = ("一般", "厚", "薄", "厚唇", "薄唇", "适中")
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
    "polygenic_disease", "consanguinity", "availability",
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
    "code", "serial_no", "status", "semen_test", "blood_test",
    "chromosome_test", "microbio_test", "remark",
})


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
    """submit_preference_profile 的 parameters。attributes 的具体 kind 由 parse_profile 再校验。"""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "attributes"],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "attributes": {
                "type": "object",
                "description": "完整偏好画像。取消的字段不要出现。未提及不要编造。",
            },
        },
    }
