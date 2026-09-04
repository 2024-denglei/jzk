"""Outbox 租约接管和 Redis 清理的真实 PostgreSQL 测试。"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from jzk import config
from jzk.db import outbox_repo
from jzk.db.pg import close_pools, ensure_schema
from jzk.advisor.generation_events import (
    delete_generation_events,
    publish_generation_event,
    read_generation_events,
)
from jzk.advisor.outbox_worker import OutboxWorker


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


@pytest.fixture
def outbox_database(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    ensure_schema()
    try:
        yield
    finally:
        close_pools()


def test_expired_outbox_lease_is_reclaimed_with_fencing(outbox_database):
    assert TEST_DATABASE_URL
    dedupe = f"outbox-lease-{uuid4()}"
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        event_id = int(conn.execute(
            """
            INSERT INTO app.outbox_events
                (topic, aggregate_type, aggregate_id, dedupe_key, available_at)
            VALUES ('generation_event_cleanup', 'generation', 'lease-test', %s, 'epoch')
            RETURNING id
            """,
            (dedupe,),
        ).fetchone()["id"])
    try:
        first = outbox_repo.claim_next_outbox("outbox-old")
        assert first and first["id"] == event_id
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute(
                "UPDATE app.outbox_events SET locked_at = now() - interval '2 minutes' WHERE id = %s",
                (event_id,),
            )
        second = outbox_repo.claim_next_outbox("outbox-new")
        assert second and second["id"] == event_id and second["attempts"] == 2
        with pytest.raises(outbox_repo.OutboxLeaseLost):
            outbox_repo.complete_outbox(event_id, "outbox-old")
        outbox_repo.complete_outbox(event_id, "outbox-new")
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM app.outbox_events WHERE id = %s", (event_id,))


def test_outbox_worker_deletes_redis_generation_stream(outbox_database):
    assert TEST_DATABASE_URL
    generation_id = uuid4()
    dedupe = f"outbox-redis-{uuid4()}"
    publish_generation_event(generation_id, "token", {"text": "temporary"})
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        event_id = int(conn.execute(
            """
            INSERT INTO app.outbox_events (
                topic, aggregate_type, aggregate_id, dedupe_key,
                payload_json, available_at
            ) VALUES (
                'generation_event_cleanup', 'generation', %s, %s,
                jsonb_build_object('generation_id', %s::text), 'epoch'
            ) RETURNING id
            """,
            (str(generation_id), dedupe, str(generation_id)),
        ).fetchone()["id"])
    try:
        assert read_generation_events(generation_id)
        assert OutboxWorker("outbox-redis").run_once() is True
        assert read_generation_events(generation_id) == []
        with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
            status = conn.execute(
                "SELECT status FROM app.outbox_events WHERE id = %s", (event_id,)
            ).fetchone()["status"]
        assert status == "completed"
    finally:
        delete_generation_events(generation_id)
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM app.outbox_events WHERE id = %s", (event_id,))
