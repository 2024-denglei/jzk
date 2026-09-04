# Preference Profile Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对话每轮输出一份合法 PreferenceProfile，后台用参数化 SQL 做 must 硬过滤，再用字段加权打分排序；同一接口留给以后的训练模型。

**Architecture:** 新包 `core/preference/` 作为唯一匹配契约：`parse_profile` 校验 → `build_hard_filter_sql` 生成 WHERE → `HeuristicRanker.score` 打分。`dialogue/agent_tools.py` 用工具 `submit_preference_profile` 替换 `match_donors`。`/api/search` 不改。

**Tech Stack:** Python 3.13, Pydantic v2, pytest, PostgreSQL/psycopg, FastAPI, OpenAI tool calling

**Spec:** `docs/superpowers/specs/2026-08-21-preference-profile-matching-design.md`

---

## File map

| File | Responsibility |
|---|---|
| `core/preference/schema.py` | 字段注册表、枚举、σ、Pydantic 属性模型、OpenAI tool JSON |
| `core/preference/validate.py` | `parse_profile` / `ProfileValidationError` |
| `core/preference/sql_filter.py` | must → 参数化 SQL；关键词转义；瓶颈诊断 SQL |
| `core/preference/scorer.py` | 分项分、加权总分、`HeuristicRanker` |
| `core/preference/pipeline.py` | 校验后过滤+排序+组装前端候选人 |
| `core/preference/match_log.py` | turn JSONL + 反馈事件 JSONL |
| `core/preference/__init__.py` | 导出公开 API |
| `tests/preference/*.py` | 先写失败测试 |
| `dialogue/agent_tools.py` | 新工具与 `run_preference_match` |
| `dialogue/session.py` | 存完整 `preference_profile` |
| `api/chat_stream.py` | 调用新工具 |
| `api/feedback.py` | 反馈写入训练日志 |
| `requirements.txt` | 增加 pytest |

不修改 `api/search.py`、`core/matcher.py` 的筛选路径。

---

### Task 1: pytest 与 PreferenceProfile 校验

**Files:**
- Create: `pytest.ini`
- Modify: `requirements.txt`
- Create: `core/preference/__init__.py`
- Create: `core/preference/schema.py`
- Create: `core/preference/validate.py`
- Test: `tests/preference/test_validate.py`

- [ ] **Step 1: 加入 pytest**

在 `requirements.txt` 末尾追加：

```
pytest>=8.0.0
```

创建 `pytest.ini`：

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Run: `.venv\Scripts\python.exe -m pip install pytest>=8.0.0`
Expected: pytest installed

- [ ] **Step 2: 写失败测试**

创建 `tests/preference/test_validate.py`：

```python
import pytest

from core.preference.validate import ProfileValidationError, parse_profile


def test_valid_example_profile_parses():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "height_cm": {
                "constraint": "prefer",
                "weight": 0.9,
                "range": {"min": 175, "max": None},
            },
            "education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]},
            "smoke_history": {
                "constraint": "must",
                "weight": 1.0,
                "keywords": ["无", "不吸"],
                "match": "any",
            },
        },
    }
    p = parse_profile(raw)
    assert p.schema_version == "1.0"
    assert p.attributes["abo_blood"].constraint == "must"
    assert p.attributes["height_cm"].range.min == 175
    assert p.attributes["smoke_history"].keywords == ["无", "不吸"]


def test_rejects_unknown_field():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "code": {"constraint": "must", "weight": 1.0, "keywords": ["D1"], "match": "any"},
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_illegal_enum():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "education": {"constraint": "prefer", "weight": 0.5, "values": ["小学"]},
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_empty_range():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {
                "constraint": "must",
                "weight": 1.0,
                "range": {"min": None, "max": None},
            },
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_all_zero_weights():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 0, "values": ["O"]},
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_rejects_range_payload_on_enum_field():
    raw = {
        "schema_version": "1.0",
        "attributes": {
            "education": {
                "constraint": "prefer",
                "weight": 0.5,
                "range": {"min": 1, "max": 2},
            },
        },
    }
    with pytest.raises(ProfileValidationError):
        parse_profile(raw)


def test_empty_attributes_ok():
    p = parse_profile({"schema_version": "1.0", "attributes": {}})
    assert p.attributes == {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: core.preference`

