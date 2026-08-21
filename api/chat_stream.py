"""SSE 流式对话 API：Agent + submit_preference_profile 工具调用。"""

from __future__ import annotations

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
    message: str = ""


class AbortChatRequest(BaseModel):
    session_id: str


class RewindChatRequest(BaseModel):
    session_id: str
    history: list[dict] = []
    parsed_features: dict = {}
    constraints: dict = {}
    preference_profile: dict | None = None
    messages: list[dict] | None = None
    candidates: list | None = None


@router.post("/api/chat/abort")
async def chat_abort(body: AbortChatRequest, request: Request):
    """中止进行中的一轮：回滚本轮对会话的修改，不落库。"""
    session_manager = _deps.get("session_manager")
    if not session_manager:
        return {"ok": False, "reason": "not_ready"}
    session = session_manager.get_session(body.session_id)
    if not session:
        return {"ok": True, "rolled_back": False}
    rolled = session.abort_turn()
    return {"ok": True, "rolled_back": rolled}


@router.post("/api/chat/rewind")
async def chat_rewind(body: RewindChatRequest, request: Request):
    """回溯到某条消息：截断历史并恢复筛选条件。"""
    from dialogue.session import SessionContext

    session_manager = _deps.get("session_manager")
    if not session_manager:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="系统未就绪")
    session = session_manager.get_session(body.session_id)
    if not session:
        session = session_manager.put_session(SessionContext(session_id=body.session_id))
    # 若仍有未完成轮次，先丢掉
    session.abort_turn()
    history = []
    for m in body.history or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role in ("user", "assistant"):
            history.append({"role": role, "content": content})
        elif role == "bot":
            history.append({"role": "assistant", "content": content})
    session.apply_rewind(
        history,
        parsed_features=body.parsed_features or {},
        constraints=body.constraints or {},
        candidates=body.candidates,
        preference_profile=body.preference_profile,
    )
    user_id = _optional_user_id(request)
    ui_messages = body.messages
    if ui_messages is None:
        ui_messages = _history_to_ui_messages(session, session.candidates)
    _maybe_persist(user_id, session, ui_messages, session.candidates)
    return {
        "ok": True,
        "session_id": session.session_id,
        "state": session.state.value,
        "parsed_features": session.parsed_features,
        "constraints": session.constraints,
        "preference_profile": session.preference_profile or {},
        "history_len": len(session.history),
    }


