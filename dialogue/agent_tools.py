"""顾问 Agent 工具：match_donors 及系统提示。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import config
from core.preference.schema import (
    CORE_FIELDS,
    EXTENDED_FIELDS,
    FIELD_REGISTRY,
    openai_tool_schema,
)

logger = logging.getLogger(__name__)

PREFERENCE_SNAPSHOT_PREFIX = "【当前完整偏好画像】"
EMPTY_PREFERENCE_PROFILE = {"schema_version": "1.0", "attributes": {}}
SUBMIT_PROFILE_TOOL_NAME = "submit_preference_profile"
SUBMIT_PROFILE_EXTENDED_TOOL_NAME = "submit_preference_profile_extended"
PROFILE_TOOL_NAMES = frozenset(
    {SUBMIT_PROFILE_TOOL_NAME, SUBMIT_PROFILE_EXTENDED_TOOL_NAME}
)


def parse_tool_arguments(raw_arguments: str | None, assistant_content: str | None = None) -> dict[str, Any]:
    """从工具 arguments 或助手正文中取出 PreferenceProfile 对象。"""
    for blob in (_extract_json_objects(raw_arguments) + _extract_json_objects(assistant_content)):
        if isinstance(blob, dict) and ("schema_version" in blob or "attributes" in blob):
            blob.setdefault("schema_version", "1.0")
            blob.setdefault("attributes", {})
            return blob
        if isinstance(blob, dict) and blob.get("attributes") is None and any(
            k in blob for k in ("abo_blood", "height_cm", "education")
        ):
            return {"schema_version": "1.0", "attributes": blob}
    return {}


def _extract_json_objects(text: str | None) -> list[Any]:
    if not text or not str(text).strip():
        return []
    s = str(text).strip()
    found: list[Any] = []
    try:
        found.append(json.loads(s))
        return found
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        start = s.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(s, start)
            found.append(obj)
            idx = end
        except json.JSONDecodeError:
            idx = start + 1
    return found

def build_preference_snapshot_message(profile: dict[str, Any] | None) -> dict[str, str]:
    """权威画像片段：独立 system 消息，供 chat-v2 processor 与兼容路径共用。"""
    payload = profile if isinstance(profile, dict) and profile else EMPTY_PREFERENCE_PROFILE
    return {
        "role": "system",
        "content": PREFERENCE_SNAPSHOT_PREFIX
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def is_preference_snapshot_text(text: str | None) -> bool:
    return str(text or "").startswith(PREFERENCE_SNAPSHOT_PREFIX)


def build_agent_system_prompt(
    candidate_pool: int | None = None,
) -> str:
    pool = candidate_pool if candidate_pool is not None else config.MATCH_SCORER_CANDIDATE_POOL
    extended = "、".join(EXTENDED_FIELDS)
    return f"""你是智能生育匹配系统的顾问助手。

你通过对话理解用户对捐精人的偏好，自己判断何时该调用工具。不要用固定口头禅词表，按语义理解。

【必须遵守】
1. 用户提出、修改、放宽、取消任何偏好时，必须调用工具提交当前完整 PreferenceProfile 快照后再总结。禁止只说「已记录/已添加/已放宽」却不调用。
2. 默认用 {SUBMIT_PROFILE_TOOL_NAME}（常用字段）。若本轮 tools 中出现 {SUBMIT_PROFILE_EXTENDED_TOOL_NAME}（用户提到病史/遗传/爱好/吸烟等，或当前画像已含扩展字段），则必须用它提交完整快照（含已有核心条件）。扩展字段：{extended}。
3. 工具参数必须符合 JSON Schema。每个属性都要有 constraint（must|prefer）和 weight（0~1）。字段名、类型、合法枚举以工具 parameters 为准；口语映射见各字段 description，禁止自造近义词。
4. 人数、代号、匹配度只能来自工具返回的 count / ranked_count / filtered_count / prefer_hits。禁止虚构。禁止输出捐精人 Markdown 表格。匹配结果由系统在回复下方展示卡片，引导用户看卡片。
5. 若工具返回 ok=false，根据 error，以及 field / allowed_values（若有）修正 parameters，再次调用同一工具，直到成功或确认无法修正。修正期间不要向用户编造成果。
6. 闲聊、问候、明确说「没了/没有了」且不改条件 → 不调用工具。
7. filtered_count 是满足 must 硬条件的总人数；count / ranked_count 是模型生成的可浏览排名人数（最多 {pool}），两者可能不同。若工具返回 prefer_hits 非空：这些字段只重排、未做硬过滤，hits/of 的分母是模型排名池。总结必须说明「硬条件人数未因该偏好减少，已按偏好重排」，并引用各字段 hits/of。filtered_count 大于 ranked_count 时必须同时说清两个数字，禁止把 {pool} 说成全部合格人数，也禁止把 prefer 说成筛掉了人。