- [ ] **Step 4: 实现 schema 与 parse_profile**

`core/preference/__init__.py`：

```python
from core.preference.validate import ProfileValidationError, parse_profile

__all__ = ["parse_profile", "ProfileValidationError"]
```

`core/preference/schema.py` 必须包含规格中的全部字段。完整内容：

```python
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
```

`core/preference/validate.py`：

```python
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from core.preference.schema import (
    BLOCKED_FIELDS,
    FIELD_REGISTRY,
    EnumAttr,
    KeywordAttr,
    PreferenceProfile,
    RangeAttr,
)

__all__ = ["ProfileValidationError", "parse_profile", "PreferenceProfile"]


class ProfileValidationError(ValueError):
    pass


def parse_profile(raw: dict[str, Any]) -> PreferenceProfile:
    if not isinstance(raw, dict):
        raise ProfileValidationError("profile must be an object")
    try:
        version = raw.get("schema_version")
        attrs_in = raw.get("attributes")
        if version != "1.0":
            raise ProfileValidationError("schema_version must be 1.0")
        if not isinstance(attrs_in, dict):
            raise ProfileValidationError("attributes must be an object")
        parsed: dict[str, RangeAttr | EnumAttr | KeywordAttr] = {}
        for name, payload in attrs_in.items():
            if name in BLOCKED_FIELDS or name not in FIELD_REGISTRY:
                raise ProfileValidationError(f"unknown or blocked field: {name}")
            if not isinstance(payload, dict):
                raise ProfileValidationError(f"{name} must be an object")
            spec = FIELD_REGISTRY[name]
            if spec.kind == "range":
                attr = RangeAttr.model_validate(payload)
            elif spec.kind == "enum":
                attr = EnumAttr.model_validate(payload)
                attr.check_enums(spec.enums)
            else:
                attr = KeywordAttr.model_validate(payload)
            parsed[name] = attr
        profile = PreferenceProfile(schema_version="1.0", attributes=parsed)
    except (ValidationError, ValueError) as e:
        if isinstance(e, ProfileValidationError):
            raise
        raise ProfileValidationError(str(e)) from e
    if profile.attributes:
        if all(a.weight == 0 for a in profile.attributes.values()):
            raise ProfileValidationError("all weights are 0")
    return profile
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_validate.py -v`
Expected: PASS 7 tests

- [ ] **Step 6: Commit**

```bash
git add pytest.ini requirements.txt core/preference/__init__.py core/preference/schema.py core/preference/validate.py tests/preference/test_validate.py
git commit -m "feat: add PreferenceProfile schema validation"
```

---

### Task 2: 字段打分（range / enum / keyword）

**Files:**
- Create: `core/preference/scorer.py`
- Test: `tests/preference/test_scorer.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import date, timedelta

from core.preference.scorer import score_field
from core.preference.validate import parse_profile


def _attr(field, payload):
    p = parse_profile({"schema_version": "1.0", "attributes": {field: payload}})
    return p.attributes[field]


def test_height_min_only_order():
    attr = _attr("height_cm", {"constraint": "must", "weight": 1, "range": {"min": 175}})
    s185 = score_field("height_cm", attr, {"height_cm": 185})
    s180 = score_field("height_cm", attr, {"height_cm": 180})
    s175 = score_field("height_cm", attr, {"height_cm": 175})
    s170 = score_field("height_cm", attr, {"height_cm": 170})
    assert s185 > s180 > s175 > s170
    assert abs(s175 - 0.8) < 1e-6
    assert abs(s185 - 1.0) < 1e-6


def test_education_symmetric_distance():
    attr = _attr("education", {"constraint": "prefer", "weight": 1, "values": ["硕士"]})
    s_m = score_field("education", attr, {"education": "硕士"})
    s_d = score_field("education", attr, {"education": "博士"})
    s_b = score_field("education", attr, {"education": "本科"})
    s_c = score_field("education", attr, {"education": "大专"})
    assert s_m > s_d
    assert abs(s_d - s_b) < 1e-6
    assert s_b > s_c


def test_abo_hit_or_miss():
    attr = _attr("abo_blood", {"constraint": "must", "weight": 1, "values": ["O"]})
    assert score_field("abo_blood", attr, {"abo_blood": "O"}) == 1.0
    assert score_field("abo_blood", attr, {"abo_blood": "A"}) == 0.0


def test_keyword_any():
    attr = _attr(
        "smoke_history",
        {"constraint": "must", "weight": 1, "keywords": ["无", "不吸"], "match": "any"},
    )
    assert score_field("smoke_history", attr, {"smoke_history": "无吸烟史"}) == 1.0
    assert score_field("smoke_history", attr, {"smoke_history": "偶尔吸烟"}) == 0.0


def test_rh_normalize_plus():
    attr = _attr("rh_blood", {"constraint": "must", "weight": 1, "values": ["阳性"]})
    assert score_field("rh_blood", attr, {"rh_blood": "+"}) == 1.0


def test_age_from_birth_date():
    attr = _attr("age", {"constraint": "prefer", "weight": 1, "range": {"min": 20, "max": 30}})
    born = date.today() - timedelta(days=365 * 25 + 10)
    s = score_field("age", attr, {"birth_date": born.isoformat()})
    assert s == 1.0


def test_null_prefer_is_zero():
    attr = _attr("hometown", {"constraint": "prefer", "weight": 0.5, "keywords": ["四川"]})
    assert score_field("hometown", attr, {"hometown": None}) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_scorer.py -v`
