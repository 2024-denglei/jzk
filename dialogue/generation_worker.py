"""与 Web/SSE 解耦的持久生成 Worker。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from time import monotonic
from typing import Any, Callable, Protocol
from uuid import UUID

import config
from db import generation_runs_repo
from db.chat_models import GenerationRunView
from db.generation_runs_repo import GenerationLeaseLost
from dialogue.generation_events import (
    GenerationEventStreamUnavailable,
    publish_generation_event,
)
from dialogue.generation_trace import GenerationTrace
from dialogue.state_schema import dump_state, load_state


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationOutput:
    content: str
    state_after: dict[str, Any]
    match_run_id: UUID | None = None
    timings: dict[str, Any] = field(default_factory=dict)


class GenerationProcessor(Protocol):
    async def __call__(
        self,
        context: dict[str, Any],
        control: "GenerationControl",
    ) -> GenerationOutput: ...


class GenerationCancelled(RuntimeError):
    pass


class GenerationControl:
    def __init__(
        self,
        run: GenerationRunView,
        worker_id: str,
        trace: GenerationTrace,
    ):
        self.run = run
        self.worker_id = worker_id
        self.trace = trace
        self._content = ""
        self._last_checkpoint_chars = 0
        self._last_checkpoint_at = monotonic()
        self._state_after: dict[str, Any] | None = None

    @property
    def content(self) -> str:
        return self._content

    async def emit_token(self, text: str) -> None:
        if not text:
            return
        self._content += text
        await self._publish("token", {"text": text})

    async def set_state(self, state_after: dict[str, Any]) -> None:
        self._state_after = dump_state(state_after)

    async def emit_event(self, event: str, payload: dict[str, Any]) -> None:
        await self._publish(event, payload)

    async def set_model_metadata(
        self,
        *,
        model: str,
        prompt_version: str,
        prompt_hash: str,
    ) -> None:
        generation_runs_repo.set_generation_model_metadata(
            self.run.id,
            self.worker_id,
            model=model,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
        )

    async def checkpoint(self, *, force: bool = False) -> bool:
        if self._state_after is None:
            return False
        elapsed = monotonic() - self._last_checkpoint_at
        chars = len(self._content) - self._last_checkpoint_chars
        if not force and (
            elapsed < config.CHAT_GENERATION_CHECKPOINT_INTERVAL_SECONDS
            and chars < config.CHAT_GENERATION_CHECKPOINT_CHARS
        ):
            return False
        generation_runs_repo.checkpoint_generation(
            self.run.id,
            self.worker_id,
            content=self._content,
            state_after=self._state_after,
        )
        self._last_checkpoint_at = monotonic()
        self._last_checkpoint_chars = len(self._content)
        await self._publish(
            "state_checkpoint",
            {"assistant_message_id": str(self.run.assistant_message_id), "chars": len(self._content)},
        )
        return True

    async def cancelled(self) -> bool:
        return generation_runs_repo.generation_cancel_requested(
            self.run.id,
            self.worker_id,
        )

    async def _publish(self, event: str, payload: dict[str, Any]) -> None:
        try:
            publish_generation_event(self.run.id, event, payload)
        except GenerationEventStreamUnavailable:
            logger.warning("Redis 生成事件写入失败 generation_id=%s", self.run.id)


class GenerationWorker:
    def __init__(self, worker_id: str, processor: GenerationProcessor):
        if not worker_id.strip():
            raise ValueError("worker_id 不能为空")
        self.worker_id = worker_id
        self.processor = processor

    async def run_once(self) -> bool:
        generation_runs_repo.fail_exhausted_generations()
        run = generation_runs_repo.claim_next_generation(self.worker_id)
        if run is None:
            return False

        trace = GenerationTrace(run.id)
        control = GenerationControl(run, self.worker_id, trace)
        await control._publish(
            "generation_status",
            {"status": "running", "attempt_count": run.attempt_count},
        )
        try:
            trace.add(
                "generation_claimed",
                chat_id=run.chat_id,
                branch_id=run.branch_id,
                user_message_id=run.user_message_id,
                assistant_message_id=run.assistant_message_id,
                attempt_count=run.attempt_count,
            )
        except Exception:
            logger.exception("写入 generation_claimed Trace 失败")

        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(run.id, stop_heartbeat))
        try:
            context = generation_runs_repo.load_generation_context(
                run.id,
                self.worker_id,
            )
            state = load_state(
                context["state_after_user"],
                schema_version=context["state_schema_version"],
                recoverable=context["state_recoverable"],
            ).model_dump(mode="json")
            context["state_after_user"] = state
            if await control.cancelled():
                await self._stop(run, trace, control)
                return True

            output = await self.processor(context, control)
            final_state = dump_state(output.state_after)
            await control.set_state(final_state)
            if not control.content and output.content:
                await control.emit_token(output.content)
            final_content = output.content or control.content
            await control.checkpoint(force=True)
            if await control.cancelled():
                await self._stop(run, trace, control)
                return True
            finished = generation_runs_repo.complete_generation(
                run.id,
                self.worker_id,
                content=final_content,
                state_after=final_state,
                match_run_id=output.match_run_id,
                timings=output.timings,
            )
            try:
                trace.finish(
                    "completed",
                    assistant_message_id=run.assistant_message_id,
                    match_run_id=output.match_run_id,
                    reply_chars=len(final_content),
                )
            except Exception:
                logger.exception("写入 generation completed Trace 失败")
            await control._publish(
                "completed",
                {
                    "status": finished.status.value,
                    "assistant_message_id": str(run.assistant_message_id),
                    "match_run_id": str(output.match_run_id) if output.match_run_id else None,
                },
            )
            return True
        except GenerationCancelled:
            await self._stop(run, trace, control)
            return True
        except GenerationLeaseLost:
            logger.warning("生成任务租约丢失 generation_id=%s", run.id)
            return True
        except Exception as exc:
            logger.exception("持久生成任务失败 generation_id=%s", run.id)
            if run.attempt_count < config.CHAT_GENERATION_MAX_ATTEMPTS:
                try:
                    retrying = generation_runs_repo.release_generation_for_retry(
                        run.id,
                        self.worker_id,
                        error_type=type(exc).__name__[:80],
                        error_message=exc,
                    )
                except GenerationLeaseLost:
                    return True
                try:
                    trace.add(
                        "attempt_failed",
                        attempt_count=run.attempt_count,
                        error_type=type(exc).__name__[:80],
                    )
                except Exception:
                    logger.exception("写入 generation retry Trace 失败")
                await control._publish(
                    "generation_status",
                    {
                        "status": retrying.status.value,
                        "attempt_count": run.attempt_count,
                        "retrying": True,
                    },
                )
                return True
            try:
                finished = generation_runs_repo.finish_generation_unsuccessfully(
                    run.id,
                    self.worker_id,
                    stopped=False,
                    error_type=type(exc).__name__[:80],
                    error_message=exc,
                )
            except GenerationLeaseLost:
                return True
            try:
                trace.finish("failed", error_type=type(exc).__name__[:80])
            except Exception:
                logger.exception("写入 generation failed Trace 失败")
            await control._publish(
                "failed",
                {"status": finished.status.value, "error_type": type(exc).__name__[:80]},
            )
            return True
        finally:
            stop_heartbeat.set()
            await heartbeat_task

    async def _stop(
        self,
        run: GenerationRunView,
        trace: GenerationTrace,
        control: GenerationControl,
    ) -> None:
        finished = generation_runs_repo.finish_generation_unsuccessfully(
            run.id,
            self.worker_id,
            stopped=True,
        )
        try:
            trace.finish("stopped", assistant_message_id=run.assistant_message_id)
        except Exception:
            logger.exception("写入 generation stopped Trace 失败")
        await control._publish("stopped", {"status": finished.status.value})

    async def _heartbeat_loop(self, generation_id: UUID, stop: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=config.CHAT_GENERATION_HEARTBEAT_SECONDS,
                )
                return
            except TimeoutError:
                alive = generation_runs_repo.heartbeat_generation(
                    generation_id,
                    self.worker_id,
                )
                if not alive:
                    return

    async def run_forever(
        self,
        *,
        idle_seconds: float = 0.5,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        while not (should_stop and should_stop()):
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(max(0.05, idle_seconds))
