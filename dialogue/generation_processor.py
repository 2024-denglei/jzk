"""持久任务使用的顾问 Agent 处理器。"""

from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Any
from uuid import UUID

import config
from api.match import execute_match
from core.preference.scoring_contract import RankerUnavailable
from core.preference.schema import EXTENDED_FIELDS
from core.preference.validate import ProfileValidationError, parse_profile
from dialogue.agent_tools import (
    AGENT_SYSTEM_PROMPT,
    PROFILE_TOOL_NAMES,
    SUBMIT_PROFILE_EXTENDED_TOOL,
    SUBMIT_PROFILE_TOOL,
    build_preference_snapshot_message,
    describe_empty_tool_arguments_error,
    parse_tool_arguments,
    slim_assistant_for_llm,
    tool_failure_payload,
)
from dialogue.generation_worker import GenerationCancelled, GenerationControl, GenerationOutput

# 用户话术命中这些再挂全量 extended schema，避免每轮都带两份工具定义。
_EXTENDED_HINTS = (
    "吸烟", "抽烟", "喝酒", "不抽", "不喝",
    "病史", "疾病", "手术", "遗传", "染色体", "近亲",
    "爱好", "运动", "艺术", "旅游", "阅读", "美食",
    "发量", "发色", "发型", "胡须", "络腮", "鼻梁",
    "婚育", "结婚", "子女", "性伴侣", "性病",
)


