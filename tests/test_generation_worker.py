import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from db.chat_models import GenerationRunView, GenerationStatus
from db.generation_runs_repo import GenerationTraceValidationError, sanitize_trace_payload
from dialogue import generation_trace, generation_worker
from dialogue.generation_worker import GenerationOutput, GenerationWorker


def _run_view():
    return GenerationRunView(
        id=uuid4(),
        user_id=7,
        chat_id=12,
        branch_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        status=GenerationStatus.RUNNING,
        attempt_count=1,
        queued_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )


def test_database_trace_rejects_full_messages_and_redacts_secrets():
    with pytest.raises(GenerationTraceValidationError, match="禁止保存字段"):
        sanitize_trace_payload({"messages": [{"content": "完整正文"}]})
    clean = sanitize_trace_payload(
        {"generation_id": uuid4(), "authorization": "Bearer abc.def.secret", "count": 3}
    )
    assert clean["authorization"] == "[redacted]"
    assert clean["count"] == 3


def test_worker_completes_generation_even_when_event_stream_is_unavailable(monkeypatch):
    run = _run_view()
    events = []
    completed = []
    steps = []

    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "fail_exhausted_generations",
        lambda: 0,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "claim_next_generation",
        lambda _worker: run,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "load_generation_context",
        lambda *_args: {
            "generation": run,
            "messages": [{"id": str(run.user_message_id), "role": "user", "content": "你好"}],
            "state_after_user": {"state_schema_version": 1},
            "state_schema_version": 1,
            "state_recoverable": True,
        },
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "generation_cancel_requested",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "heartbeat_generation",
        lambda *_args: False,
    )
    monkeypatch.setattr(generation_worker.config, "CHAT_GENERATION_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "checkpoint_generation",
        lambda *_args, **kwargs: events.append(("checkpoint", kwargs["content"])),
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "complete_generation",
        lambda *_args, **kwargs: completed.append(kwargs) or run.model_copy(
            update={"status": GenerationStatus.COMPLETED, "finished_at": datetime.now(timezone.utc)}
        ),
    )
    monkeypatch.setattr(
        generation_trace,
        "append_generation_step",
        lambda _gid, step, payload=None, **_kwargs: steps.append((step, payload)) or len(steps),
    )
    monkeypatch.setattr(
        generation_worker,
        "publish_generation_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            generation_worker.GenerationEventStreamUnavailable("redis down")
        ),
    )

    async def processor(context, control):
        assert context["messages"][-1]["content"] == "你好"
        await control.set_state({"state_schema_version": 1, "dialogue_state": "collecting"})
        await control.emit_token("完成")
        return GenerationOutput(
            content="完成",
            state_after={"state_schema_version": 1, "dialogue_state": "collecting"},
        )

    assert asyncio.run(
        asyncio.wait_for(GenerationWorker("worker-1", processor).run_once(), timeout=2)
    ) is True
    assert completed[0]["content"] == "完成"
    assert events[-1] == ("checkpoint", "完成")
    assert [step[0] for step in steps] == ["generation_claimed", "generation_finished"]


def test_worker_honors_cancel_before_processor(monkeypatch):
    run = _run_view()
    stopped = []
    processor_called = False
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "fail_exhausted_generations",
        lambda: 0,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "claim_next_generation",
        lambda _worker: run,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "load_generation_context",
        lambda *_args: {
            "generation": run,
            "messages": [],
            "state_after_user": {"state_schema_version": 1},
            "state_schema_version": 1,
            "state_recoverable": True,
        },
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "generation_cancel_requested",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "heartbeat_generation",
        lambda *_args: False,
    )
    monkeypatch.setattr(generation_worker.config, "CHAT_GENERATION_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "finish_generation_unsuccessfully",
        lambda *_args, **kwargs: stopped.append(kwargs) or run.model_copy(
            update={"status": GenerationStatus.STOPPED}
        ),
    )
    monkeypatch.setattr(
        generation_trace,
        "append_generation_step",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(generation_worker, "publish_generation_event", lambda *_args: "1-0")

    async def processor(_context, _control):
        nonlocal processor_called
        processor_called = True
        raise AssertionError("不应调用")

    assert asyncio.run(
        asyncio.wait_for(GenerationWorker("worker-1", processor).run_once(), timeout=2)
    ) is True
    assert stopped == [{"stopped": True}]
    assert processor_called is False


def test_worker_passes_internal_user_scope_to_claim(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "fail_exhausted_generations",
        lambda: 0,
    )
    monkeypatch.setattr(
        generation_worker.generation_runs_repo,
        "claim_next_generation",
        lambda worker_id, scope: calls.append((worker_id, scope)) or None,
    )

    async def processor(_context, _control):
        raise AssertionError("没有任务时不应调用")

    worked = asyncio.run(
        GenerationWorker(
            "internal-worker",
            processor,
            allowed_user_ids=frozenset({7, 9}),
        ).run_once()
    )
    assert worked is False
    assert calls == [("internal-worker", frozenset({7, 9}))]
