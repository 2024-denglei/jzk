"""持久生成任务租约、停止、接管与终态的真实 PostgreSQL 测试。"""

from __future__ import annotations

import os
import asyncio
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import config
from db import generation_runs_repo
from db.chat_models import GenerationStatus, TurnCommand
from db.pg import close_pools, ensure_schema
from dialogue.conversation_commands import create_turn
from dialogue.generation_events import (
    delete_generation_events,
    publish_generation_event,
    read_generation_events,
)
from dialogue.generation_processor import FallbackGenerationProcessor
from dialogue.generation_worker import GenerationWorker
from dialogue.state_schema import empty_state


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


@pytest.fixture
def generation_user(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    ensure_schema()
    email = f"generation-v2-{uuid4()}@example.test"
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        user_id = int(
            conn.execute(
                """
                INSERT INTO app.users (email, password_hash, nickname)
                VALUES (%s, 'test-only', 'generation-v2') RETURNING id
                """,
                (email,),
            ).fetchone()["id"]
        )
    try:
        yield user_id
    finally:
        close_pools()
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))


def test_generation_claim_checkpoint_trace_complete_and_terminal_protection(generation_user):
    turn = create_turn(
        generation_user,
        TurnCommand(content="持久生成", client_request_id=uuid4()),
    )
    claimed = generation_runs_repo.claim_next_generation("worker-a")
    assert claimed and claimed.id == turn.generation_id
    assert claimed.status == GenerationStatus.RUNNING and claimed.attempt_count == 1
    assert generation_runs_repo.heartbeat_generation(claimed.id, "worker-a")

    context = generation_runs_repo.load_generation_context(claimed.id, "worker-a")
    assert context["messages"][-1]["content"] == "持久生成"
    generation_runs_repo.checkpoint_generation(
        claimed.id,
        "worker-a",
        content="生成中",
        state_after=empty_state(),
    )
    generation_runs_repo.append_generation_step(
        claimed.id,
        "tool_result",
        {"tool_name": "match", "match_run_id": uuid4(), "count": 3},
        elapsed_ms=12.5,
    )
    finished = generation_runs_repo.complete_generation(
        claimed.id,
        "worker-a",
        content="最终回复",
        state_after=empty_state(),
        timings={"total_ms": 20},
    )
    assert finished.status == GenerationStatus.COMPLETED
    steps = generation_runs_repo.list_generation_steps(generation_user, claimed.id)
    assert steps and steps[0]["payload_json"]["count"] == 3

    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        message = conn.execute(
            "SELECT status, content FROM app.chat_messages WHERE id = %s",
            (turn.assistant_message_id,),
        ).fetchone()
        assert message == {"status": "completed", "content": "最终回复"}
        with pytest.raises(psycopg.errors.CheckViolation, match="generation status transition"):
            conn.execute(
                "UPDATE app.ai_generation_runs SET status = 'running' WHERE id = %s",
                (claimed.id,),
            )


def test_queued_stop_and_expired_lease_takeover(generation_user):
    queued = create_turn(
        generation_user,
        TurnCommand(content="立即停止", client_request_id=uuid4()),
    )
    stopped = generation_runs_repo.request_generation_stop(generation_user, queued.generation_id)
    assert stopped and stopped.status == GenerationStatus.STOPPED

    next_turn = create_turn(
        generation_user,
        TurnCommand(
            branch_id=queued.branch_id,
            parent_message_id=queued.assistant_message_id,
            content="租约接管",
            client_request_id=uuid4(),
        ),
        chat_id=queued.chat_id,
    )
    first = generation_runs_repo.claim_next_generation("worker-old")
    assert first and first.id == next_turn.generation_id
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute(
            "UPDATE app.ai_generation_runs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
            (first.id,),
        )
    with pytest.raises(generation_runs_repo.GenerationLeaseLost):
        generation_runs_repo.checkpoint_generation(
            first.id,
            "worker-old",
            content="过期 Worker 不得覆盖",
            state_after=empty_state(),
        )
    second = generation_runs_repo.claim_next_generation("worker-new")
    assert second and second.id == first.id and second.attempt_count == 2
    assert generation_runs_repo.heartbeat_generation(first.id, "worker-old") is False
    failed = generation_runs_repo.finish_generation_unsuccessfully(
        second.id,
        "worker-new",
        stopped=False,
        error_type="ProviderError",
        error_message="Bearer secret-token sk-supersecret",
    )
    assert failed.status == GenerationStatus.FAILED
    assert "secret-token" not in (failed.error_message_safe or "")