Expected: FAIL `ModuleNotFoundError: core.preference.scorer`

- [ ] **Step 3: 实现 scorer.py 中的 score_field / normalize_rh / donor_age**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
```

先把 `HeuristicRanker` 留到 Task 3，本任务只实现 `score_field` 及相关辅助函数。

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/preference/scorer.py tests/preference/test_scorer.py
git commit -m "feat: add per-field preference scores"
```

---

### Task 3: 加权总分与 HeuristicRanker

**Files:**
- Modify: `core/preference/scorer.py`
- Modify: `tests/preference/test_scorer.py`

- [ ] **Step 1: 追加失败测试**

```python
from core.preference.scorer import HeuristicRanker
from core.preference.validate import parse_profile


def test_weighted_average_and_tie_break_specimen():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
            "height_cm": {"constraint": "prefer", "weight": 0.9, "range": {"min": 175}},
        },
    })
    ranker = HeuristicRanker()
    a = {"abo_blood": "O", "height_cm": 185, "specimen_count": 1, "code": "A"}
    b = {"abo_blood": "O", "height_cm": 175, "specimen_count": 9, "code": "B"}
    sa, _ = ranker.score(profile, a)
    sb, _ = ranker.score(profile, b)
    assert sa > sb
    ranked = ranker.rank(profile, [b, a])
    assert ranked[0][0]["code"] == "A"


def test_same_score_higher_specimen_first():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
        },
    })
    ranker = HeuristicRanker()
    low = {"abo_blood": "O", "specimen_count": 1, "code": "L"}
    high = {"abo_blood": "O", "specimen_count": 8, "code": "H"}
    ranked = ranker.rank(profile, [low, high])
    assert ranked[0][0]["code"] == "H"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_scorer.py::test_weighted_average_and_tie_break_specimen -v`
Expected: FAIL `HeuristicRanker` 未定义

- [ ] **Step 3: 在 scorer.py 追加**

```python
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
                target = {"min": attr.range.min, "max": attr.range.max}
                actual = donor_numeric(field, row)
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
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/preference/scorer.py tests/preference/test_scorer.py
git commit -m "feat: add weighted HeuristicRanker"
```

---

### Task 4: 参数化 SQL 硬过滤

**Files:**
- Create: `core/preference/sql_filter.py`
- Test: `tests/preference/test_sql_filter.py`

- [ ] **Step 1: 写失败测试（不连数据库，只断言 SQL 文本与参数）**

