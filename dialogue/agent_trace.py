"""旧 Agent Trace 只保留历史文件读取；新写入已迁移到 PostgreSQL。"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

def _default_trace_dir() -> str:
    from config import TRACE_DIR

    return TRACE_DIR


def _json_safe(obj: Any) -> Any:
    """尽量可 JSON 序列化。"""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _json_safe(obj.model_dump())
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return _json_safe(obj.dict())
        except Exception:
            pass
    return str(obj)


def _slim_messages(messages: list[dict], max_chars: int = 4000) -> list[dict]:
    """缩短超长 message content，保留 tool_calls。"""
    out = []
    for m in messages or []:
        item = {k: v for k, v in m.items() if k != "content"}
        content = m.get("content")
        if isinstance(content, str) and len(content) > max_chars:
            item["content"] = content[:max_chars] + f"…[truncated {len(content) - max_chars} chars]"
        else:
            item["content"] = content
        out.append(_json_safe(item))
    return out


def _safe_name(s: str, max_len: int = 80) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(s))[:max_len]


class AgentTrace:
    """单轮对话的 trace 收集器。"""

    def __init__(
        self,
        session_id: str,
        user_message: str,
        user_id: int | None = None,
        model: str | None = None,
    ):
        self.trace_id = str(uuid.uuid4())
        self.session_id = session_id
        self.user_id = user_id
        self.user_message = user_message
        self.model = model
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps: list[dict[str, Any]] = []
        self.final_reply: str | None = None
        self.candidates_count: int = 0
        self.parsed_features: dict | None = None
        self.constraints: dict | None = None
        self.error: str | None = None
        self.timings: dict[str, float] = {}

    def mark(self, stage: str, elapsed_ms: float, **extra: Any) -> None:
        self.timings[stage] = round(float(elapsed_ms), 1)
        self.add("timing", stage=stage, elapsed_ms=self.timings[stage], **extra)

    def add(self, step_type: str, **payload: Any) -> None:
        self.steps.append(
            {
                "type": step_type,
                "ts": datetime.now(timezone.utc).isoformat(),
                **_json_safe(payload),
            }
        )

    def log_llm_request(self, phase: str, messages: list[dict], **extra: Any) -> None:
        self.add(
            "llm_request",
            phase=phase,
            model=self.model,
            messages=_slim_messages(messages),
            **extra,
        )

    def log_llm_response(
        self,
        phase: str,
        content: str | None = None,
        tool_calls: list | None = None,
        **extra: Any,
    ) -> None:
        self.add(
            "llm_response",
            phase=phase,
            content=content,
            tool_calls=_json_safe(tool_calls) if tool_calls else None,
            **extra,
        )

    def log_tool_call(
        self,
        name: str,
        arguments: dict | None,
        result: Any = None,
        tool_call_id: str | None = None,
    ) -> None:
        # result 可能很大：若是匹配 payload 直接记；若是长字符串截断
        result_out = result
        if isinstance(result, str) and len(result) > 3000:
            result_out = result[:3000] + f"…[truncated {len(result) - 3000} chars]"
        elif isinstance(result, dict) and "top_preview" in result:
            result_out = {
                "count": result.get("count"),
                "match_level": result.get("match_level"),
                "feature_summary": result.get("feature_summary"),
                "bottlenecks": result.get("bottlenecks"),
                "top_preview": result.get("top_preview"),
            }
        self.add(
            "tool_call",
            name=name,
            tool_call_id=tool_call_id,
            arguments=_json_safe(arguments or {}),
            result=_json_safe(result_out),
        )

    def finish(
        self,
        final_reply: str | None = None,
        candidates_count: int = 0,
        parsed_features: dict | None = None,
        constraints: dict | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        self.final_reply = final_reply
        self.candidates_count = candidates_count
        self.parsed_features = parsed_features
        self.constraints = constraints
        self.error = error
        record = self.to_dict()
        write_trace(record)
        return record

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "user_id": self.user_id,
            "model": self.model,
            "user_message": self.user_message,
            "steps": self.steps,
            "final_reply": self.final_reply,
            "candidates_count": self.candidates_count,
            "parsed_features": _json_safe(self.parsed_features),
            "constraints": _json_safe(self.constraints),
            "error": self.error,
            "timings": dict(self.timings),
        }


def write_trace(record: dict[str, Any]) -> None:
    """旧入口不再写本地文件；V2 GenerationTrace 统一写 PostgreSQL。"""
    logger.debug(
        "legacy local agent trace disabled trace_id=%s",
        record.get("trace_id"),
    )


def read_session_traces(session_id: str, user_id: int | None = None) -> list[dict[str, Any]]:
    """读取单个会话的全部 turn trace，并校验会话与用户归属。"""
    if not session_id:
        return []

    session_dir = os.path.join(_default_trace_dir(), "sessions", _safe_name(session_id))
    if not os.path.isdir(session_dir):
        return []

    records: list[dict[str, Any]] = []
    try:
        filenames = sorted(name for name in os.listdir(session_dir) if name.endswith(".json"))
    except OSError:
        logger.exception("读取 session trace 目录失败: %s", session_dir)
        return []

    for filename in filenames:
        path = os.path.join(session_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("跳过无效 session trace: %s", path)
            continue

        if not isinstance(record, dict) or str(record.get("session_id") or "") != str(session_id):
            continue
        trace_user_id = record.get("user_id")
        if user_id is not None and trace_user_id is not None and str(trace_user_id) != str(user_id):
            continue
        records.append(record)

    records.sort(key=lambda item: (
        str(item.get("started_at") or ""),
        str(item.get("finished_at") or ""),
        str(item.get("trace_id") or ""),
    ))
    return records