def test_generation_events_support_resume_from_last_event(generation_user):
    turn = create_turn(
        generation_user,
        TurnCommand(content="事件恢复", client_request_id=uuid4()),
    )
    delete_generation_events(turn.generation_id)
    first_id = publish_generation_event(turn.generation_id, "token", {"text": "A"})
    publish_generation_event(turn.generation_id, "token", {"text": "B"})
    all_events = read_generation_events(turn.generation_id)
    resumed = read_generation_events(turn.generation_id, after=first_id)
    assert [event["payload"]["text"] for event in all_events] == ["A", "B"]
    assert [event["payload"]["text"] for event in resumed] == ["B"]
    assert delete_generation_events(turn.generation_id)


def test_transient_failures_retry_until_exhausted_then_become_terminal(generation_user):
    turn = create_turn(
        generation_user,
        TurnCommand(content="重试上限", client_request_id=uuid4()),
    )
    for attempt in range(1, config.CHAT_GENERATION_MAX_ATTEMPTS + 1):
        claimed = generation_runs_repo.claim_next_generation(f"worker-{attempt}")
        assert claimed and claimed.id == turn.generation_id
        assert claimed.attempt_count == attempt
        if attempt < config.CHAT_GENERATION_MAX_ATTEMPTS:
            retrying = generation_runs_repo.release_generation_for_retry(
                claimed.id,
                f"worker-{attempt}",
                error_type="TemporaryProviderError",
                error_message="temporary",
            )
            assert retrying.status == GenerationStatus.QUEUED
        else:
            assert TEST_DATABASE_URL
            with psycopg.connect(TEST_DATABASE_URL) as conn:
                conn.execute(
                    """
                    UPDATE app.ai_generation_runs
                    SET lease_expires_at = now() - interval '1 second'
                    WHERE id = %s
                    """,
                    (claimed.id,),
                )
    assert generation_runs_repo.fail_exhausted_generations() == 1
    final = generation_runs_repo.get_generation(generation_user, turn.generation_id)
    assert final and final.status == GenerationStatus.FAILED
    assert final.error_type == "MAX_ATTEMPTS_EXCEEDED"


def test_fallback_worker_completes_task_without_any_sse_connection(generation_user):
    turn = create_turn(
        generation_user,
        TurnCommand(content="断开连接后继续", client_request_id=uuid4()),
    )
    worked = asyncio.run(
        GenerationWorker("fallback-worker", FallbackGenerationProcessor()).run_once()
    )
    assert worked is True
    final = generation_runs_repo.get_generation(generation_user, turn.generation_id)
    assert final and final.status == GenerationStatus.COMPLETED
    assert final.model == "fallback" and final.prompt_version == "fallback-v1"
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        message = conn.execute(
            "SELECT status, content FROM app.chat_messages WHERE id = %s",
            (turn.assistant_message_id,),
        ).fetchone()
    assert message["status"] == "completed"
    assert "未配置顾问模型" in message["content"]


def test_worker_claim_can_be_limited_to_internal_user_scope(generation_user):
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        internal_user = int(conn.execute(
            """
            INSERT INTO app.users (email, password_hash, nickname)
            VALUES (%s, 'test-only', 'internal-rollout') RETURNING id
            """,
            (f"internal-rollout-{uuid4()}@example.test",),
        ).fetchone()["id"])
    try:
        outside = create_turn(
            generation_user,
            TurnCommand(content="非灰度任务", client_request_id=uuid4()),
        )
        inside = create_turn(
            internal_user,
            TurnCommand(content="内部灰度任务", client_request_id=uuid4()),
        )
        claimed = generation_runs_repo.claim_next_generation(
            "internal-only-worker", frozenset({internal_user})
        )
        assert claimed and claimed.id == inside.generation_id
        assert claimed.user_id == internal_user
        generation_runs_repo.finish_generation_unsuccessfully(
            claimed.id,
            "internal-only-worker",
            stopped=False,
            error_type="TestComplete",
            error_message="test cleanup",
        )
        assert generation_runs_repo.request_generation_stop(
            generation_user, outside.generation_id
        ).status == GenerationStatus.STOPPED
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM app.users WHERE id = %s", (internal_user,))