```python
from core.preference.sql_filter import build_hard_filter_sql, escape_like
from core.preference.validate import parse_profile


def test_prefer_height_not_in_where():
    p = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {"constraint": "prefer", "weight": 0.9, "range": {"min": 175}},
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
        },
    })
    sql, params = build_hard_filter_sql(p)
    assert "height_cm" not in sql
    assert "abo_blood" in sql
    assert "status" in sql and "active" in sql
    assert "O" in params


def test_must_height_in_where():
    p = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {"constraint": "must", "weight": 1.0, "range": {"min": 175}},
        },
    })
    sql, params = build_hard_filter_sql(p)
    assert "height_cm >=" in sql.replace("  ", " ")
    assert 175 in params


def test_keyword_percent_escaped():
    assert "%" in escape_like("100%")
    p = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "occupation": {
                "constraint": "must",
                "weight": 1.0,
                "keywords": ["100%"],
                "match": "any",
            },
        },
    })
    sql, params = build_hard_filter_sql(p)
    assert "ILIKE" in sql.upper()
    assert "ESCAPE" in sql.upper()
    assert "%" + escape_like("100%") + "%" in params


def test_no_must_only_active():
    p = parse_profile({"schema_version": "1.0", "attributes": {
        "education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]},
    }})
    sql, params = build_hard_filter_sql(p)
    assert "education" not in sql
    assert params == () or "active" in params
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_sql_filter.py -v`
Expected: FAIL missing `sql_filter`

- [ ] **Step 3: 实现 sql_filter.py**

```python
from __future__ import annotations

from core.preference.schema import FIELD_REGISTRY, EnumAttr, KeywordAttr, RangeAttr
from core.preference.validate import PreferenceProfile


def escape_like(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _age_sql() -> str:
    return "(EXTRACT(YEAR FROM AGE(CURRENT_DATE, birth_date)))"


def build_hard_filter_sql(profile: PreferenceProfile) -> tuple[str, tuple]:
    clauses = ["status = %s"]
    params: list = ["active"]
    for field, attr in profile.attributes.items():
        if attr.constraint != "must":
            continue
        spec = FIELD_REGISTRY[field]
        if isinstance(attr, RangeAttr):
            col = _age_sql() if field == "age" else spec.db_column
            if attr.range.min is not None:
                clauses.append(f"{col} >= %s")
                params.append(attr.range.min)
            if attr.range.max is not None:
                clauses.append(f"{col} <= %s")
                params.append(attr.range.max)
        elif isinstance(attr, EnumAttr):
            if field == "rh_blood":
                col = "CASE WHEN rh_blood IN ('+', '阳性') THEN '阳性' WHEN rh_blood IN ('-', '阴性') THEN '阴性' ELSE rh_blood END"
            else:
                col = spec.db_column
            placeholders = ", ".join(["%s"] * len(attr.values))
            clauses.append(f"{col} IN ({placeholders})")
            params.extend(attr.values)
        elif isinstance(attr, KeywordAttr):
            likes = []
            for kw in attr.keywords:
                likes.append(f"{spec.db_column} ILIKE %s ESCAPE '\\'")
                params.append("%" + escape_like(kw) + "%")
            joiner = " AND " if attr.match == "all" else " OR "
            clauses.append("(" + joiner.join(likes) + ")")
    sql = "SELECT * FROM donor.donors WHERE " + " AND ".join(clauses)
    return sql, tuple(params)
```

注意：`test_prefer_height_not_in_where` 里 `assert 175 not in params` 已由「SQL 不含 height_cm」覆盖。`test_no_must_only_active` 的 params 为 `("active",)`。

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_sql_filter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/preference/sql_filter.py tests/preference/test_sql_filter.py
git commit -m "feat: build parameterized SQL from must constraints"
```

---

### Task 5: 瓶颈诊断（0 人时不放宽）

**Files:**
- Modify: `core/preference/sql_filter.py`
- Modify: `tests/preference/test_sql_filter.py`

- [ ] **Step 1: 写失败测试**

```python
from core.preference.sql_filter import diagnose_bottlenecks
from core.preference.validate import parse_profile