@router.post("/api/chat/stream")
async def chat_stream(body: StreamChatRequest, request: Request):
    """流式对话接口（SSE）。

    事件: token | reply | candidates | state | done | error | aborted
    """
    from dialogue.session import DialogueState
    from dialogue.dialogue_flow import get_welcome
    from dialogue.agent_tools import (
        SUBMIT_PROFILE_TOOL,
        build_agent_messages,
        run_preference_match,
    )
    from config import LLM_MODEL, TRACE_ENABLED
    from dialogue.agent_trace import AgentTrace

    session_manager = _deps.get("session_manager")
    feature_encoder = _deps.get("feature_encoder")
    donor_df = _deps.get("donor_df")
    llm_client = _deps.get("llm_client")

    user_id = _optional_user_id(request)

    async def event_stream():
        trace: AgentTrace | None = None
        session = None
        turn_started = False
        try:
            if not all([session_manager, feature_encoder, donor_df is not None]):
                yield _sse("error", {"message": "系统未就绪"})
                return

            session = session_manager.get_or_create(body.session_id)

            yield _sse(
                "state",
                {
                    "session_id": session.session_id,
                    "state": session.state.value,
                    "parsed_features": session.parsed_features,
                    "constraints": session.constraints,
                    "preference_profile": session.preference_profile or {},
                },
            )

            # 空消息：欢迎语
            if session.state == DialogueState.START and not (body.message or "").strip():
                welcome = get_welcome(session)
                yield _sse("reply", {"text": welcome})
                yield _sse("done", {})
                _maybe_persist(user_id, session, [], [])
                return

            user_text = (body.message or "").strip()
            if not user_text:
                yield _sse("error", {"message": "消息不能为空"})
                return

            features_before = dict(session.parsed_features)
            constraints_before = dict(session.constraints)

            # START 状态若直接发需求，先进入收集
            if session.state == DialogueState.START:
                session.state = DialogueState.COLLECTING

            session.begin_turn()
            turn_started = True
            session.add_message("user", user_text)

            async def _client_gone() -> bool:
                try:
                    return await request.is_disconnected()
                except Exception:
                    return False

            async def _abort_and_signal():
                nonlocal turn_started
                if session and turn_started:
                    session.abort_turn()
                    turn_started = False
                if trace:
                    try:
                        trace.finish(error="aborted_by_client")
                    except Exception:
                        pass
                yield_msg = _sse("aborted", {"session_id": session.session_id if session else None})
                return yield_msg

            if TRACE_ENABLED:
                trace = AgentTrace(
                    session_id=session.session_id,
                    user_message=user_text,
                    user_id=user_id,
                    model=LLM_MODEL,
                )
                trace.add(
                    "turn_start",
                    dialogue_state=session.state.value,
                    parsed_features_before=features_before,
                    constraints_before=constraints_before,
                )

            candidates: list = []
            final_reply = ""

            if await _client_gone():
                yield await _abort_and_signal()
                return

            if not llm_client:
                # 无 LLM：规则兜底直接匹配常见条件
                final_reply, candidates = _mock_agent_turn(
                    session, user_text, feature_encoder, donor_df
                )
                if trace:
                    trace.add("mock_agent", reply=final_reply, candidates_count=len(candidates))
            else:
                messages = build_agent_messages(session, user_text)
                if trace:
                    trace.log_llm_request(
                        "tool_select",
                        messages,
                        tools=["submit_preference_profile"],
                        tool_choice="auto",
                    )
                # 第一轮：带 tools（非流式，便于拿 tool_calls）
                try:
                    first = llm_client.chat.completions.create(
                        model=LLM_MODEL,
                        messages=messages,
                        tools=[SUBMIT_PROFILE_TOOL],
                        tool_choice="auto",
                        temperature=0.2,
                        max_tokens=1024,
                    )
                except Exception as e:
                    logger.exception("LLM tools 调用失败")
                    if session and turn_started:
                        session.abort_turn()
                        turn_started = False
                    if trace:
                        trace.finish(error=str(e))
                    yield _sse("error", {"message": f"顾问服务异常：{e}"})
                    return

                if await _client_gone():
                    yield await _abort_and_signal()
                    return

                choice = first.choices[0].message
                tool_calls = getattr(choice, "tool_calls", None) or []
                tool_calls_dump = [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in tool_calls
                ]
                if trace:
                    trace.log_llm_response(
                        "tool_select",
                        content=choice.content,
                        tool_calls=tool_calls_dump,
                    )

                if tool_calls:
                    # 执行工具
                    assistant_tool_msg = {
                        "role": "assistant",
                        "content": choice.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                    messages.append(assistant_tool_msg)

                    for tc in tool_calls:
                        name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {"_raw": tc.function.arguments}
                        if name != "submit_preference_profile":
                            tool_content = json.dumps(
                                {"error": f"unknown tool {name}"}, ensure_ascii=False
                            )
                            if trace:
                                trace.log_tool_call(
                                    name, args, result={"error": f"unknown tool {name}"}, tool_call_id=tc.id
                                )
                        else:
                            candidates, payload = run_preference_match(session, args, log=True)
                            tool_content = json.dumps(payload, ensure_ascii=False)
                            if trace:
                                trace.log_tool_call(
                                    name,
                                    {
                                        "raw_arguments": args,
                                        "preference_profile": session.preference_profile,
                                    },
                                    result=payload,
                                    tool_call_id=tc.id,
                                )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": tool_content,
                            }
                        )

                    if await _client_gone():
                        yield await _abort_and_signal()
                        return

                    # 第二轮：根据工具结果总结（流式）
                    if trace:
                        trace.log_llm_request("summarize", messages)
                    try:
                        stream = llm_client.chat.completions.create(
                            model=LLM_MODEL,
                            messages=messages,
                            temperature=0.3,
                            max_tokens=600,
                            stream=True,
                        )
                        for chunk in stream:
                            if await _client_gone():
                                yield await _abort_and_signal()
                                return
                            if not chunk.choices:
                                continue
                            delta = chunk.choices[0].delta
                            if delta and delta.content:
                                final_reply += delta.content
                                yield _sse("token", {"text": delta.content})
                    except Exception as e:
                        logger.exception("总结流式失败")
                        n = len(candidates)
                        final_reply = (
                            f"已根据您的条件匹配到 {n} 位候选人，请查看下方卡片。"
                            if n
                            else "未找到匹配结果，请尝试放宽条件。"
                        )
                        yield _sse("token", {"text": final_reply})
                        if trace:
                            trace.add("summarize_fallback", error=str(e), reply=final_reply)

                    if trace:
                        trace.log_llm_response("summarize", content=final_reply)

                    # 人数兜底：若模型胡说，用真实人数校正短回复
                    if candidates and str(len(candidates)) not in final_reply:
                        final_reply = (
                            f"{final_reply.rstrip()}\n\n"
                            f"（本轮实际匹配 {len(candidates)} 位，详见下方卡片）"
                        )
                        if trace:
                            trace.add("reply_count_corrected", candidates_count=len(candidates))
                else:
                    # 无工具：澄清/闲聊。匹配只接受合法 PreferenceProfile，不再用旧条件硬猜。
                    content = choice.content or ""
                    if content:
                        final_reply = content
                        yield _sse("token", {"text": content})
                    else:
                        final_reply = "请再具体描述一下您的期望，例如学历、身高、年龄等。"
                        yield _sse("token", {"text": final_reply})

                    if await _client_gone():
                        yield await _abort_and_signal()
                        return

            if await _client_gone():
                yield await _abort_and_signal()
                return

            if not final_reply:
                final_reply = "已处理您的请求。"

            session.add_message("assistant", final_reply)
            session.end_turn()
            turn_started = False

            yield _sse("reply", {"text": final_reply})
            if candidates:
                yield _sse("candidates", {"items": candidates})

            yield _sse(
                "state",
                {
                    "session_id": session.session_id,
                    "state": session.state.value,
                    "parsed_features": session.parsed_features,
                    "constraints": session.constraints,
                    "preference_profile": session.preference_profile or {},
                    "features_before": features_before,
                    "constraints_before": constraints_before,
                },
            )
            yield _sse("done", {})

            # 登录用户：服务端持久化
            ui_messages = _history_to_ui_messages(session, candidates)
            _maybe_persist(user_id, session, ui_messages, candidates)

            if trace:
                trace.finish(
                    final_reply=final_reply,
                    candidates_count=len(candidates),
                    parsed_features=dict(session.parsed_features),
                    constraints=dict(session.constraints),
                )

        except Exception as e:
            logger.exception("流式对话异常")
            if session and turn_started:
                try:
                    session.abort_turn()
                except Exception:
                    pass
            if trace:
                try:
                    trace.finish(error=str(e))
                except Exception:
                    pass
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


