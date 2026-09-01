"""真实 PostgreSQL 约束冒烟测试；默认无 TEST_DATABASE_URL 时跳过。"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


def test_branching_schema_accepts_atomic_chat_tree_and_cascades_on_user_delete():
    assert TEST_DATABASE_URL
    conn = psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row)
    branch_id = uuid4()
    user_message_id = uuid4()
    assistant_message_id = uuid4()
    generation_id = uuid4()
    request_id = uuid4()
    email = f"chat-schema-{uuid4()}@example.test"
    try:
        user_id = conn.execute(
            """
            INSERT INTO app.users (email, password_hash, nickname)
            VALUES (%s, 'test-only', 'schema-test') RETURNING id
            """,
            (email,),
        ).fetchone()["id"]
        chat_id = conn.execute(
            """
            INSERT INTO app.chats (user_id, session_id, title, storage_version)
            VALUES (%s, %s, '测试会话', 2) RETURNING id
            """,
            (user_id, str(uuid4())),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO app.chat_branches
                (id, chat_id, name, system_name, fork_reason, created_by)
            VALUES (%s, %s, '主分支', '主分支', 'root', 'system')
            """,
            (branch_id, chat_id),
        )
        conn.execute(
            """
            INSERT INTO app.chat_messages
                (id, chat_id, created_in_branch_id, role, status, content,
                 state_after_json, depth, client_request_id, completed_at)
            VALUES (%s, %s, %s, 'user', 'completed', '你好', '{}'::jsonb, 0, %s, now())
            """,
            (user_message_id, chat_id, branch_id, request_id),
        )
        conn.execute(
            """
            INSERT INTO app.chat_messages
                (id, chat_id, created_in_branch_id, parent_message_id, role,
                 status, content, state_after_json, depth)
            VALUES (%s, %s, %s, %s, 'assistant', 'generating', '', '{}'::jsonb, 1)
            """,
            (assistant_message_id, chat_id, branch_id, user_message_id),
        )
        conn.execute(
            """
            INSERT INTO app.ai_generation_runs
                (id, user_id, chat_id, branch_id, user_message_id,
                 assistant_message_id, client_request_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                generation_id,
                user_id,
                chat_id,
                branch_id,
                user_message_id,
                assistant_message_id,
                request_id,
            ),
        )
        conn.execute(
            "UPDATE app.chat_branches SET head_message_id = %s WHERE id = %s",
            (assistant_message_id, branch_id),
        )
        conn.execute(
            """
            UPDATE app.chats
            SET active_branch_id = %s, branch_count = 1, message_count = 2
            WHERE id = %s
            """,
            (branch_id, chat_id),
        )
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        conn.commit()

        saved = conn.execute(
            """
            SELECT c.active_branch_id, c.message_count, g.status
            FROM app.chats c
            JOIN app.ai_generation_runs g ON g.chat_id = c.id
            WHERE c.id = %s
            """,
            (chat_id,),
        ).fetchone()
        assert saved == {
            "active_branch_id": branch_id,
            "message_count": 2,
            "status": "queued",
        }

        second_assistant_id = uuid4()
        conn.execute(
            """
            INSERT INTO app.chat_messages
                (id, chat_id, created_in_branch_id, parent_message_id, role,
                 status, content, state_after_json, depth)
            VALUES (%s, %s, %s, %s, 'assistant', 'generating', '', '{}'::jsonb, 1)
            """,
            (second_assistant_id, chat_id, branch_id, user_message_id),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO app.ai_generation_runs
                    (id, user_id, chat_id, branch_id, user_message_id,
                     assistant_message_id, client_request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    user_id,
                    chat_id,
                    branch_id,
                    user_message_id,
                    second_assistant_id,
                    uuid4(),
                ),
            )
        conn.rollback()

        conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))
        conn.commit()
        assert conn.execute(
            "SELECT 1 FROM app.chat_messages WHERE chat_id = %s", (chat_id,)
        ).fetchone() is None
    finally:
        conn.rollback()
        conn.execute("DELETE FROM app.users WHERE email = %s", (email,))
        conn.commit()
        conn.close()
