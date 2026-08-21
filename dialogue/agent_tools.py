"""顾问 Agent 工具：match_donors 及系统提示。"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """你是智能生育匹配系统的顾问助手。

职责：
1. 通过多轮对话理解用户对捐精人各属性的偏好，每轮输出当前完整 PreferenceProfile
2. 有任何仍生效的偏好时，必须调用工具 submit_preference_profile；禁止只说「已记录」却不调用
3. 工具返回后用中文简洁总结；人数必须与工具结果一致，禁止虚构捐精人

【画像规则】
- 每轮提交完整 attributes 快照，不是增量。取消某条件 = 该字段从 attributes 中消失
- 每个出现的字段必须有 constraint（must|prefer）和 weight（0~1）
- 用户说「必须/一定要」→ must 且 weight=1.0；「最好/希望」→ prefer；未说强度时 must=1.0、prefer=0.5
- 数值字段用 range.min/max（height_cm、weight_kg、bmi、age、specimen_count）
- 枚举字段用 values 数组：education/abo_blood/rh_blood/figure/skin_color/face_shape/eyelid/lip_shape/constellation
- 其余文本字段用 keywords + match(any|all)
- 禁止输出 SQL，禁止编造代号和具体捐精人信息
- 闲聊、问候且没有偏好 → 不调用工具
"""

SUBMIT_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_preference_profile",
        "description": "提交当前完整偏好画像并匹配捐精人。每轮有偏好时必须调用；取消的字段不要出现。",
        "parameters": {
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
        },
    },
}

MATCH_DONORS_TOOL = {
    "type": "function",
    "function": {
        "name": "match_donors",
        "description": "根据结构化条件查询匹配捐精人。有可筛选条件时应调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "education": {
                    "type": "string",
                    "description": "学历：大专/本科/硕士/博士",
                },
                "height": {
                    "type": "object",
                    "properties": {
                        "min": {"type": ["number", "null"]},
                        "max": {"type": ["number", "null"]},
                    },
                    "description": "身高 cm，如 175 以上 → {min:175}",
                },
                "age": {
                    "type": "object",
                    "properties": {
                        "min": {"type": ["number", "null"]},
                        "max": {"type": ["number", "null"]},
                    },
                    "description": "年龄，如 30 岁以下 → {max:30}",
                },
                "blood_type": {"type": "string", "description": "A/B/O/AB"},
                "rh_blood": {"type": "string", "description": "阳性/阴性"},
                "figure": {"type": "string", "description": "匀称型/精壮型/偏瘦型"},
                "skin_color": {"type": "string", "description": "偏白/一般"},
                "face_shape": {"type": "string"},
                "eyelid": {"type": "string", "description": "单/双/内双"},
                "appearance": {
                    "type": "string",
                    "description": "形象气质：文艺型/阳光型/成熟型/绅士型。口语「帅/帅气/长得帅」请填阳光型",
                },
                "lip_shape": {"type": "string"},
                "constellation": {"type": "string"},
                "ethnicity": {"type": "string"},
                "hometown": {"type": "string"},
                "occupation": {"type": "string"},
                "personality": {"type": "string"},
                "specimen_min": {"type": "number", "description": "最低标本管数"},
                "remove_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要删除的字段名列表（education/height/age/hometown 等）。"
                        "用户取消某条件时必填，且不要再传该字段的值"
                    ),
                },
                "constraints": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                        "enum": ["must", "prefer"],
                    },
                    "description": "各字段约束强度 must|prefer",
                },
            },
        },
    },
}


_FIELD_KEYWORDS: dict[str, list[str]] = {
    "figure": ["体型", "体形", "身材"],
    "skin_color": ["肤色", "皮肤"],
    "eyelid": ["眼皮", "双眼皮", "单眼皮"],
    "face_shape": ["脸型"],
    "lip_shape": ["唇形", "唇型"],
    "blood_type": ["血型"],
    "constellation": ["星座"],
    "education": ["学历"],
    "hometown": ["籍贯", "老家", "地区"],
    "ethnicity": ["民族"],
    "occupation": ["职业"],
    "personality": ["性格"],
    "height": ["身高"],
    "age": ["年龄"],
    "appearance": ["形象", "气质", "长相"],
    "specimen_min": ["标本"],
    "rh_blood": ["RH", "Rh", "熊猫血"],
}

_REMOVE_KEYWORDS = (
    "不做要求",
    "没有要求",
    "不作为筛选",
    "不用作为",
    "不用筛选",
    "取消",
    "去掉",
    "不用了",
    "不要了",
    "不限",
    "随便",
    "无所谓",
    "不重要",
    "放宽",
    "都可以",
    "都行",
    "不强制",
    "无需",
    "不必",
)


def detect_remove_fields(text: str, current_features: dict | None) -> list[str]:
    """从用户话术识别要删除的字段（LLM 漏填 remove_fields 时的兜底）。"""
    if not text or not current_features:
        return []
    t = text.strip()
    if not any(k in t for k in _REMOVE_KEYWORDS):
        # 「学历不用了 / 身高算了」等短句
        if not any(k in t for k in ("不用", "不要", "算了", "取消", "去掉", "不限")):
            return []
    found: list[str] = []
    for field, keywords in _FIELD_KEYWORDS.items():
        if field not in current_features:
            continue
        if any(kw in t for kw in keywords):
            found.append(field)
    return found


def normalize_colloquial_features(text: str) -> dict[str, Any]:
    """把口语偏好映射为结构化字段（如「长得帅」→ 阳光型）。"""
    features: dict[str, Any] = {}
    if not text:
        return features
    # 取消类话术不要误映射「帅」「白」等
    if any(k in text for k in _REMOVE_KEYWORDS) or any(
        k in text for k in ("不用", "不要", "算了", "取消", "去掉")
    ):
        return features
    t = text.strip()
    if any(k in t for k in ("长得帅", "帅气", "好帅", "阳光帅气")) or (
        "帅" in t and "律师" not in t
    ):
        features["appearance"] = "阳光型"
    elif any(k in t for k in ("儒雅", "斯文", "绅士")):
        features["appearance"] = "绅士型"
    elif any(k in t for k in ("文艺", "温柔气质")):
        features["appearance"] = "文艺型"
    elif any(k in t for k in ("成熟稳重", "成熟型")):
        features["appearance"] = "成熟型"
    if any(k in t for k in ("偏白", "白一点", "肤白", "白皙")):
        features["skin_color"] = "偏白"
    return features


def tool_args_to_features(args: dict[str, Any]) -> tuple[dict, dict, list[str]]:
    """将工具参数拆成 features / constraints / remove_fields。"""
    remove_fields = []
    raw_remove = args.get("remove_fields") or []
    if isinstance(raw_remove, list):
        remove_fields = [f for f in raw_remove if isinstance(f, str)]

    constraints = {}
    raw_c = args.get("constraints") or {}
    if isinstance(raw_c, dict):
        for k, v in raw_c.items():
            if v in ("must", "prefer"):
                constraints[k] = v

    skip = {"remove_fields", "constraints"}
    features: dict[str, Any] = {}
    for k, v in args.items():
        if k in skip or v is None or v == "":
            continue
        # 部分模型会把对象序列化成字符串
        if isinstance(v, str) and v.strip().startswith("{"):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        if k in ("height", "age") and isinstance(v, dict):
            cleaned = {}
            if v.get("min") is not None:
                try:
                    cleaned["min"] = float(v["min"])
                except (TypeError, ValueError):
                    pass
            if v.get("max") is not None:
                try:
                    cleaned["max"] = float(v["max"])
                except (TypeError, ValueError):
                    pass
            if cleaned:
                features[k] = cleaned
                constraints.setdefault(k, "must")
        elif k == "specimen_min":
            try:
                features[k] = float(v)
                constraints.setdefault(k, "must")
            except (TypeError, ValueError):
                pass
        else:
            features[k] = v
            constraints.setdefault(k, "must")
    return features, constraints, remove_fields


def run_match_donors(session, feature_encoder, donor_df) -> tuple[list[dict], str, dict]:
    """执行本地匹配，返回 (candidates, match_level, tool_payload_for_llm)。"""
    from core.matcher import compute_similarity, match_with_relaxation, diagnose_no_match
    from core.ranker import rank_and_explain
    from dialogue.dialogue_flow import build_feature_summary
    from dialogue.session import DialogueState

    query_vec, mask = feature_encoder.encode_query(session.parsed_features)
    scores = compute_similarity(query_vec, feature_encoder.feature_matrix, mask=mask)
    cands, match_level, _relaxed = match_with_relaxation(
        donor_df,
        session.parsed_features,
        scores,
        constraints=session.constraints,
    )
    candidates = rank_and_explain(
        cands, donor_df, session.parsed_features, match_level=match_level
    )

    seen = set()
    unique = []
    for c in candidates:
        code = c["donor_info"].get("code", "")
        if code not in seen:
            seen.add(code)
            unique.append(c)
    candidates = unique
    session.candidates = candidates
    session.state = DialogueState.PRESENTING

    summary = build_feature_summary(session.parsed_features)
    n = len(candidates)
    top = []
    for c in candidates[:5]:
        d = c.get("donor_info") or {}
        top.append(
            {
                "code": d.get("code"),
                "education": d.get("education"),
                "height": d.get("height"),
                "age": d.get("age"),
                "match_pct": c.get("match_pct"),
            }
        )

    bottlenecks: list[str] = []
    if match_level != "full":
        bottlenecks = diagnose_no_match(
            donor_df, session.parsed_features, session.constraints, scores
        )
        session.pending_relaxations = bottlenecks
    else:
        session.pending_relaxations = []

    payload = {
        "count": n,
        "match_level": match_level,
        "feature_summary": summary,
        "bottlenecks": bottlenecks,
        "top_preview": top,
        "note": "请根据 count/match_level 总结，引导用户查看下方卡片，勿虚构人数与代号。",
    }
    return candidates, match_level, payload


_FIELD_ZH = {
    "height_cm": "身高", "weight_kg": "体重", "bmi": "BMI", "age": "年龄",
    "specimen_count": "标本数量", "education": "学历", "abo_blood": "血型",
    "rh_blood": "Rh血型", "figure": "体型", "skin_color": "肤色",
    "face_shape": "脸型", "eyelid": "眼皮", "lip_shape": "唇型",
    "constellation": "星座",
}


def build_profile_summary(profile) -> str:
    from core.preference.schema import EnumAttr, KeywordAttr, RangeAttr

    lines = []
    for field, attr in profile.attributes.items():
        label = _FIELD_ZH.get(field, field)
        tag = "必须" if attr.constraint == "must" else "偏好"
        if isinstance(attr, RangeAttr):
            lo, hi = attr.range.min, attr.range.max
            if lo is not None and hi is not None:
                val = f"{lo}-{hi}"
            elif lo is not None:
                val = f"≥{lo}"
            else:
                val = f"≤{hi}"
        elif isinstance(attr, EnumAttr):
            val = "或".join(attr.values)
        elif isinstance(attr, KeywordAttr):
            val = "或".join(attr.keywords)
        else:
            val = ""
        lines.append(f"• {label}（{tag}，权重{attr.weight}）：{val}")
    return "\n".join(lines) if lines else "（暂无偏好）"


def run_preference_match(
    session,
    raw_profile: dict,
    fetch_rows=None,
    count_rows=None,
    log: bool = True,
):
    """校验完整画像并匹配。非法则不改 session。返回 (candidates, payload)。"""
    from core.preference.pipeline import match_profile
    from core.preference.validate import ProfileValidationError, parse_profile
    from dialogue.session import DialogueState

    try:
        profile = parse_profile(raw_profile if isinstance(raw_profile, dict) else {})
    except ProfileValidationError as e:
        return [], {"ok": False, "error": str(e)}

    dumped = profile.model_dump()
    session.replace_profile(dumped)
    session.parsed_features = dict(dumped.get("attributes") or {})
    session.constraints = {
        k: (v.get("constraint") if isinstance(v, dict) else "prefer")
        for k, v in (dumped.get("attributes") or {}).items()
    }
    if not profile.attributes:
        return [], {
            "ok": True,
            "skipped": True,
            "count": 0,
            "match_level": "none",
            "bottlenecks": [],
            "feature_summary": "（暂无偏好）",
            "note": "无偏好条件，不执行匹配。",
        }

    result = match_profile(
        profile,
        fetch_rows=fetch_rows,
        count_rows=count_rows,
        log=log,
        session_id=getattr(session, "session_id", ""),
    )
    session.candidates = result.candidates
    session.state = DialogueState.PRESENTING if result.candidates else DialogueState.COLLECTING
    session.pending_relaxations = [b["field"] for b in result.bottlenecks]
    top = []
    for c in result.candidates[:5]:
        d = c.get("donor_info") or {}
        top.append({
            "code": d.get("code"),
            "education": d.get("education"),
            "height": d.get("height"),
            "age": d.get("age"),
            "score": c.get("score"),
        })
    payload = {
        "ok": True,
        "count": len(result.candidates),
        "match_level": result.match_level,
        "filtered_count": result.filtered_count,
        "feature_summary": build_profile_summary(profile),
        "bottlenecks": result.bottlenecks,
        "top_preview": top,
        "note": "请根据 count/match_level 总结，引导用户查看下方卡片，勿虚构人数与代号。",
    }
    return result.candidates, payload


def build_agent_messages(session, user_message: str | None = None) -> list[dict]:
    """组装 Agent 消息列表（session.history 应已含本轮用户句）。"""
    messages: list[dict] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    if session.preference_profile:
        messages.append(
            {
                "role": "system",
                "content": "【当前完整偏好画像】"
                + json.dumps(session.preference_profile, ensure_ascii=False),
            }
        )
    for m in session.get_llm_messages():
        role = m.get("role")
        if role == "assistant":
            messages.append({"role": "assistant", "content": m.get("content") or ""})
        elif role == "user":
            messages.append({"role": "user", "content": m.get("content") or ""})
    # 若 history 尚未写入本轮用户句，则补上
    if user_message:
        last = messages[-1] if messages else None
        if not (last and last.get("role") == "user" and last.get("content") == user_message):
            messages.append({"role": "user", "content": user_message})
    return messages
