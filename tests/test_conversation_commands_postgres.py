"""分支命令与共享查询的真实 PostgreSQL 集成测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import config
from db.chat_models import TurnAction, TurnCommand
from db.pg import close_pools, ensure_schema
from dialogue.conversation_commands import create_turn
from dialogue.conversation_queries import ConversationQueryService


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


@pytest.fixture
def v2_user(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    ensure_schema()
    email = f"conversation-v2-{uuid4()}@example.test"
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        user_id = conn.execute(
            """
            INSERT INTO app.users (email, password_hash, nickname)
            VALUES (%s, 'test-only', 'conversation-v2') RETURNING id
            """,
            (email,),
        ).fetchone()["id"]
    try:
        yield int(user_id)
    finally:
        close_pools()
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))


def _finish_generation(result, content="AI 回复"):
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute(
            """
            UPDATE app.chat_messages
            SET status = 'completed', content = %s, completed_at = now()
            WHERE id = %s
            """,
            (content, result.assistant_message_id),
        )
        conn.execute(
            """
            UPDATE app.ai_generation_runs
            SET status = 'running', started_at = now()
            WHERE id = %s
            """,
            (result.generation_id,),
        )
        conn.execute(
            """
            UPDATE app.ai_generation_runs
            SET status = 'completed', finished_at = now()
            WHERE id = %s
            """,
            (result.generation_id,),
        )


def test_edit_rewrites_current_line_while_explicit_branch_preserves_its_path(v2_user):
    root = create_turn(
        v2_user,
        TurnCommand(content="第一条需求", client_request_id=uuid4()),
    )
    _finish_generation(root, "第一条回复")
    replay = create_turn(
        v2_user,
        TurnCommand(content="不会重复创建", client_request_id=uuid4()),
        chat_id=root.chat_id,
    )
    _finish_generation(replay, "第二条回复")

    first_request_id = uuid4()
    other_root = create_turn(
        v2_user,
        TurnCommand(
            branch_id=root.branch_id,
            parent_message_id=replay.assistant_message_id,
            content="第三条需求",
            client_request_id=first_request_id,
        ),
        chat_id=root.chat_id,
    )
    same = create_turn(
        v2_user,
        TurnCommand(
            branch_id=root.branch_id,
            parent_message_id=replay.assistant_message_id,
            content="客户端重试正文可不同但资源必须相同",
            client_request_id=first_request_id,
        ),
        chat_id=root.chat_id,
    )
    assert same.idempotent_replay
    assert same.generation_id == other_root.generation_id
    _finish_generation(other_root, "第三条回复")

    rewind = create_turn(
        v2_user,
        TurnCommand(
            branch_id=root.branch_id,
            parent_message_id=root.assistant_message_id,
            action=TurnAction.REWIND_CONTINUE,
            content="从第一条回复处继续",
            client_request_id=uuid4(),
        ),
        chat_id=root.chat_id,
    )
    _finish_generation(rewind, "显式分支回复")

    edit = create_turn(
        v2_user,
        TurnCommand(
            branch_id=root.branch_id,
            action=TurnAction.EDIT_RESEND,
            derived_from_message_id=root.user_message_id,
            content="编辑后的第一条需求",
            client_request_id=uuid4(),
        ),
        chat_id=root.chat_id,
    )

    assert not edit.branch_created
    assert edit.branch_id == root.branch_id
    assert edit.fork_reason.value == "root"
    assert rewind.branch_created and rewind.fork_reason == TurnAction.REWIND_CONTINUE.value

    user_view = ConversationQueryService().get_conversation(v2_user, root.chat_id)
    admin_view = ConversationQueryService(admin=True).get_conversation(v2_user, root.chat_id)
    assert admin_view.model_dump() == user_view.model_dump()
    assert user_view.chat.branch_count == 2
    assert {branch.id for branch in user_view.branches} == {
        root.branch_id,
        rewind.branch_id,
    }
    names = {branch.id: branch.name for branch in user_view.branches}
    assert names[root.branch_id] == "主线"
    assert names[rewind.branch_id] == "分支1"

    root_path = ConversationQueryService().get_message_path(
        v2_user, root.chat_id, root.branch_id, limit=20
    )
    rewind_path = ConversationQueryService().get_message_path(
        v2_user, root.chat_id, rewind.branch_id, limit=20
    )
    assert [item.content for item in root_path.items] == ["编辑后的第一条需求", ""]
    assert [item.content for item in rewind_path.items] == [
        "第一条需求", "第一条回复", "从第一条回复处继续", "显式分支回复",
    ]
    assert user_view.chat.message_count == 6


def test_edit_without_other_branch_hard_deletes_replaced_line(v2_user):
    root = create_turn(v2_user, TurnCommand(content="旧需求", client_request_id=uuid4()))
    _finish_generation(root, "旧回复")

    edit = create_turn(
        v2_user,
        TurnCommand(
            branch_id=root.branch_id,
            action=TurnAction.EDIT_RESEND,
            derived_from_message_id=root.user_message_id,
            content="新需求",
            client_request_id=uuid4(),
        ),
        chat_id=root.chat_id,
    )

    assert edit.branch_id == root.branch_id and not edit.branch_created
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        messages = conn.execute(
            "SELECT id, content FROM app.chat_messages WHERE chat_id = %s ORDER BY depth",
            (root.chat_id,),
        ).fetchall()
        assert [row["content"] for row in messages] == ["新需求", ""]
        assert {row["id"] for row in messages}.isdisjoint({
            root.user_message_id, root.assistant_message_id,
        })
        assert conn.execute(
            "SELECT 1 FROM app.ai_generation_runs WHERE id = %s", (root.generation_id,)
        ).fetchone() is None


def test_database_rejects_terminal_message_mutation_and_single_node_delete(v2_user):
    root = create_turn(v2_user, TurnCommand(content="不可变", client_request_id=uuid4()))
    _finish_generation(root)
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="terminal chat messages"):
            conn.execute(
                "UPDATE app.chat_messages SET content = '篡改' WHERE id = %s",
                (root.assistant_message_id,),
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation, match="only be deleted"):
            conn.execute("DELETE FROM app.chat_messages WHERE id = %s", (root.user_message_id,))
        conn.rollback()
        conn.execute("DELETE FROM app.chats WHERE id = %s", (root.chat_id,))


def test_one_hundred_concurrent_sends_from_same_head_are_all_preserved(v2_user):
    root = create_turn(v2_user, TurnCommand(content="并发起点", client_request_id=uuid4()))
    _finish_generation(root)

    def send(index: int):
        return create_turn(
            v2_user,
            TurnCommand(
                branch_id=root.branch_id,
                parent_message_id=root.assistant_message_id,
                content=f"并发消息 {index}",
                client_request_id=uuid4(),
            ),
            chat_id=root.chat_id,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(send, range(100)))

    assert len({result.user_message_id for result in results}) == 100
    assert len({result.assistant_message_id for result in results}) == 100
    assert sum(result.branch_created for result in results) == 99
    tree = ConversationQueryService().get_conversation(v2_user, root.chat_id)
    assert tree.chat.branch_count == 100
    assert tree.chat.message_count == 202