【画像规则】
- 以「{PREFERENCE_SNAPSHOT_PREFIX}」system 片段为当前权威快照；每轮提交完整 attributes，不是增量。取消某条件 = 该字段从 attributes 中消失
- 「必须/一定要/不要（某项）」→ must 且 weight=1.0；「最好/希望」→ prefer；未说强度时 must=1.0、prefer=0.5
- 「也可以/也行」表示放宽：把新值并入该字段（如籍贯 keywords 同时含重庆和四川），不要丢掉旧值
- 数值字段用 range.min/max；单边范围另一侧填 null。枚举用 values。文本用 keywords + match(any|all)
- 调用时 arguments 必须是完整 JSON（schema_version=1.0 与 attributes），禁止空参数
- 禁止输出 SQL，禁止编造代号
"""


AGENT_SYSTEM_PROMPT = build_agent_system_prompt()

_DONOR_CODE = re.compile(r"A\d{7}")
_MD_TABLE_ROW = re.compile(r"(?m)^\s*\|.+\|\s*$")


def slim_assistant_for_llm(content: str | None) -> str:
    """历史里去掉捐精人表格和代号，避免下一轮照抄、跳过工具。"""
    text = content or ""
    text = _MD_TABLE_ROW.sub("", text)
    text = _DONOR_CODE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def tool_failure_payload(error: Any, **extra: Any) -> dict[str, Any]:
    """校验失败时给模型的工具回执：说明怎么错、如何改、要求重试。"""
    payload = {
        "ok": False,
        "retry": True,
        "error": str(error),
        "note": (
            "参数未通过校验。请根据 error，以及 field/allowed_values（若有）"
            "修正完整 PreferenceProfile 后，再次调用同一工具。"
            "不要向用户编造匹配人数、代号或卡片。"
        ),
    }
    field = getattr(error, "field", None)
    allowed_values = getattr(error, "allowed_values", None)
    if field:
        payload["field"] = field
    if allowed_values:
        payload["allowed_values"] = list(allowed_values)
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _match_success_note(
    prefer_hits: list | None,
    *,
    filtered_count: int | None = None,
    ranked_count: int | None = None,
) -> str:
    base = "请根据 count/match_level 总结，引导用户查看下方卡片，勿虚构人数与代号。"
    if (
        filtered_count is not None
        and ranked_count is not None
        and filtered_count > ranked_count
    ):
        base += (
            f" 共有 {filtered_count} 人满足 must 硬条件；"
            f"模型对预选的 {ranked_count} 人生成可浏览排名。"
        )
    if not prefer_hits:
        return base
    return (
        base
        + " prefer_hits 是偏好字段在当前名单上的命中人数，未做硬过滤。"
        " 必须说明：人数未因该偏好减少（仍是 count），已按偏好重排，并引用各字段 hits/of。"
        " 禁止把 prefer 说成筛掉了人。"
    )


SUBMIT_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": SUBMIT_PROFILE_TOOL_NAME,
        "description": (
            "提交当前完整 PreferenceProfile（常用字段）并匹配捐精人。"
            "有偏好或改条件时必须调用。arguments 必须符合 JSON Schema。"
            "除 specimen_count 外最多提交 11 个属性。"
            "若涉及扩展字段，改用 submit_preference_profile_extended。"
            "若返回 ok=false，按 error/field/allowed_values 修正后重试。"
        ),
        "parameters": openai_tool_schema(CORE_FIELDS),
    },
}

SUBMIT_PROFILE_EXTENDED_TOOL = {
    "type": "function",
    "function": {
        "name": SUBMIT_PROFILE_EXTENDED_TOOL_NAME,
        "description": (
            "提交含扩展字段的完整 PreferenceProfile 并匹配捐精人。"
            "用户明确提到病史、遗传、爱好、发量等扩展条件时使用。"
            "arguments 仍须是完整快照（含已有核心条件）。"
            "除 specimen_count 外最多提交 11 个属性。"
            "若返回 ok=false，按 error/field/allowed_values 修正后重试。"
        ),
        "parameters": openai_tool_schema(tuple(FIELD_REGISTRY)),
    },
}

AGENT_TOOLS = [SUBMIT_PROFILE_TOOL, SUBMIT_PROFILE_EXTENDED_TOOL]

# 非 chat-v2 主路径遗留工具；新对话请用 AGENT_TOOLS。
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
                "figure": {"type": "string", "description": "一般/瘦弱/强壮/肥胖"},
                "skin_color": {"type": "string", "description": "偏白/一般/偏黑"},
                "face_shape": {"type": "string", "description": "长方/长/椭圆/瓜子"},
                "eyelid": {"type": "string", "description": "单/双"},
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
    ranker=None,
    log: bool = True,
):
    """校验完整画像并匹配。非法则不改 session。返回 (candidates, payload)。"""
    from core.preference.pipeline import match_profile
    from core.preference.validate import ProfileValidationError, parse_profile
    from dialogue.session import DialogueState

    try:
        profile = parse_profile(raw_profile if isinstance(raw_profile, dict) else {})
    except ProfileValidationError as e:
        return [], tool_failure_payload(e)

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
        ranker=ranker,
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
        "count": result.ranked_count or len(result.candidates),
        "ranked_count": result.ranked_count or len(result.candidates),
        "match_level": result.match_level,
        "filtered_count": result.filtered_count,
        "feature_summary": build_profile_summary(profile),
        "bottlenecks": result.bottlenecks,
        "top_preview": top,
        "prefer_hits": list(result.prefer_hits or []),
        "note": _match_success_note(
            result.prefer_hits,
            filtered_count=result.filtered_count,
            ranked_count=result.ranked_count or len(result.candidates),
        ),
    }
    return result.candidates, payload


def apply_match_api_response(session, raw_profile: dict, status: int, data: dict):
    """把 POST /api/match 的 HTTP 结果写回会话，并生成给大模型的工具回执。"""
    from core.preference.validate import ProfileValidationError, parse_profile
    from dialogue.session import DialogueState

    if status == 400:
        detail = data.get("detail") if isinstance(data, dict) else status
        return [], tool_failure_payload(detail)
    if status != 200 or not (isinstance(data, dict) and data.get("ok")):
        detail = (data.get("detail") if isinstance(data, dict) else None) or f"match api {status}"
        return [], tool_failure_payload(detail, retry=status in (400, 422))
    try:
        profile = parse_profile(raw_profile if isinstance(raw_profile, dict) else {})
    except ProfileValidationError as e:
        return [], tool_failure_payload(e)

    dumped = profile.model_dump()
    session.replace_profile(dumped)
    session.parsed_features = dict(dumped.get("attributes") or {})
    session.constraints = {
        k: (v.get("constraint") if isinstance(v, dict) else "prefer")
        for k, v in (dumped.get("attributes") or {}).items()
    }
    candidates = data.get("candidates") or []
    filtered_count = data.get("total", data.get("filtered_count"))
    try:
        total_count = max(len(candidates), int(filtered_count))
    except (TypeError, ValueError):
        total_count = len(candidates)
    session.candidates = candidates
    session.match_result_id = data.get("result_set_id") or None
    session.match_total = total_count
    session.match_next_cursor = data.get("next_cursor") or None
    session.state = DialogueState.PRESENTING if candidates else DialogueState.COLLECTING
    session.pending_relaxations = [b.get("field") for b in (data.get("bottlenecks") or []) if isinstance(b, dict)]
    top = []
    for c in candidates[:5]:
        d = (c or {}).get("donor_info") or {}
        top.append({
            "code": d.get("code"),
            "education": d.get("education"),
            "height": d.get("height"),
            "age": d.get("age"),
            "score": c.get("score"),
        })
    prefer_hits = list(data.get("prefer_hits") or [])
    payload = {
        "ok": True,
        "count": total_count,
        "ranked_count": total_count,
        "match_level": data.get("match_level"),
        "filtered_count": data.get("filtered_count"),
        "feature_summary": build_profile_summary(profile),
        "bottlenecks": data.get("bottlenecks") or [],
        "top_preview": top,
        "prefer_hits": prefer_hits,
        "result_set_id": session.match_result_id,
        "next_cursor": session.match_next_cursor,
        "note": _match_success_note(
            prefer_hits,
            filtered_count=data.get("filtered_count"),
            ranked_count=total_count,
        ),
    }
    if data.get("skipped"):
        payload["skipped"] = True
        payload["note"] = "无偏好条件，不执行匹配。"
        payload["feature_summary"] = "（暂无偏好）"
    return candidates, payload


def build_agent_messages(session, user_message: str | None = None) -> list[dict]:
    """组装 Agent 消息列表（兼容旧 session 路径；chat-v2 以 processor 为准）。"""
    messages: list[dict] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        build_preference_snapshot_message(getattr(session, "preference_profile", None)),
    ]
    for m in session.get_llm_messages():
        role = m.get("role")
        if role == "assistant":
            messages.append({"role": "assistant", "content": slim_assistant_for_llm(m.get("content") or "")})
        elif role == "user":
            messages.append({"role": "user", "content": m.get("content") or ""})
    # 若 history 尚未写入本轮用户句，则补上
    if user_message:
        last = messages[-1] if messages else None
        if not (last and last.get("role") == "user" and last.get("content") == user_message):
            messages.append({"role": "user", "content": user_message})
    return messages
