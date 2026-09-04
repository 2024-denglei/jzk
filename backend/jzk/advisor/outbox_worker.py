"""处理 Chat 删除后的 Redis 清理和孤儿快照回收。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable
from uuid import UUID

from jzk.db import outbox_repo
from jzk.advisor.generation_events import delete_generation_events


logger = logging.getLogger(__name__)


def _uuids(payload: dict[str, Any], plural: str, singular: str) -> list[UUID]:
    raw = payload.get(plural)
    values = raw if isinstance(raw, list) else [payload.get(singular)]
    return [UUID(str(value)) for value in values if value]


class OutboxWorker:
    def __init__(self, worker_id: str):
        if not worker_id.strip():
            raise ValueError("worker_id 不能为空")
        self.worker_id = worker_id

    def run_once(self) -> bool:
        event = outbox_repo.claim_next_outbox(self.worker_id)
        if event is None:
            return False
        try:
            self._process(str(event["topic"]), dict(event.get("payload_json") or {}))
            outbox_repo.complete_outbox(int(event["id"]), self.worker_id)
        except Exception as exc:
            logger.exception("Outbox 处理失败 event_id=%s", event["id"])
            try:
                outbox_repo.fail_outbox(
                    int(event["id"]), self.worker_id, exc, int(event["attempts"])
                )
            except outbox_repo.OutboxLeaseLost:
                logger.warning("Outbox 失败回写时租约已丢失 event_id=%s", event["id"])
        return True

    def _process(self, topic: str, payload: dict[str, Any]) -> None:
        if topic in {"chat_deleted", "generation_event_cleanup"}:
            for generation_id in _uuids(payload, "generation_ids", "generation_id"):
                delete_generation_events(generation_id)
            return
        if topic == "orphan_match_run_cleanup":
            outbox_repo.delete_orphan_match_runs(
                _uuids(payload, "match_run_ids", "match_run_id")
            )
            return
        raise ValueError(f"不支持的 Outbox topic: {topic}")

    async def run_forever(
        self,
        *,
        idle_seconds: float = 0.5,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        while not (should_stop and should_stop()):
            if not self.run_once():
                await asyncio.sleep(max(0.05, idle_seconds))
