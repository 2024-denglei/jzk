"""持久生成任务状态、停止和可重连 SSE。"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

import config
from api.auth_utils import get_current_user_id
from db import generation_runs_repo
from db.chat_models import GenerationStatus
from dialogue.generation_events import (
    GenerationEventStreamUnavailable,
    publish_generation_event,
    read_generation_events,
)


router = APIRouter(prefix="/api/generations", tags=["generations-v2"])
_TERMINAL = {
    GenerationStatus.COMPLETED,
    GenerationStatus.STOPPED,
    GenerationStatus.FAILED,
}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _require_read() -> None:
    if not config.CHAT_STORAGE_V2_READ_ENABLED:
        raise _error(503, "CHAT_STORAGE_V2_READ_DISABLED", "新版对话读取尚未启用")


def _sse(event: str, payload: dict, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


async def _owned_generation(user_id: int, generation_id: UUID):
    run = await run_in_threadpool(generation_runs_repo.get_generation, user_id, generation_id)
    if run is None:
        raise _error(404, "GENERATION_NOT_FOUND", "生成任务不存在")
    return run


@router.get("/{generation_id}")
async def get_generation_status(
    generation_id: UUID,
    user_id: int = Depends(get_current_user_id),
):
    _require_read()
    return await _owned_generation(user_id, generation_id)


@router.post("/{generation_id}/stop")
async def stop_generation(
    generation_id: UUID,
    user_id: int = Depends(get_current_user_id),
):
    _require_read()
    run = await run_in_threadpool(
        generation_runs_repo.request_generation_stop,
        user_id,
        generation_id,
    )
    if run is None:
        raise _error(404, "GENERATION_NOT_FOUND", "生成任务不存在")
    try:
        await run_in_threadpool(
            publish_generation_event,
            generation_id,
            "generation_status",
            {"status": run.status.value, "cancel_requested": True},
        )
    except GenerationEventStreamUnavailable:
        pass
    return run


@router.get("/{generation_id}/events")
async def stream_generation_events(
    generation_id: UUID,
    request: Request,
    after: str | None = Query(default=None, max_length=64),
    user_id: int = Depends(get_current_user_id),
):
    _require_read()
    initial = await _owned_generation(user_id, generation_id)
    last_id = after or request.headers.get("last-event-id") or "0-0"

    async def stream():
        nonlocal last_id
        yield _sse(
            "generation_status",
            {
                "status": initial.status.value,
                "assistant_message_id": str(initial.assistant_message_id),
                "attempt_count": initial.attempt_count,
            },
        )
        if initial.status in _TERMINAL:
            return
        while not await request.is_disconnected():
            try:
                events = await run_in_threadpool(
                    read_generation_events,
                    generation_id,
                    after=last_id,
                    block_ms=10_000,
                    count=100,
                )
            except GenerationEventStreamUnavailable:
                events = []
                await asyncio.sleep(1)
            for item in events:
                last_id = item["id"]
                yield _sse(item["event"], item["payload"], last_id)
            current = await run_in_threadpool(
                generation_runs_repo.get_generation,
                user_id,
                generation_id,
            )
            if current is None:
                return
            if current.status in _TERMINAL:
                if not events or events[-1]["event"] not in {"completed", "stopped", "failed"}:
                    yield _sse(
                        current.status.value,
                        {
                            "status": current.status.value,
                            "assistant_message_id": str(current.assistant_message_id),
                        },
                    )
                return
            if not events:
                yield ": keepalive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