def test_bottleneck_orders_by_recovered_count():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            "rh_blood": {"constraint": "must", "weight": 1, "values": ["阴性"]},
        },
    })

    def fake_count(sql, params):
        # 去掉 rh 能恢复更多人
        if "阴性" in params:
            return 0
        if "O" in params:
            return 10
        return 100

    out = diagnose_bottlenecks(profile, fake_count)
    assert out[0]["field"] == "rh_blood"
    assert out[0]["recovered"] == 10
    assert out[1]["field"] == "abo_blood"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_sql_filter.py::test_bottleneck_orders_by_recovered_count -v`
Expected: FAIL `diagnose_bottlenecks` 未定义

- [ ] **Step 3: 实现**

在 `sql_filter.py` 增加：把某个 must 字段临时改成 prefer，再 `build_hard_filter_sql`，用注入的 `count_fn(sql, params) -> int` 计数。

```python
from copy import deepcopy


def diagnose_bottlenecks(profile: PreferenceProfile, count_fn) -> list[dict]:
    must_fields = [f for f, a in profile.attributes.items() if a.constraint == "must"]
    results = []
    for field in must_fields:
        clone = profile.model_copy(deep=True)
        clone.attributes[field].constraint = "prefer"
        sql, params = build_hard_filter_sql(clone)
        recovered = int(count_fn(sql, params))
        results.append({"field": field, "recovered": recovered})
    results.sort(key=lambda x: x["recovered"], reverse=True)
    return results
```

`PreferenceProfile` 来自 `schema.py`；`validate.py` 已导出它的话，测试里的 import 可继续用 `validate`。若 `model_copy` 后 constraint 赋值需要 attr 可变：Pydantic 模型默认可变。

把 `PreferenceProfile` 从 `schema.py` 在 `validate.py` 再导出：

```python
from core.preference.schema import PreferenceProfile
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_sql_filter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/preference/sql_filter.py core/preference/validate.py tests/preference/test_sql_filter.py
git commit -m "feat: diagnose must-filter bottlenecks without auto-relax"
```

---

### Task 6: 匹配流水线（过滤 + 排序 + 前端结构）

**Files:**
- Create: `core/preference/pipeline.py`
- Test: `tests/preference/test_pipeline.py`

- [ ] **Step 1: 写失败测试（注入 fetch，不连真实库）**

```python
from core.preference.pipeline import match_profile
from core.preference.validate import parse_profile


def test_empty_attributes_does_not_query():
    called = []
    profile = parse_profile({"schema_version": "1.0", "attributes": {}})
    result = match_profile(profile, fetch_rows=lambda s, p: called.append((s, p)) or [])
    assert result.candidates == []
    assert result.skipped is True
    assert called == []


def test_zero_rows_returns_bottlenecks_not_relaxed():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
        },
    })
    result = match_profile(
        profile,
        fetch_rows=lambda s, p: [],
        count_rows=lambda s, p: 0,
    )
    assert result.candidates == []
    assert result.match_level == "none"
    assert result.bottlenecks


def test_ranks_by_score():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
        },
    })
    rows = [
        {"code": "S", "abo_blood": "O", "height_cm": 175, "specimen_count": 3, "status": "active"},
        {"code": "T", "abo_blood": "O", "height_cm": 185, "specimen_count": 3, "status": "active"},
    ]
    result = match_profile(profile, fetch_rows=lambda s, p: rows)
    assert result.candidates[0]["donor_info"]["code"] == "T"
    assert result.candidates[0]["score"] > result.candidates[1]["score"]
    assert "field_scores" in result.candidates[0]
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_pipeline.py -v`
Expected: FAIL missing pipeline

- [ ] **Step 3: 实现 pipeline.py**

`MatchResult` 含 `candidates`、`match_level`（`full` | `none`）、`bottlenecks`、`skipped`、`filtered_count`。

`match_profile(profile, fetch_rows=None, count_rows=None, ranker=None)`：

- `attributes` 为空：`skipped=True`，不调用 `fetch_rows`
- 默认 `fetch_rows`：`db.pg.db_session` + `fetchall`
- 默认 `count_rows`：把 `SELECT *` 换成 `SELECT COUNT(*) AS c`
- 0 行：`diagnose_bottlenecks`，`match_level="none"`，不放宽
- 有行：`HeuristicRanker.rank`，用 `get_donor_display_info` 填 `donor_info`；`score` 四位小数；`field_match` 由 `s >= 1.0` 或 keyword/enum 命中得到 `{match, actual, user}`；`match_pct` 为 `round(100 * mean(s_f), 1)`；`match_level="full"`；`reason` 用命中字段拼一句短中文

默认 `fetch_rows`：

```python
def default_fetch(sql, params):
    from db.pg import db_session, fetchall
    with db_session() as conn:
        return fetchall(conn, sql, params)
