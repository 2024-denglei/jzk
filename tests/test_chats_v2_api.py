"""用户端 V2 API 的真实所有权、分支、停止和硬删除测试。"""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
import pytest
from psycopg.rows import dict_row

import config
from api.auth_utils import get_current_user_id
from api.chats import message_router, router as chats_router
from api.generation_events import router as generations_router
from db.pg import close_pools, ensure_schema


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


@pytest.fixture
def v2_client(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_READ_ENABLED", True)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_ENABLED", True)
    ensure_schema()
    emails = [f"v2-api-{uuid4()}@example.test" for _ in range(2)]
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        user_ids = [
            int(
                conn.execute(
                    """
                    INSERT INTO app.users (email, password_hash, nickname)
                    VALUES (%s, 'test-only', 'v2-api') RETURNING id
                    """,
                    (email,),
                ).fetchone()["id"]
            )
            for email in emails
        ]
    current = {"user_id": user_ids[0]}
    app = FastAPI()
    app.include_router(chats_router)
    app.include_router(message_router)
    app.include_router(generations_router)
    app.dependency_overrides[get_current_user_id] = lambda: current["user_id"]
    try:
        yield TestClient(app), current, user_ids
    finally:
        close_pools()
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute(
                """
                DELETE FROM app.outbox_events event
                USING app.chat_deletion_audit audit
                WHERE event.aggregate_id = audit.chat_id::text
                  AND audit.user_id = ANY(%s)
                """,
                (user_ids,),
            )
            conn.execute(
                "DELETE FROM app.chat_deletion_audit WHERE user_id = ANY(%s)",
                (user_ids,),
            )
            conn.execute("DELETE FROM app.users WHERE id = ANY(%s)", (user_ids,))


