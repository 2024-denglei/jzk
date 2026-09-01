"""管理端分支工作区的真实 PostgreSQL 查询与审计测试。"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import config
from api import admin_chats
from db import generation_runs_repo
from db.chat_models import TurnCommand
from db.pg import close_pools, ensure_schema
from dialogue.conversation_commands import create_turn


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


@pytest.fixture
def admin_conversation(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_READ_ENABLED", True)
    ensure_schema()
    suffix = uuid4().hex
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        user_id = int(conn.execute(
            """
            INSERT INTO app.users (email, password_hash, nickname)
            VALUES (%s, 'test-only', 'admin-chat-v2') RETURNING id
            """,
            (f"admin-chat-v2-{suffix}@example.test",),
        ).fetchone()["id"])
        admin_id = int(conn.execute(
            """
            INSERT INTO admin.admin_users (username, password_hash, display_name, role)
            VALUES (%s, 'test-only', 'admin-chat-v2', 'super_admin') RETURNING id
            """,
            (f"admin-chat-v2-{suffix}",),
        ).fetchone()["id"])
    turn = create_turn(user_id, TurnCommand(content="管理端审计", client_request_id=uuid4()))
    generation_runs_repo.append_generation_step(
        turn.generation_id,
        "generation_claimed",
        {"assistant_message_id": str(turn.assistant_message_id)},
    )
    try:
        yield user_id, {"id": admin_id, "role": "super_admin"}, turn
    finally:
        close_pools()
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM admin.user_audit_logs WHERE operator_id = %s", (admin_id,))
            conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))
            conn.execute("DELETE FROM admin.admin_users WHERE id = %s", (admin_id,))


def test_admin_workspace_reads_counts_tree_path_db_trace_and_writes_audit(admin_conversation):
    user_id, operator, turn = admin_conversation
    listed = admin_chats.list_admin_conversations(
        user_id, cursor=None, limit=20, admin=operator
    )
    assert listed.items[0].id == turn.chat_id
    assert listed.items[0].message_count == 2

    tree = admin_chats.get_admin_conversation(user_id, turn.chat_id, admin=operator)
    assert tree.chat.branch_count == 1
    path = admin_chats.get_admin_message_path(
        user_id,
        turn.chat_id,
        turn.branch_id,
        before=None,
        limit=50,
        admin=operator,
    )
    assert path.items[-1].generation_id == turn.generation_id
    trace = admin_chats.get_admin_generation_trace(
        user_id,
        turn.chat_id,
        turn.generation_id,
        after_order=-1,
        limit=100,
        admin=operator,
    )
    assert trace["steps"][0]["step_type"] == "generation_claimed"

    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        actions = conn.execute(
            """
            SELECT action FROM admin.user_audit_logs
            WHERE user_id = %s AND operator_id = %s ORDER BY id
            """,
            (user_id, operator["id"]),
        ).fetchall()
    assert [row["action"] for row in actions] == [
        "view_chat_list",
        "view_chat_tree",
        "view_chat_path",
        "view_chat_trace",
    ]