def _optional_user_id(request: Request) -> int | None:
    from api.auth_utils import decode_token

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
        return int(payload.get("sub"))
    except Exception:
        return None


def _maybe_persist(user_id, session, ui_messages, candidates):
    if not user_id:
        return
    try:
        from api.chat_persist import upsert_user_chat

        upsert_user_chat(
            user_id=user_id,
            session_id=session.session_id,
            messages=ui_messages or _history_to_ui_messages(session, candidates),
            candidates=candidates or session.candidates,
            state=session.to_state(),
        )
    except Exception:
        logger.exception("持久化对话失败")


def _history_to_ui_messages(session, last_candidates) -> list[dict]:
    out = []
    for m in session.history:
        role = m.get("role")
        item = {
            "role": "user" if role == "user" else "bot",
            "content": m.get("content") or "",
        }
        out.append(item)
    if last_candidates and out and out[-1]["role"] == "bot":
        out[-1]["candidates"] = last_candidates
    return out


def _looks_like_criteria(text: str) -> bool:
    keys = (
        "学历", "身高", "年龄", "血型", "硕士", "本科", "博士", "大专", "cm", "岁",
        "帅", "气质", "肤色", "籍贯", "职业", "性格", "标本",
    )
    return any(k in text for k in keys)


def _apply_simple_parse(session, text: str):
    """极简规则解析，供无 tool_call 时的强制匹配兜底。"""
    import re

    # 取消条件类话术不要误解析出新条件
    if any(
        k in text
        for k in (
            "不做要求",
            "没有要求",
            "不作为",
            "不用作为",
            "取消",
            "去掉",
            "不用了",
            "不要了",
            "不限",
            "算了",
        )
    ):
        return

    features = {}
    constraints = {}
    if "博士" in text:
        features["education"] = "博士"
    elif "硕士" in text:
        features["education"] = "硕士"
    elif "本科" in text:
        features["education"] = "本科"
    elif "大专" in text:
        features["education"] = "大专"
    if "education" in features:
        constraints["education"] = "must"

    m = re.search(r"身高\s*(?:要|得)?\s*(\d{2,3})\s*(?:cm)?\s*(?:以上|及以上|\+|以上)", text)
    if not m:
        m = re.search(r"(\d{2,3})\s*(?:cm)?\s*以上", text)
    if m:
        features["height"] = {"min": int(m.group(1))}
        constraints["height"] = "must"

    # 年龄：仅当含岁/年龄
    if "年龄" in text or "岁" in text:
        m = re.search(r"(\d{1,2})\s*岁\s*(?:以下|以内)", text)
        if m:
            features["age"] = {"max": int(m.group(1))}
            constraints["age"] = "must"
        m = re.search(r"(\d{1,2})\s*岁\s*(?:以上|及以上)", text)
        if m and "身高" not in text[max(0, m.start() - 4) : m.start()]:
            features["age"] = {"min": int(m.group(1))}
            constraints["age"] = "must"

    if features:
        session.update_features(features, constraints)


def _mock_agent_turn(session, user_text, feature_encoder, donor_df):
    return "当前未配置大模型，无法解析偏好画像。请配置 LLM_API_KEY 后重试。", []


def _sanitize(obj):
    import math

    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    return obj


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(_sanitize(data), ensure_ascii=False)}\n\n"
