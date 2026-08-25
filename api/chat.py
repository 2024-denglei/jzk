"""文本对话 API 路由。"""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth_utils import get_current_user_id

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class CandidateInfo(BaseModel):
    donor_info: dict
    score: float
    reason: str
    match_level: str = "full"
    field_match: dict = {}


class ChatResponse(BaseModel):
    reply: str
    candidates: list[CandidateInfo] = []
    session_id: str
    state: str
    parsed_features: dict = {}


# 这些依赖会在 main.py 中注入
_deps = {}


def inject_dependencies(session_manager, feature_encoder, donor_df, llm_client):
    """注入运行时依赖。"""
    _deps["session_manager"] = session_manager
    _deps["feature_encoder"] = feature_encoder
    _deps["donor_df"] = donor_df
    _deps["llm_client"] = llm_client


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _user_id: int = Depends(get_current_user_id)):
    """文本对话主接口（需登录）。"""
    from dialogue.session import DialogueState
    from dialogue.nlu import parse_user_intent
    from dialogue.dialogue_flow import get_welcome
    from dialogue.response_gen import generate_response
    from core.matcher import compute_similarity, match_with_relaxation
    from core.ranker import rank_and_explain

    session_manager = _deps.get("session_manager")
    feature_encoder = _deps.get("feature_encoder")
    donor_df = _deps.get("donor_df")
    llm_client = _deps.get("llm_client")

    if not all([session_manager, feature_encoder, donor_df is not None]):
        raise HTTPException(status_code=500, detail="系统未就绪")

    # 获取或创建会话
    session = session_manager.get_or_create(request.session_id)

    # 首次对话 → 发送欢迎语
    if session.state == DialogueState.START:
        welcome = get_welcome(session)
        return ChatResponse(
            reply=welcome,
            candidates=[],
            session_id=session.session_id,
            state=session.state.value,
            parsed_features={},
        )

    # 记录用户消息
    session.add_message("user", request.message)

    # LLM 解析（有 API Key 时调用 LLM，否则使用规则模拟）
    if llm_client:
        nlu_result = parse_user_intent(
            client=llm_client,
            user_message=request.message,
            history=session.get_llm_messages(),
            current_features=session.parsed_features,
        )
    else:
        nlu_result = _mock_parse(request.message)

    # 匹配函数
    _match_info: dict = {}

    def do_match(parsed_features: dict) -> list[dict]:
        from core.matcher import diagnose_no_match
        query_vec, mask = feature_encoder.encode_query(parsed_features)
        scores = compute_similarity(query_vec, feature_encoder.feature_matrix, mask=mask)
        cands, match_level, relaxed_fields = match_with_relaxation(
            donor_df, parsed_features, scores,
            constraints=session.constraints,
        )
        _match_info["level"] = match_level
        _match_info["relaxed"] = relaxed_fields
        if match_level != "full":
            _match_info["bottlenecks"] = diagnose_no_match(
                donor_df, parsed_features, session.constraints, scores
            )
        return rank_and_explain(cands, donor_df, parsed_features, match_level=match_level)

    # 生成回复
    result = generate_response(session, nlu_result, match_func=do_match, match_info=_match_info)

    return ChatResponse(
        reply=result["reply"],
        candidates=[CandidateInfo(**c) for c in result.get("candidates", [])],
        session_id=result["session_id"],
        state=result["state"],
        parsed_features=result.get("parsed_features", {}),
    )


def _mock_parse(message: str) -> dict:
    """无 LLM 时的规则解析（用于演示/测试）。"""
    features = {}
    reply_parts = []

    # 学历
    for edu in ["博士", "硕士", "本科", "大专"]:
        if edu in message:
            features["education"] = edu
            reply_parts.append(f"学历：{edu}")
            break
    if "学历高" in message:
        features["education"] = "硕士"
        reply_parts.append("学历：硕士及以上")

    # 身高
    h_match = re.search(r"(\d{3})\s*(?:cm|厘米)?(?:\s*[-~到至]\s*(\d{3}))?", message)
    if h_match:
        h_min = int(h_match.group(1))
        h_max = int(h_match.group(2)) if h_match.group(2) else h_min + 10
        features["height"] = {"min": h_min, "max": h_max}
        reply_parts.append(f"身高：{h_min}-{h_max}cm")
    elif "高个" in message or "偏高" in message:
        features["height"] = {"min": 178, "max": 190}
        reply_parts.append("身高：178-190cm")
    elif "身高适中" in message:
        features["height"] = {"min": 170, "max": 180}
        reply_parts.append("身高：170-180cm")

    # 体型
    figure_map = {"匀称": "匀称型", "标准": "匀称型", "壮": "精壮型", "精壮": "精壮型", "瘦": "偏瘦型"}
    for kw, val in figure_map.items():
        if kw in message:
            features["figure"] = val
            reply_parts.append(f"体型：{val}")
            break

    # 肤色
    if "白" in message and "肤" in message or "皮肤白" in message or "偏白" in message:
        features["skin_color"] = "偏白"
        reply_parts.append("肤色：偏白")

    # 血型
    for bt in ["AB", "A", "B", "O"]:
        if f"{bt}型血" in message or f"血型{bt}" in message or f"{bt}型" in message:
            features["blood_type"] = bt
            reply_parts.append(f"血型：{bt}型")
            break

    # 形象气质
    appear_map = {"阳光": "阳光型", "帅": "阳光型", "文艺": "文艺型", "温柔": "文艺型", "成熟": "成熟型", "稳重": "成熟型", "绅士": "绅士型", "儒雅": "绅士型"}
    for kw, val in appear_map.items():
        if kw in message:
            features["appearance"] = val
            reply_parts.append(f"形象气质：{val}")
            break

    has_features = bool(features)

    # 判断是否为修正意图（含修改/调整/追加关键词）
    refine_keywords = ["改", "换", "不要", "调整", "修改", "还要", "再加", "追加", "另外"]
    is_refine = any(kw in message for kw in refine_keywords)
    intent = "refine" if (has_features and is_refine) else ("search" if has_features else "question")

    if has_features:
        summary = "、".join(reply_parts)
        if is_refine:
            reply = f"好的，我已更新您的条件：{summary}。正在重新为您匹配..."
        else:
            reply = f"好的，我理解您的需求：{summary}。正在为您匹配..."
    else:
        reply = "请告诉我您对捐精人的具体要求，例如学历、身高、体型、肤色等。"

    # 根据用户语气推断 constraints
    must_keywords = ["必须", "一定要", "只要", "要求", "得是", "必须是", "不能不是"]
    prefer_keywords = ["最好", "希望", "偏好", "尽量", "优先", "如果可以"]
    is_must_tone = any(kw in message for kw in must_keywords)
    is_prefer_tone = any(kw in message for kw in prefer_keywords)

    DEFAULT_MUST = {"education", "blood_type", "height"}
    mock_constraints = {}
    for key in features:
        if is_prefer_tone:
            mock_constraints[key] = "prefer"
        elif is_must_tone:
            mock_constraints[key] = "must"
        else:
            mock_constraints[key] = "must" if key in DEFAULT_MUST else "prefer"

    return {
        "reply": reply,
        "intent": intent,
        "features": features,
        "constraints": mock_constraints,
        "ambiguity": False,
        "clarification_needed": None,
    }
