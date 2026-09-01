from uuid import uuid4

from dialogue import outbox_worker
from dialogue.generation_events import GenerationEventStreamUnavailable
from dialogue.outbox_worker import OutboxWorker


def test_outbox_worker_cleans_generation_streams_and_completes(monkeypatch):
    generation_ids = [uuid4(), uuid4()]
    completed = []
    deleted = []
    event = {
        "id": 12,
        "topic": "chat_deleted",
        "payload_json": {"generation_ids": [str(value) for value in generation_ids]},
        "attempts": 1,
    }
    monkeypatch.setattr(
        outbox_worker.outbox_repo,
        "claim_next_outbox",
        lambda _worker: event,
    )
    monkeypatch.setattr(
        outbox_worker,
        "delete_generation_events",
        lambda generation_id: deleted.append(generation_id) or True,
    )
    monkeypatch.setattr(
        outbox_worker.outbox_repo,
        "complete_outbox",
        lambda event_id, worker: completed.append((event_id, worker)),
    )
    monkeypatch.setattr(
        outbox_worker.outbox_repo,
        "fail_outbox",
        lambda *_args: (_ for _ in ()).throw(AssertionError("不应失败")),
    )
    assert OutboxWorker("cleanup-1").run_once() is True
    assert deleted == generation_ids
    assert completed == [(12, "cleanup-1")]


def test_outbox_worker_retries_when_redis_is_unavailable(monkeypatch):
    generation_id = uuid4()
    failures = []
    monkeypatch.setattr(
        outbox_worker.outbox_repo,
        "claim_next_outbox",
        lambda _worker: {
            "id": 13,
            "topic": "generation_event_cleanup",
            "payload_json": {"generation_id": str(generation_id)},
            "attempts": 3,
        },
    )
    monkeypatch.setattr(
        outbox_worker,
        "delete_generation_events",
        lambda _generation_id: (_ for _ in ()).throw(
            GenerationEventStreamUnavailable("redis down")
        ),
    )
    monkeypatch.setattr(
        outbox_worker.outbox_repo,
        "complete_outbox",
        lambda *_args: (_ for _ in ()).throw(AssertionError("失败任务不能完成")),
    )
    monkeypatch.setattr(
        outbox_worker.outbox_repo,
        "fail_outbox",
        lambda event_id, worker, error, attempts: failures.append(
            (event_id, worker, type(error).__name__, attempts)
        ),
    )
    assert OutboxWorker("cleanup-2").run_once() is True
    assert failures == [(13, "cleanup-2", "GenerationEventStreamUnavailable", 3)]