```

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/preference/pipeline.py tests/preference/test_pipeline.py
git commit -m "feat: preference matching pipeline without auto-relax"
```

---

### Task 7: 训练日志 JSONL

**Files:**
- Create: `core/preference/match_log.py`
- Modify: `config.py`（增加 `MATCH_LOG_DIR`，默认 `agent/data/match_logs`）
- Test: `tests/preference/test_match_log.py`

- [ ] **Step 1: 写失败测试（用 tmp_path）**

```python
import json
from pathlib import Path

from core.preference.match_log import append_feedback_event, append_match_turn


def test_write_turn_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCH_LOG_DIR", str(tmp_path))
    append_match_turn({
        "schema_version": "1.0",
        "session_id": "s1",
        "preference_profile": {"schema_version": "1.0", "attributes": {}},
        "filtered_count": 2,
        "candidates": [{"code": "A", "score": 0.9, "rank": 1, "field_scores": [], "attrs": {}}],
    })
    append_feedback_event({
        "session_id": "s1",
        "donor_code": "A",
        "event": "like",
    })
    turns = (tmp_path / "turns.jsonl").read_text(encoding="utf-8").strip().splitlines()
    events = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(turns[0])["session_id"] == "s1"
    assert "semen_test" not in turns[0]
    assert json.loads(events[0])["event"] == "like"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_match_log.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`config.py` 增加：

```python
MATCH_LOG_DIR = os.getenv(
    "MATCH_LOG_DIR",
    os.path.join(os.path.dirname(__file__), "data", "match_logs"),
)
```

`match_log.py`：确保目录存在；`append_match_turn` / `append_feedback_event` 各写一行 JSON，带 `ts` ISO 时间；禁止写入 `semen_test` 等检测字段（从 attrs 里 pop）。

`pipeline.match_profile` 在成功排序后调用 `append_match_turn`（可用参数 `log=True`，测试里 `log=False` 以免写默认目录）。更新 Task 6 测试保持 `log=False`。

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_match_log.py tests/preference/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/preference/match_log.py core/preference/pipeline.py config.py tests/preference/test_match_log.py
git commit -m "feat: log preference match turns for future ranker training"
```

---

### Task 8: Session 保存完整画像

**Files:**
- Modify: `dialogue/session.py`
- Test: `tests/preference/test_session_profile.py`

- [ ] **Step 1: 写失败测试**

```python
from dialogue.session import SessionContext


def test_replace_profile_is_snapshot_not_merge():
    s = SessionContext()
    s.replace_profile({"schema_version": "1.0", "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}}})
    s.replace_profile({"schema_version": "1.0", "attributes": {"height_cm": {"constraint": "prefer", "weight": 0.5, "range": {"min": 175}}}})
    assert "abo_blood" not in s.preference_profile["attributes"]
    assert "height_cm" in s.preference_profile["attributes"]


def test_checkpoint_includes_profile():
    s = SessionContext()
    s.replace_profile({"schema_version": "1.0", "attributes": {}})
    cp = s.export_checkpoint()
    s.replace_profile({"schema_version": "1.0", "attributes": {"education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]}}})
    s.restore_checkpoint(cp)
    assert s.preference_profile["attributes"] == {}
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_session_profile.py -v`
Expected: FAIL `replace_profile`

- [ ] **Step 3: 实现**

在 `SessionContext.__init__` 增加 `self.preference_profile: dict | None = None`。

```python
def replace_profile(self, profile: dict | None) -> None:
    self.preference_profile = None if profile is None else dict(profile)
```

`export_checkpoint` / `restore_checkpoint` / `apply_rewind` / `to_dict` / `from_dict` 增加 `preference_profile`。非法画像不要在 session 方法里校验；由调用方先 `parse_profile`。

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_session_profile.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dialogue/session.py tests/preference/test_session_profile.py
git commit -m "feat: store full preference profile on session"
```

---

### Task 9: 替换 match_donors 工具

**Files:**
- Modify: `dialogue/agent_tools.py`
- Test: `tests/preference/test_agent_tool.py`

- [ ] **Step 1: 写失败测试**

```python
from dialogue.agent_tools import SUBMIT_PROFILE_TOOL, run_preference_match
from dialogue.session import SessionContext


