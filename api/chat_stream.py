"""SSE 流式对话 API 路由。"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_deps = {}


def inject_dependencies(session_manager, feature_encoder, donor_df, llm_client):
    """注入运行时依赖。"""
    _deps["session_manager"] = session_manager
    _deps["feature_encoder"] = feature_encoder
    _deps["donor_df"] = donor_df
    _deps["llm_client"] = llm_client


class StreamChatRequest(BaseModel):
    session_id: str | None = None
    message: str


@router.post("/api/chat/stream")
async def chat_stream(request: StreamChatRequest):
    """流式对话接口（SSE）。

    事件类型:
      - token:      LLM 流式文本片段
      - reply:      最终完整文本回复
      - candidates: 匹配的候选人列表（JSON）
      - state:      会话状态更新
      - done:       流结束
      - error:      出错
    """
    from dialogue.session import DialogueState
    from dialogue.dialogue_flow import (
        get_welcome,
        build_feature_summary,
        determine_next_action,
        _has_any_feature,
    )
    from dialogue.session import SessionContext
    from core.matcher import compute_similarity, match_with_relaxation
    from core.ranker import rank_and_explain
    from config import LLM_MODEL

    session_manager = _deps.get("session_manager")
    feature_encoder = _deps.get("feature_encoder")
    donor_df = _deps.get("donor_df")
    llm_client = _deps.get("llm_client")

    async def event_stream():
        try:
            if not all([session_manager, feature_encoder, donor_df is not None]):
                yield _sse("error", {"message": "系统未就绪"})
                return

            session = session_manager.get_or_create(request.session_id)

            # 发送 session_id
            yield _sse("state", {
                "session_id": session.session_id,
                "state": session.state.value,
            })

            # 首次对话 → 欢迎语
            if session.state == DialogueState.START:
                welcome = get_welcome(session)
                yield _sse("reply", {"text": welcome})
                yield _sse("done", {})
                return

            session.add_message("user", request.message)

            # ---- LLM 流式调用 ----
            nlu_result = None
            if llm_client:
                nlu_result, token_events = _stream_llm_parse(
                    llm_client, session, request.message
                )
                for evt in token_events:
                    yield evt
            else:
                from api.chat import _mock_parse
                nlu_result = _mock_parse(request.message)
                yield _sse("token", {"text": nlu_result["reply"]})

            if nlu_result is None:
                yield _sse("error", {"message": "LLM 解析失败"})
                return

            intent = nlu_result["intent"]
            features = nlu_result["features"]
            constraints = nlu_result.get("constraints", {})
            remove_fields = nlu_result.get("remove_fields", [])
            ambiguity = nlu_result["ambiguity"]
            clarification = nlu_result["clarification_needed"]
            llm_reply = nlu_result["reply"]

            # 调试事件：发送完整 NLU 解析结果
            yield _sse("debug", {
                "intent": intent,
                "features": features,
                "constraints": constraints,
                "remove_fields": remove_fields,
                "pending_relaxations": session.pending_relaxations,
                "ambiguity": ambiguity,
                "clarification_needed": clarification,
                "accumulated_features": session.parsed_features,
            })

            # Python 端全局肯定兜底：用户简短肯定 + 上轮有待放宽字段 → 强制执行放宽
            from dialogue.nlu import _is_global_affirmative
            from dialogue.dialogue_flow import _has_any_feature as _haf
            if (
                session.pending_relaxations
                and not remove_fields
                and not _haf(features)
                and _is_global_affirmative(request.message)
            ):
                remove_fields = list(session.pending_relaxations)
                intent = "refine"
                session.pending_relaxations = []

            # 决定下一步
            action_info = determine_next_action(
                session, intent, features, ambiguity, clarification, constraints, remove_fields
            )
            action = action_info["action"]

            candidates = []
            final_reply = llm_reply

            if action == "farewell":
                final_reply = action_info["message"]
                session.state = DialogueState.END

            elif action == "match":
                # 执行匹配（渐进式放宽）
                from core.matcher import diagnose_no_match
                query_vec, mask = feature_encoder.encode_query(session.parsed_features)
                scores = compute_similarity(query_vec, feature_encoder.feature_matrix, mask=mask)
                cands, match_level, relaxed_fields = match_with_relaxation(
                    donor_df, session.parsed_features, scores,
                    constraints=session.constraints,
                )
                candidates = rank_and_explain(
                    cands, donor_df, session.parsed_features, match_level=match_level
                )

                # 去重
                seen = set()
                unique = []
                for c in candidates:
                    code = c["donor_info"].get("code", "")
                    if code not in seen:
                        seen.add(code)
                        unique.append(c)
                candidates = unique
                session.candidates = candidates

                summary = build_feature_summary(session.parsed_features)
                n = len(candidates)

                if match_level == "full":
                    session.pending_relaxations = []  # 全量匹配成功，清除待放宽列表
                    final_reply = (
                        f"已根据您的条件完全匹配到 {n} 位捐精人：\n{summary}\n\n"
                        f"您可以查看下方卡片了解详情，也可以点击「满意」或「不满意」进行反馈。"
                    )
                else:
                    # 诊断瓶颈字段并生成引导对话
                    bottlenecks = diagnose_no_match(
                        donor_df, session.parsed_features, session.constraints, scores
                    )
                    session.pending_relaxations = bottlenecks  # 存储本轮瓶颈，供下轮全局肯定时使用
                    if bottlenecks:
                        suggest_lines = "\n".join(f"  • **{b}**" for b in bottlenecks)
                        relax_hint = (
                            f"\n\n以下条件是造成精确匹配困难的主要原因：\n{suggest_lines}\n\n"
                            f'您可以告诉我哪项条件可以放宽（例如"学历放宽到本科也可以"），'
                            f"系统会立即重新为您精准匹配。"
                        )
                    else:
                        relax_hint = "\n\n您可以告诉我哪些条件可以适当放宽，系统会重新为您精准匹配。"

                    if match_level == "relaxed":
                        final_reply = (
                            f"当前条件组合没有完全匹配的捐精人，以下是放宽部分条件后最接近的 {n} 位推荐：\n{summary}\n\n"
                            f"下方卡片显示每项条件的匹配情况，带「✓」的为已满足条件。"
                            + relax_hint
                        )
                    else:
                        final_reply = (
                            f"根据当前全部条件未找到匹配的捐精人，以下是综合相似度最高的 {n} 位推荐：\n{summary}\n\n"
                            f"下方仅供参考。"
                            + relax_hint
                        )
                session.state = DialogueState.PRESENTING

            session.add_message("assistant", final_reply)

            # 发送最终回复
            yield _sse("reply", {"text": final_reply})

            # 发送候选人
            if candidates:
                yield _sse("candidates", {"items": candidates})

            # 发送状态
            yield _sse("state", {
                "session_id": session.session_id,
                "state": session.state.value,
                "parsed_features": session.parsed_features,
            })

            yield _sse("done", {})

        except Exception as e:
            logger.exception("流式对话异常")
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _stream_llm_parse(llm_client, session, user_message: str) -> tuple[dict, list[str]]:
    """流式调用 LLM 并解析结果。

    Returns:
        (nlu_result, token_events): nlu_result 为解析结果，token_events 为需要发送给前端的 SSE 字符串列表。
    """
    import json as _json
    from dialogue.nlu import SYSTEM_PROMPT, _extract_json_from_reply, _clean_reply, _detect_relaxation_fallback, _is_global_affirmative
    from config import LLM_MODEL

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if session.parsed_features:
        ctx = f"【当前已收集的用户需求】{_json.dumps(session.parsed_features, ensure_ascii=False)}"
        messages.append({"role": "system", "content": ctx})
    messages.extend(session.get_llm_messages())
    messages.append({"role": "user", "content": user_message})

    full_text = ""
    token_events = []
    in_json_block = False

    try:
        stream = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not delta or not delta.content:
                continue
            full_text += delta.content
            # 跟踪是否在 JSON 块内
            if "```json" in full_text and not in_json_block:
                in_json_block = True
            if in_json_block and full_text.count("```") >= 2:
                in_json_block = False
            # 只发送非 JSON 块的文本
            if not in_json_block and "```json" not in delta.content:
                token_events.append(_sse("token", {"text": delta.content}))

    except Exception as e:
        logger.error(f"LLM 流式调用失败: {e}")
        return {
            "reply": "抱歉，系统暂时无法处理您的请求，请稍后重试。",
            "intent": "error",
            "features": {},
            "ambiguity": False,
            "clarification_needed": None,
        }, []

    parsed = _extract_json_from_reply(full_text)
    clean = _clean_reply(full_text)

    raw_remove = parsed.get("remove_fields", [])
    remove_fields = [f for f in raw_remove if isinstance(f, str)] if isinstance(raw_remove, list) else []

    # 关键词兜底：LLM 未识别到删除意图时，Python 端补充
    if session.parsed_features:
        fallback = _detect_relaxation_fallback(user_message, session.parsed_features)
        for f in fallback:
            if f not in remove_fields:
                remove_fields.append(f)

    nlu_result = {
        "reply": clean,
        "intent": parsed.get("intent", "question"),
        "features": parsed.get("features", {}),
        "constraints": parsed.get("constraints", {}),
        "remove_fields": remove_fields,
        "ambiguity": parsed.get("ambiguity", False),
        "clarification_needed": parsed.get("clarification_needed"),
    }
    return nlu_result, token_events


def _sanitize(obj):
    """递归将 NaN/Inf 替换为 None，避免 json.dumps 抛出 ValueError。"""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    return obj


def _sse(event: str, data: dict) -> str:
    """格式化 SSE 事件（自动清理 NaN/Inf）。"""
    return f"event: {event}\ndata: {json.dumps(_sanitize(data), ensure_ascii=False)}\n\n"