def test_v2_api_branch_lifecycle_ownership_and_irreversible_delete(v2_client):
    client, current, (user_a, user_b) = v2_client
    first_request = str(uuid4())
    first = client.post(
        "/api/chats/turns",
        json={"content": "第一条", "client_request_id": first_request},
    )
    assert first.status_code == 202
    created = first.json()
    chat_id = created["chat_id"]
    root_branch = created["branch_id"]

    replay = client.post(
        "/api/chats/turns",
        json={"content": "重试正文", "client_request_id": first_request},
    )
    assert replay.status_code == 202
    assert replay.json()["generation_id"] == created["generation_id"]
    assert replay.json()["idempotent_replay"] is True

    current["user_id"] = user_b
    assert client.get(f"/api/chats/{chat_id}").status_code == 404
    assert client.get(
        f"/api/chats/{chat_id}/branches/{root_branch}/messages"
    ).status_code == 404
    assert client.get(
        f"/api/messages/{created['assistant_message_id']}/match-results"
    ).status_code == 404
    assert client.post(f"/api/generations/{created['generation_id']}/stop").status_code == 404
    current["user_id"] = user_a

    stopped = client.post(f"/api/generations/{created['generation_id']}/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    stream = client.get(f"/api/generations/{created['generation_id']}/events")
    assert stream.status_code == 200
    assert "event: generation_status" in stream.text
    assert '"status":"stopped"' in stream.text

    rewind = client.post(
        f"/api/chats/{chat_id}/turns",
        json={
            "branch_id": root_branch,
            "parent_message_id": created["assistant_message_id"],
            "action": "rewind_continue",
            "content": "从这里建立分支",
            "client_request_id": str(uuid4()),
        },
    )
    assert rewind.status_code == 202
    fork = rewind.json()
    assert fork["branch_created"] is True
    client.post(f"/api/generations/{fork['generation_id']}/stop")

    tree = client.get(f"/api/chats/{chat_id}")
    assert tree.status_code == 200
    assert tree.json()["chat"]["branch_count"] == 2
    assert len(tree.json()["branches"]) == 2
    path = client.get(
        f"/api/chats/{chat_id}/branches/{fork['branch_id']}/messages?limit=20"
    )
    assert path.status_code == 200
    assert [item["content"] for item in path.json()["items"]][-2] == "从这里建立分支"
    assert path.json()["items"][-1]["generation_id"] == fork["generation_id"]

    assert client.patch(f"/api/chats/{chat_id}", json={"title": "新标题"}).status_code == 200
    assert client.patch(
        f"/api/chats/{chat_id}/branches/{root_branch}",
        json={"name": "旧主线", "is_archived": True},
    ).status_code == 200
    active_archive = client.patch(
        f"/api/chats/{chat_id}/branches/{fork['branch_id']}",
        json={"is_archived": True},
    )
    assert active_archive.status_code == 409

    message_match = client.get(
        f"/api/messages/{created['assistant_message_id']}/match-results"
    )
    assert message_match.status_code == 404
    assert message_match.json()["detail"]["code"] == "MATCH_SNAPSHOT_NOT_FOUND"

    delete_request = str(uuid4())
    unconfirmed = client.request(
        "DELETE",
        f"/api/chats/{chat_id}",
        json={"confirm_irreversible": False, "request_id": delete_request},
    )
    assert unconfirmed.status_code == 400
    deleted = client.request(
        "DELETE",
        f"/api/chats/{chat_id}",
        json={"confirm_irreversible": True, "request_id": delete_request},
    )
    assert deleted.status_code == 200
    assert deleted.json()["message_count"] == 4
    assert client.get(f"/api/chats/{chat_id}").status_code == 404
    replay_delete = client.request(
        "DELETE",
        f"/api/chats/{chat_id}",
        json={"confirm_irreversible": True, "request_id": delete_request},
    )
    assert replay_delete.status_code == 200
    assert replay_delete.json()["idempotent_replay"] is True

    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        assert conn.execute(
            "SELECT 1 FROM app.chat_messages WHERE chat_id = %s", (chat_id,)
        ).fetchone() is None
        outbox = conn.execute(
            "SELECT payload_json FROM app.outbox_events WHERE aggregate_id = %s",
            (str(chat_id),),
        ).fetchone()
        assert outbox and set(outbox["payload_json"]) == {"generation_ids"}


def test_v2_flags_fail_closed(v2_client, monkeypatch):
    client, _current, _users = v2_client
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_READ_ENABLED", False)
    assert client.get("/api/chats").status_code == 503
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_ENABLED", False)
    assert client.post(
        "/api/chats/turns",
        json={"content": "关闭", "client_request_id": str(uuid4())},
    ).status_code == 503


def test_regenerate_action_is_no_longer_part_of_public_api(v2_client):
    client, _current, _users = v2_client
    response = client.post(
        "/api/chats/turns",
        json={
            "action": "regenerate",
            "derived_from_message_id": str(uuid4()),
            "client_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 422


def test_rollback_blocks_new_turns_but_keeps_stop_and_delete_available(v2_client, monkeypatch):
    client, _current, _users = v2_client
    created = client.post(
        "/api/chats/turns",
        json={"content": "灰度回滚", "client_request_id": str(uuid4())},
    ).json()
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_ENABLED", False)
    blocked = client.post(
        "/api/chats/turns",
        json={"content": "不得新建", "client_request_id": str(uuid4())},
    )
    assert blocked.status_code == 503
    assert client.post(f"/api/generations/{created['generation_id']}/stop").status_code == 200
    deleted = client.request(
        "DELETE",
        f"/api/chats/{created['chat_id']}",
        json={"confirm_irreversible": True, "request_id": str(uuid4())},
    )
    assert deleted.status_code == 200


def test_write_rollout_rejects_user_outside_cohort(v2_client, monkeypatch):
    client, _current, _users = v2_client
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_PERCENT", 0)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_USER_IDS", frozenset())
    response = client.post(
        "/api/chats/turns",
        json={"content": "尚未灰度", "client_request_id": str(uuid4())},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CHAT_STORAGE_V2_WRITE_NOT_IN_ROLLOUT"