def _select_agent_tools(
    state: dict[str, Any],
    history_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profile = state.get("preference_profile") or {}
    attrs = profile.get("attributes") if isinstance(profile, dict) else None
    if isinstance(attrs, dict) and any(name in EXTENDED_FIELDS for name in attrs):
        return [SUBMIT_PROFILE_EXTENDED_TOOL]
    latest_user = ""
    for item in reversed(history_messages):
        if item.get("role") == "user":
            latest_user = str(item.get("content") or "")
            break
    if any(hint in latest_user for hint in _EXTENDED_HINTS):
        return [SUBMIT_PROFILE_EXTENDED_TOOL]
    return [SUBMIT_PROFILE_TOOL]


def _prompt_hash(messages: list[dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _state_with_profile(
    state: dict[str, Any],
    profile_payload: dict[str, Any],
    result_set_id: str | None,
    total: int,
) -> dict[str, Any]:
    parsed = parse_profile(profile_payload).model_dump(mode="json")
    attributes = dict(parsed.get("attributes") or {})
    next_state = dict(state)
    next_state["preference_profile"] = parsed
    next_state["parsed_features"] = attributes
    next_state["constraints"] = {
        key: str(value.get("constraint") or "must")
        for key, value in attributes.items()
        if isinstance(value, dict)
    }
    next_state["dialogue_state"] = "presenting" if total > 0 else "collecting"
    next_state["latest_match_run_id"] = result_set_id
    return next_state


class FallbackGenerationProcessor:
    """开发环境无 LLM 时仍完成持久任务，不伪造匹配数量。"""

    async def __call__(self, context, control: GenerationControl) -> GenerationOutput:
        state = dict(context["state_after_user"])
        await control.set_model_metadata(
            model="fallback",
            prompt_version="fallback-v1",
            prompt_hash=hashlib.sha256(b"fallback-v1").hexdigest(),
        )
        reply = "已收到您的需求。当前未配置顾问模型，请稍后再试。"
        await control.set_state(state)
        await control.emit_token(reply)
        return GenerationOutput(content=reply, state_after=state)


class AgentGenerationProcessor:
    def __init__(self, llm_client, *, model: str | None = None):
        self.llm_client = llm_client
        self.model = model or config.LLM_MODEL

    async def __call__(
        self,
        context: dict[str, Any],
        control: GenerationControl,
    ) -> GenerationOutput:
        started = perf_counter()
        state = dict(context["state_after_user"])
        history_with_ids: list[tuple[str, dict[str, Any]]] = []
        for item in context.get("messages") or []:
            if item.get("role") not in {"user", "assistant"}:
                continue
            message_id = str(item.get("id"))
            content = str(item.get("content") or "")
            if item.get("role") == "assistant":
                content = slim_assistant_for_llm(content)
            history_with_ids.append(
                (message_id, {"role": item["role"], "content": content})
            )
        selected_history = history_with_ids[-40:]
        input_ids = [message_id for message_id, _message in selected_history]
        preference_message = build_preference_snapshot_message(
            state.get("preference_profile")
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            preference_message,
            *(message for _message_id, message in selected_history),
        ]
        agent_tools = _select_agent_tools(
            state,
            [message for _message_id, message in selected_history],
        )
        attempt_count = int(getattr(context["generation"], "attempt_count", 1) or 1)
        control.trace.add(
            "agent_message",
            role="system",
            phase="input_context",
            text=AGENT_SYSTEM_PROMPT,
            attempt_count=attempt_count,
        )
        control.trace.add(
            "agent_message",
            role="system",
            phase="input_context",
            kind="preference_snapshot",
            text=preference_message["content"],
            attempt_count=attempt_count,
        )
        for message_id, message in selected_history:
            control.trace.add(
                "agent_message",
                role=message["role"],
                phase="input_context",
                text=message["content"],
                source_message_id=message_id,
                attempt_count=attempt_count,
            )
        initial_prompt_hash = _prompt_hash(messages)
        await control.set_model_metadata(
            model=self.model,
            prompt_version="agent-v4",
            prompt_hash=initial_prompt_hash,
        )
        final_reply = ""
        match_run_id: UUID | None = None
        timings: dict[str, Any] = {}

        for round_index in range(4):
            if await control.cancelled():
                raise GenerationCancelled("generation_cancelled")
            await control.emit_event(
                "agent_stage",
                {"stage": "thinking", "round": round_index},
            )
            llm_started = perf_counter()
            control.trace.add(
                "llm_request",
                phase="tool_select",
                model=self.model,
                prompt_hash=_prompt_hash(messages),
                input_message_ids=input_ids,
                message_count=len(messages),
                round=round_index,
            )
            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=agent_tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=2048,
            )
            timings[f"tool_select_{round_index}_ms"] = round(
                (perf_counter() - llm_started) * 1000, 1
            )
            choice = response.choices[0].message
            tool_calls = list(getattr(choice, "tool_calls", None) or [])
            control.trace.add(
                "llm_response",
                phase="tool_select",
                tool_call_count=len(tool_calls),
                reply_chars=len(choice.content or ""),
            )
            if not tool_calls:
                final_reply = choice.content or "请再具体描述一下您的期望。"
                await control.set_state(state)
                await control.emit_token(final_reply)
                break

            assistant_tool_message = {
                "role": "assistant",
                "content": choice.content or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            }
            messages.append(assistant_tool_message)
            control.trace.add(
                "agent_message",
                role="assistant",
                phase="tool_call",
                text=choice.content or "",
                tool_calls=[
                    {
                        "id": call.id,
                        "name": call.function.name,
                        "arguments_text": call.function.arguments,
                    }
                    for call in tool_calls
                ],
                round=round_index,
                attempt_count=attempt_count,
            )
            match_ok = False
            for call in tool_calls:
                arguments = parse_tool_arguments(call.function.arguments, choice.content)
                await control.emit_event(
                    "agent_stage",
                    {"stage": "tool_call", "tool_name": call.function.name},
                )
                tool_started = perf_counter()
                if call.function.name not in PROFILE_TOOL_NAMES:
                    tool_payload = tool_failure_payload(f"unknown tool {call.function.name}")
                elif not arguments:
                    tool_payload = tool_failure_payload(
                        describe_empty_tool_arguments_error(call.function.arguments)
                    )
                else:
                    try:
                        match_data = execute_match(
                            arguments,
                            owner_user_id=context["generation"].user_id,
                            page_size=config.MATCH_RESULT_PAGE_SIZE_DEFAULT,
                        )
                        result_set_id = match_data.get("result_set_id")
                        total = int(match_data.get("total") or 0)
                        state = _state_with_profile(state, arguments, result_set_id, total)
                        match_run_id = UUID(result_set_id) if result_set_id else None
                        await control.set_state(state)
                        tool_payload = {
                            "ok": True,
                            "count": total,
                            "ranked_count": total,
                            "filtered_count": int(
                                match_data.get("filtered_count") or 0
                            ),
                            "match_level": match_data.get("match_level"),
                            "prefer_hits": match_data.get("prefer_hits") or [],
                            "bottlenecks": match_data.get("bottlenecks") or [],
                            "result_set_id": result_set_id,
                            "note": (
                                "匹配卡片由客户端按消息快照分页加载。"
                                f"共有 {int(match_data.get('filtered_count') or 0)} 人满足 must 硬条件；"
                                f"模型生成 {total} 人的可浏览排名。"
                            ),
                        }
                        match_ok = True
                        if match_run_id:
                            await control.emit_event(
                                "match_ready",
                                {
                                    "assistant_message_id": str(
                                        context["generation"].assistant_message_id
                                    ),
                                    "total": total,
                                },
                            )
                    except RankerUnavailable as exc:
                        tool_payload = tool_failure_payload(
                            exc,
                            retry=False,
                            note=(
                                "匹配评分服务暂时不可用。请明确告知用户稍后重试，"
                                "不要修改偏好条件，也不要编造匹配人数、代号或卡片。"
                            ),
                        )
                    except (ProfileValidationError, ValueError) as exc:
                        tool_payload = tool_failure_payload(exc)
                timings[f"tool_{round_index}_ms"] = round(
                    (perf_counter() - tool_started) * 1000, 1
                )
                control.trace.add(
                    "tool_call",
                    tool_name=call.function.name,
                    arguments=arguments,
                    ok=bool(tool_payload.get("ok")),
                    match_run_id=tool_payload.get("result_set_id"),
                    count=tool_payload.get("count"),
                )
                tool_result_text = json.dumps(tool_payload, ensure_ascii=False)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": tool_result_text,
                    }
                )
                control.trace.add(
                    "agent_message",
                    role="tool",
                    phase="tool_result",
                    text=tool_result_text,
                    tool_name=call.function.name,
                    tool_call_id=call.id,
                    ok=bool(tool_payload.get("ok")),
                    result_set_id=tool_payload.get("result_set_id"),
                    count=tool_payload.get("count"),
                    round=round_index,
                    attempt_count=attempt_count,
                )

            if not match_ok:
                if round_index < 3:
                    continue
                final_reply = "没能生成合法偏好画像，请再明确说明必须条件和偏好。"
                await control.set_state(state)
                await control.emit_token(final_reply)
                break

            summarize_started = perf_counter()
            await control.emit_event(
                "agent_stage",
                {"stage": "summarizing"},
            )
            control.trace.add(
                "llm_request",
                phase="summarize",
                model=self.model,
                prompt_hash=_prompt_hash(messages),
                input_message_ids=input_ids,
                message_count=len(messages),
            )
            stream = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=600,
                stream=True,
            )
            async for chunk in stream:
                if await control.cancelled():
                    raise GenerationCancelled("generation_cancelled")
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = str(getattr(delta, "content", None) or "")
                if text:
                    final_reply += text
                    await control.emit_token(text)
                    await control.checkpoint()
            timings["summarize_ms"] = round((perf_counter() - summarize_started) * 1000, 1)
            control.trace.add(
                "llm_response",
                phase="summarize",
                reply_chars=len(final_reply),
            )
            break

        if not final_reply:
            final_reply = "已处理您的请求。"
            await control.emit_token(final_reply)
        control.trace.add(
            "agent_message",
            role="assistant",
            phase="final",
            text=final_reply,
            match_run_id=match_run_id,
            attempt_count=attempt_count,
        )
        timings["total_ms"] = round((perf_counter() - started) * 1000, 1)
        return GenerationOutput(
            content=final_reply,
            state_after=state,
            match_run_id=match_run_id,
            timings=timings,
        )
