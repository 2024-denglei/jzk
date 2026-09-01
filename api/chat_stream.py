"""SSE 流式对话 API：Agent + submit_preference_profile 工具调用。"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth_utils import get_current_user_id
from core.data_loader import to_card_donor_info

logger = logging.getLogger(__name__)

router = APIRouter()

_deps = {}


def _slim_candidates_for_sse(
    candidates: list,
    prefer_hits: list | None = None,
) -> list[dict]:
    """对话 SSE 保留全量条数，但去掉 field_scores 等重字段，避免前端解析卡死。"""
    prefer_fields = {
        h.get("field")
        for h in (prefer_hits or [])
        if isinstance(h, dict) and h.get("field")
    }
    slimmed: list[dict] = []
    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        fm = c.get("field_match") or {}
        slim_fm = (
            {k: fm[k] for k in prefer_fields if k in fm}
            if prefer_fields and isinstance(fm, dict)
            else {}
        )
        info = c.get("donor_info") if isinstance(c.get("donor_info"), dict) else {}
        slimmed.append(
            {
                "donor_info": to_card_donor_info(info),
                "score": c.get("score"),
                "match_pct": c.get("match_pct"),
                "reason": "",
                "match_level": c.get("match_level") or "",
                "field_match": slim_fm,
                "rank": c.get("rank"),
            }
        )
    return slimmed


def inject_dependencies(session_manager, feature_encoder, donor_df, llm_client):
    """注入运行时依赖。"""
    _deps["session_manager"] = session_manager
    _deps["feature_encoder"] = feature_encoder
    _deps["donor_df"] = donor_df
    _deps["llm_client"] = llm_client


class StreamChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    message: str = Field(default="", max_length=4000)


class AbortChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class RewindChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    history: list[dict] = Field(default_factory=list, max_length=100)
    parsed_features: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)
    preference_profile: dict | None = None
    messages: list[dict] | None = Field(default=None, max_length=100)
    candidates: list | None = Field(default=None, max_length=1000)
    match_result_id: str | None = Field(default=None, max_length=64)
    match_total: int = Field(default=0, ge=0)
    match_next_cursor: str | None = Field(default=None, max_length=2048)


@router.post("/api/chat/abort")
async def chat_abort(body: AbortChatRequest, user_id: int = Depends(get_current_user_id)):
    """中止进行中的一轮：回滚本轮对会话的修改，不落库。"""
    session_manager = _deps.get("session_manager")
    if not session_manager:
        return {"ok": False, "reason": "not_ready"}
    session = session_manager.get_session(user_id, body.session_id)
    if not session:
        return {"ok": True, "rolled_back": False}
    rolled = session.abort_turn()
    session_manager.put_session(session)
    return {"ok": True, "rolled_back": rolled}


@router.post("/api/chat/rewind")
async def chat_rewind(body: RewindChatRequest, user_id: int = Depends(get_current_user_id)):
    """回溯到某条消息：截断历史并恢复筛选条件。"""
    from dialogue.session import SessionContext

    session_manager = _deps.get("session_manager")
    if not session_manager:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="系统未就绪")
    session = session_manager.get_session(user_id, body.session_id)
    if not session:
        session = session_manager.put_session(
            SessionContext(owner_user_id=user_id, session_id=body.session_id)
        )
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
        match_result_id=body.match_result_id,
        match_total=body.match_total,
        match_next_cursor=body.match_next_cursor,
    )
    session_manager.put_session(session)
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
async def chat_stream(body: StreamChatRequest, request: Request, user_id: int = Depends(get_current_user_id)):
    """流式对话接口（SSE）。

    事件: token | reply | candidates | state | done | error | aborted
    """
    from dialogue.session import DialogueState
    from dialogue.dialogue_flow import get_welcome
    from dialogue.agent_tools import (
        SUBMIT_PROFILE_TOOL,
        apply_match_api_response,
        build_agent_messages,
        parse_tool_arguments,
        tool_failure_payload,
    )
    from api.match import invoke_match_endpoint
    from config import LLM_MODEL, MATCH_RESULT_PAGE_SIZE_DEFAULT, TRACE_ENABLED
    from dialogue.agent_trace import AgentTrace

    session_manager = _deps.get("session_manager")
    feature_encoder = _deps.get("feature_encoder")
    donor_df = _deps.get("donor_df")
    llm_client = _deps.get("llm_client")

    async def event_stream():
        trace: AgentTrace | None = None
        session = None
        turn_started = False
        try:
            if not all([session_manager, feature_encoder, donor_df is not None]):
                yield _sse("error", {"message": "系统未就绪"})
                return

            session = session_manager.get_or_create(user_id, body.session_id)

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
                session_manager.put_session(session)
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
            session_manager.put_session(session)
            t_turn = time.perf_counter()

            async def _client_gone() -> bool:
                try:
                    return await request.is_disconnected()
                except Exception:
                    return False

            async def _abort_and_signal():
                nonlocal turn_started
                if session and turn_started:
                    session.abort_turn()
                    session_manager.put_session(session)
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
            candidate_total = 0
            prefer_hits: list = []
            match_result_id: str | None = None
            match_next_cursor: str | None = None
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
                match_payload: dict | None = None
                used_tool = False
                max_rounds = 4
                for round_i in range(max_rounds):
                    if trace:
                        trace.log_llm_request(
                            "tool_select",
                            messages,
                            tools=["submit_preference_profile"],
                            tool_choice="auto",
                        )
                    try:
                        t_llm1 = time.perf_counter()
                        first = await llm_client.chat.completions.create(
                            model=LLM_MODEL,
                            messages=messages,
                            tools=[SUBMIT_PROFILE_TOOL],
                            tool_choice="auto",
                            temperature=0.2,
                            max_tokens=2048,
                        )
                        if trace:
                            trace.mark("llm_tool_select", (time.perf_counter() - t_llm1) * 1000)
                    except Exception as e:
                        logger.exception("LLM tools 调用失败")
                        if session and turn_started:
                            session.abort_turn()
                            turn_started = False
                        if trace:
                            trace.finish(error=str(e))
                        msg = f"顾问服务异常：{e}"
                        yield _sse("error", {"message": msg})
                        yield _sse("token", {"text": msg})
                        return

                    if await _client_gone():
                        yield await _abort_and_signal()
                        return

                    choice = first.choices[0].message
                    tool_calls = getattr(choice, "tool_calls", None) or []
                    if trace:
                        trace.log_llm_response(
                            "tool_select",
                            content=choice.content,
                            tool_calls=[
                                {
                                    "id": tc.id,
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }
                                for tc in tool_calls
                            ],
                        )

                    if not tool_calls:
                        content = choice.content or ""
                        retryable = bool(
                            used_tool
                            and match_payload
                            and not match_payload.get("ok")
                            and match_payload.get("retry")
                            and round_i < max_rounds - 1
                        )
                        if retryable:
                            messages.append({"role": "assistant", "content": content or None})
                            err = match_payload.get("error") or "画像校验失败"
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"工具校验失败：{err}。"
                                        "请按该错误修正完整 PreferenceProfile 后，"
                                        "再次调用 submit_preference_profile。"
                                        "不要向用户编造匹配结果。"
                                    ),
                                }
                            )
                            if trace:
                                trace.add("tool_retry", error=str(err), round=round_i)
                            yield _sse("token", {"text": "条件格式需要修正，正在重试…"})
                            continue
                        if used_tool and match_payload and not match_payload.get("ok"):
                            err = match_payload.get("error") or "画像校验失败"
                            final_reply = (
                                f"没能生成合法偏好画像（{err}）。"
                                "请再用一句话说清必须条件和偏好，例如：必须O型，身高最好175以上。"
                            )
                            yield _sse("error", {"message": final_reply})
                            yield _sse("token", {"text": final_reply})
                        elif content:
                            final_reply = content
                            yield _sse("token", {"text": content})
                        else:
                            final_reply = "请再具体描述一下您的期望，例如学历、身高、年龄等。"
                            yield _sse("token", {"text": final_reply})
                        break

                    used_tool = True
                    if choice.content:
                        yield _sse("token", {"text": choice.content})

                    messages.append(
                        {
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
                    )

                    for tc in tool_calls:
                        name = tc.function.name
                        args = parse_tool_arguments(
                            tc.function.arguments, choice.content
                        )
                        if name != "submit_preference_profile":
                            match_payload = tool_failure_payload(f"unknown tool {name}")
                            tool_content = json.dumps(match_payload, ensure_ascii=False)
                            if trace:
                                trace.log_tool_call(
                                    name, args, result={"error": f"unknown tool {name}"}, tool_call_id=tc.id
                                )
                        else:
                            yield _sse("token", {"text": "\n\n正在匹配候选人…"})
                            auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
                            t_match = time.perf_counter()
                            status, match_data = await invoke_match_endpoint(
                                request.app,
                                auth,
                                args,
                                page_size=MATCH_RESULT_PAGE_SIZE_DEFAULT,
                            )
                            match_invoke_ms = (time.perf_counter() - t_match) * 1000
                            t_apply = time.perf_counter()
                            candidates, match_payload = apply_match_api_response(
                                session, args, status, match_data
                            )
                            prefer_hits = list((match_payload or {}).get("prefer_hits") or [])
                            candidate_total = int((match_payload or {}).get("count") or len(candidates))
                            match_result_id = (match_payload or {}).get("result_set_id")
                            match_next_cursor = (match_payload or {}).get("next_cursor")
                            apply_ms = (time.perf_counter() - t_apply) * 1000
                            tool_content = json.dumps(match_payload, ensure_ascii=False)
                            if trace:
                                inner = match_data.get("timings") if isinstance(match_data, dict) else None
                                trace.mark(
                                    "match",
                                    match_invoke_ms,
                                    http_status=status,
                                    candidates_count=len(candidates),
                                    **(inner if isinstance(inner, dict) else {}),
                                )
                                trace.mark("apply_match_response", apply_ms)
                                trace.log_tool_call(
                                    name,
                                    {
                                        "raw_arguments": args,
                                        "preference_profile": session.preference_profile,
                                    },
                                    result=match_payload,
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

                    if match_payload and match_payload.get("ok"):
                        if trace:
                            trace.log_llm_request("summarize", messages)
                        try:
                            t_sum = time.perf_counter()
                            first_token_ms = None
                            stream = await llm_client.chat.completions.create(
                                model=LLM_MODEL,
                                messages=messages,
                                temperature=0.3,
                                max_tokens=600,
                                stream=True,
                            )
                            async for chunk in stream:
                                if await _client_gone():
                                    yield await _abort_and_signal()
                                    return
                                if not chunk.choices:
                                    continue
                                delta = chunk.choices[0].delta
                                if delta and delta.content:
                                    if first_token_ms is None:
                                        first_token_ms = (time.perf_counter() - t_sum) * 1000
                                    final_reply += delta.content
                                    yield _sse("token", {"text": delta.content})
                            if trace:
                                extra = {}
                                if first_token_ms is not None:
                                    extra["first_token_ms"] = round(first_token_ms, 1)
                                extra["reply_chars"] = len(final_reply)
                                trace.mark(
                                    "llm_summarize",
                                    (time.perf_counter() - t_sum) * 1000,
                                    **extra,
                                )
                        except Exception as e:
                            logger.exception("总结流式失败")
                            n = candidate_total or len(candidates)
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
                        actual_count = candidate_total or len(candidates)
                        if candidates and str(actual_count) not in (final_reply or ""):
                            extra = f"\n\n（本轮实际匹配 {actual_count} 位，下方展示排名靠前的候选人）"
                            final_reply = (final_reply or "").rstrip() + extra
                            yield _sse("token", {"text": extra})
                            if trace:
                                trace.add("reply_count_corrected", candidates_count=actual_count)
                        break

                    if round_i >= max_rounds - 1:
                        err = (match_payload or {}).get("error") or "画像格式无效"
                        final_reply = (
                            f"没能生成合法偏好画像（{err}）。"
                            "请再用一句话说清必须条件和偏好，例如：必须O型，身高最好175以上。"
                        )
                        yield _sse("error", {"message": final_reply})
                        yield _sse("token", {"text": "\n\n" + final_reply})
                        logger.warning("preference profile invalid after retry: %s", err)

            if await _client_gone():
                yield await _abort_and_signal()
                return

            if not final_reply:
                final_reply = "已处理您的请求。"

            session.add_message("assistant", final_reply)
            session.end_turn()
            session_manager.put_session(session)
            turn_started = False

            yield _sse("reply", {"text": final_reply})
            if candidates:
                t_sse = time.perf_counter()
                slim_items = _slim_candidates_for_sse(candidates, prefer_hits)
                candidates_event = _sse(
                    "candidates",
                    {
                        "items": slim_items,
                        "prefer_hits": prefer_hits,
                        "total": candidate_total or len(candidates),
                        "result_set_id": match_result_id,
                        "next_cursor": match_next_cursor,
                    },
                )
                if trace:
                    trace.mark(
                        "sse_candidates",
                        (time.perf_counter() - t_sse) * 1000,
                        candidates_count=len(candidates),
                        payload_bytes=len(candidates_event.encode("utf-8")),
                    )
                yield candidates_event

            yield _sse(
                "state",
                {
                    "session_id": session.session_id,
                    "state": session.state.value,
                    "parsed_features": session.parsed_features,
                    "constraints": session.constraints,
                    "preference_profile": session.preference_profile or {},
                    "match_result_id": session.match_result_id,
                    "match_total": session.match_total,
                    "match_next_cursor": session.match_next_cursor,
                    "features_before": features_before,
                    "constraints_before": constraints_before,
                },
            )
            yield _sse("done", {})

            # 登录用户：服务端持久化
            t_persist = time.perf_counter()
            ui_messages = _history_to_ui_messages(
                session,
                candidates,
                prefer_hits,
                candidate_total=candidate_total or len(candidates),
                match_result_id=match_result_id,
                match_next_cursor=match_next_cursor,
            )
            _maybe_persist(user_id, session, ui_messages, candidates)
            if trace:
                trace.mark("persist", (time.perf_counter() - t_persist) * 1000)
                trace.mark("total", (time.perf_counter() - t_turn) * 1000)

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
                    session_manager.put_session(session)
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


def _history_to_ui_messages(
    session,
    last_candidates,
    prefer_hits=None,
    candidate_total: int | None = None,
    match_result_id: str | None = None,
    match_next_cursor: str | None = None,
) -> list[dict]:
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
        out[-1]["candidates_total"] = candidate_total or len(last_candidates)
        out[-1]["match_result_id"] = match_result_id or session.match_result_id
        out[-1]["match_next_cursor"] = match_next_cursor or session.match_next_cursor
        if prefer_hits:
            out[-1]["prefer_hits"] = prefer_hits
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
    try:
        from decimal import Decimal

        if isinstance(obj, Decimal):
            return float(obj)
    except Exception:
        pass
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    return obj


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(_sanitize(data), ensure_ascii=False)}\n\n"
