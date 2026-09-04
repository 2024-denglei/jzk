"""数据库权威 Generation Trace；保存运行元数据和经脱敏的真实 Agent 消息序列。"""

from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import UUID

from jzk.db.generation_runs_repo import append_generation_step


class GenerationTrace:
    def __init__(self, generation_id: UUID):
        self.generation_id = generation_id
        self.started = perf_counter()

    def add(self, step_type: str, **payload: Any) -> int:
        return append_generation_step(self.generation_id, step_type, payload)

    def mark(self, step_type: str, started_at: float, **payload: Any) -> int:
        elapsed_ms = max(0.0, (perf_counter() - started_at) * 1000)
        return append_generation_step(
            self.generation_id,
            step_type,
            payload,
            elapsed_ms=elapsed_ms,
        )

    def finish(self, status: str, **payload: Any) -> int:
        return append_generation_step(
            self.generation_id,
            "generation_finished",
            {"status": status, **payload},
            elapsed_ms=max(0.0, (perf_counter() - self.started) * 1000),
        )
