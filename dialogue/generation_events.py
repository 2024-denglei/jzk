"""Redis Stream 实时生成事件；PostgreSQL 始终是最终状态权威来源。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from redis.exceptions import RedisError

import config
from redis_client import get_redis_client


class GenerationEventStreamUnavailable(RuntimeError):
    pass


def generation_event_key(generation_id: UUID) -> str:
    return f"jzk:generation:{{{generation_id}}}:events"


def publish_generation_event(
    generation_id: UUID,
    event: str,
    payload: dict[str, Any] | None = None,
) -> str:
    if not event.strip() or len(event) > 80:
        raise ValueError("生成事件名称无效")
    client = get_redis_client()
    key = generation_event_key(generation_id)
    try:
        event_id = client.xadd(
            key,
            {
                "event": event,
                "payload": json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")),
            },
            maxlen=2000,
            approximate=True,
        )
        client.expire(key, config.CHAT_GENERATION_STREAM_TTL_SECONDS)
        return str(event_id)
    except RedisError as exc:
        raise GenerationEventStreamUnavailable("生成事件流暂时不可用") from exc


def read_generation_events(
    generation_id: UUID,
    *,
    after: str = "0-0",
    block_ms: int = 0,
    count: int = 100,
) -> list[dict[str, Any]]:
    client = get_redis_client()
    try:
        streams = client.xread(
            {generation_event_key(generation_id): after or "0-0"},
            count=max(1, min(int(count), 500)),
            block=max(0, min(int(block_ms), 30_000)) or None,
        )
    except RedisError as exc:
        raise GenerationEventStreamUnavailable("生成事件流暂时不可用") from exc
    events: list[dict[str, Any]] = []
    for _stream_name, entries in streams:
        for event_id, fields in entries:
            try:
                payload = json.loads(fields.get("payload") or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            events.append(
                {
                    "id": str(event_id),
                    "event": str(fields.get("event") or "unknown"),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
    return events


def delete_generation_events(generation_id: UUID) -> bool:
    try:
        return bool(get_redis_client().delete(generation_event_key(generation_id)))
    except RedisError as exc:
        raise GenerationEventStreamUnavailable("生成事件流暂时不可用") from exc