def test_tool_name_and_schema():
    assert SUBMIT_PROFILE_TOOL["function"]["name"] == "submit_preference_profile"
    params = SUBMIT_PROFILE_TOOL["function"]["parameters"]
    assert "schema_version" in params["properties"]
    assert "attributes" in params["properties"]


def test_invalid_profile_keeps_previous(monkeypatch):
    session = SessionContext()
    good = {"schema_version": "1.0", "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}}}
    session.replace_profile(good)
    candidates, payload = run_preference_match(
        session,
        {"schema_version": "1.0", "attributes": {"code": {"constraint": "must", "weight": 1, "keywords": ["x"]}}},
        fetch_rows=lambda s, p: [],
    )
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert payload["ok"] is False
    assert candidates == []


def test_valid_profile_replaces_and_matches():
    session = SessionContext()
    rows = [{"code": "T", "abo_blood": "O", "height_cm": 180, "specimen_count": 2}]
    candidates, payload = run_preference_match(
        session,
        {
            "schema_version": "1.0",
            "attributes": {
                "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            },
        },
        fetch_rows=lambda s, p: rows,
        log=False,
    )
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert candidates[0]["donor_info"]["code"] == "T"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_agent_tool.py -v`
Expected: FAIL

- [ ] **Step 3: 改 agent_tools.py**

保留文件，大幅替换：

- `SUBMIT_PROFILE_TOOL` 的 `parameters` 使用 `openai_tool_schema()`
- 重写 `AGENT_SYSTEM_PROMPT`：每轮输出完整画像；`must`/`prefer`/`weight`；取消=删除字段；禁止写 SQL、禁止编造捐精人；有条件就调用工具
- `run_preference_match(session, raw_profile, fetch_rows=None, log=True)`：`parse_profile` 失败则 `ok: False` 且不改 session；空 attributes 则 `ok: True, skipped: True` 不查询；成功则 `session.replace_profile(parsed.model_dump())` 再 `match_profile`
- 工具返回给模型的 payload：`ok, count, match_level, bottlenecks, feature_summary, top_preview, note`
- `feature_summary` 用 attributes 拼中文（height_cm → 身高 ≥175cm）
- 删除热路径对 `match_donors` / `remove_fields` 的依赖。`detect_remove_fields` 可留着暂时不调用
- `build_agent_messages` 的上下文改为 dump `session.preference_profile`

`run_match_donors` 改为薄封装调用 `run_preference_match`，避免漏改，或直接删掉并改所有引用（Task 10）。

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest tests/preference/test_agent_tool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dialogue/agent_tools.py tests/preference/test_agent_tool.py
git commit -m "feat: replace match_donors with submit_preference_profile"
```

---

### Task 10: 接入 chat_stream

**Files:**
- Modify: `api/chat_stream.py`
- Modify: `api/chat.py`（欢迎语仍可用；匹配不要走旧 NLU 硬过滤。空 message 保持 get_welcome）

- [ ] **Step 1: 改 chat_stream 工具循环**

把 `MATCH_DONORS_TOOL` 换成 `SUBMIT_PROFILE_TOOL`。

工具名判断改为 `submit_preference_profile`。解析 arguments 后调用：

```python
candidates, payload = run_preference_match(session, args, log=True)
```

非法时 `payload["ok"] is False`，candidates 为空，SSE 仍把错误 JSON 回给模型让它澄清。

SSE 事件里同时返回：

- `preference_profile`: `session.preference_profile or {}`
- `parsed_features`: 为兼容回溯 UI，用 `session.preference_profile["attributes"]`（不要再 merge 旧 features）
- `constraints`: `{field: attr["constraint"] for field, attr in attributes.items()}`

`rewind` 请求体增加可选 `preference_profile`；若提供则 `session.replace_profile`。仍接受旧 `parsed_features` 时忽略，不再还原成旧 matcher 条件。

去掉 `detect_remove_fields` / `normalize_colloquial_features` / `tool_args_to_features` / `session.update_features` 在 stream 路径中的调用。

`run_match_donors` 的引用全部改为 `run_preference_match`。

- [ ] **Step 2: 手工核对**

Run: `.venv\Scripts\python.exe -m pytest tests/preference -v`
Expected: PASS

再搜索：

Run: `rg "match_donors|run_match_donors" --glob "*.py"`
Expected: 无对话热路径命中（`api/search.py` 与 `core/matcher.py` 可保留旧筛选）

- [ ] **Step 3: Commit**

```bash
git add api/chat_stream.py api/chat.py dialogue/agent_tools.py
git commit -m "feat: wire chat stream to preference profile matcher"
```

---

### Task 11: 反馈事件写入训练日志

**Files:**
- Modify: `api/feedback.py`
- Modify: `tests/preference/test_match_log.py` 或 `tests/preference/test_feedback_log.py`

- [ ] **Step 1: 写失败测试**

用 FastAPI 不是必须。直接测：`session.add_feedback` 之后调用的日志函数。更简单：在 `api/feedback.py` 抽出：

```python
def record_feedback(session_id: str, donor_code: str, feedback: str) -> None:
    event = {"like": "like", "dislike": "dislike"}[feedback]
    append_feedback_event({"session_id": session_id, "donor_code": donor_code, "event": event})
```

测试 tmp_path + monkeypatch `MATCH_LOG_DIR`。

- [ ] **Step 2: Run to verify fail / Step 3: 实现 / Step 4: PASS**

`submit_feedback` 在 `session.add_feedback` 之后调用 `record_feedback(session_id, donor_code, feedback)`。

在 `api/user.py` 的 `add_favorite` 成功插入后调用：

```python
append_feedback_event({
    "session_id": "",
    "user_id": user_id,
    "donor_code": code,
    "event": "favorite",
})
```

在 `api/donors.py` 的 `GET /api/donors/{code}` 成功返回前调用 `event: "open_detail"`（`session_id` 可空）。不新建收藏/详情接口。

- [ ] **Step 5: Commit**

```bash
git add api/feedback.py api/user.py tests/preference/test_feedback_log.py
git commit -m "feat: write user feedback events for ranker training"
```

---

### Task 12: 全量回归与规格对照

**Files:** 无新文件，只跑测试并对照 spec。

- [ ] **Step 1: 跑全部 preference 测试**

Run: `.venv\Scripts\python.exe -m pytest tests/preference -v`
Expected: 全部 PASS

- [ ] **Step 2: 对照 spec 清单（全部应为已实现）**

- 完整 PreferenceProfile 快照
- must → SQL，prefer 不进 WHERE
- 加权分 + must 参与排序
- 非法 JSON 沿用上一份画像
- 0 人不自动放宽 + 瓶颈
- 训练 turn + like/dislike 日志
- Ranker 接口可替换
- `/api/search` 未改

- [ ] **Step 3: 若有缺口，补测试与代码后再提交**

```bash
git add -u
git commit -m "test: finish preference matching spec coverage"
```

---

## Self-review

**Spec coverage**

| Spec 节 | Task |
|---|---|
| JSON Schema / 校验 | 1 |
| 三类属性与禁止字段 | 1 |
| Range/enum/keyword 打分公式 | 2 |
| 加权总分、must 参与排序、标本数打平 | 3 |
| 参数化 SQL、prefer 不进 WHERE、LIKE 转义 | 4 |
| 0 人瓶颈、不自动放宽 | 5、6 |
| 空 attributes 不匹配 | 6、9 |
| 流水线 + 前端候选结构 | 6 |
| 训练日志 | 7、11 |
| Session 完整画像 | 8 |
| 替换 match_donors | 9、10 |
| 异常：非法则保留旧画像 | 9、10 |
| `/api/search` 不动 | 未列入修改文件 |

**Type names:** `PreferenceProfile`、`RangeAttr`、`EnumAttr`、`KeywordAttr`、`FieldScore`、`HeuristicRanker`、`parse_profile`、`build_hard_filter_sql`、`match_profile`、`run_preference_match`、`submit_preference_profile` 前后任务一致。
