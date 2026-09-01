"""旧 JSON 会话迁移到分支消息树的真实 PostgreSQL 测试。"""

from __future__ import annotations

import argparse
import json
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import config
from db.pg import close_pools, ensure_schema
from db.chats_repo import hard_delete_chat
from dialogue.conversation_queries import ConversationQueryService
from dialogue.chat_migration import legacy_branch_id, legacy_message_id
from scripts.migrate_chat_storage_v2 import run


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


def _args(**overrides):
    values = {
        "dry_run": False,
        "verify_only": False,
        "user_id": None,
        "chat_id": None,
        "batch_size": 1,
        "resume_after": 0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def legacy_subject(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    ensure_schema()
    email = f"chat-migration-{uuid4()}@example.test"
    donor_code = f"M-{str(uuid4())[:8]}"
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        user_id = int(conn.execute(
            """
            INSERT INTO app.users (email, password_hash, nickname)
            VALUES (%s, 'test-only', 'migration') RETURNING id
            """,
            (email,),
        ).fetchone()["id"])
        donor_id = int(conn.execute(
            """
            INSERT INTO donor.donors
                (code, education, height_cm, abo_blood, status, specimen_count)
            VALUES (%s, '硕士', 181, 'A', 'active', 8) RETURNING id
            """,
            (donor_code,),
        ).fetchone()["id"])
        match_id = uuid4()
        conn.execute(
            """
            INSERT INTO app.match_runs (
                id, user_id, profile_json, profile_hash, model_version,
                dataset_version, total, donor_ids, scores, status,
                snapshot_schema_version, snapshot_source
            ) VALUES (%s, %s, '{}'::jsonb, 'legacy', 'v1', 'legacy', 1,
                      %s, %s, 'building', 1, 'legacy_backfill')
            """,
            (match_id, user_id, [donor_id], [0.91]),
        )
        messages_json = json.dumps([
            {"role": "user", "content": "帮我匹配"},
            {"role": "bot", "content": "已找到结果"},
            {"role": "user", "content": "继续说明"},
        ], ensure_ascii=False)
        state_json = json.dumps({
            "parsed_features": {"height_cm": 181},
            "constraints": {"height_cm": "must"},
            "dialogue_state": "results",
            "pending_relaxations": [],
            "match_result_id": str(match_id),
            "history": [{"role": "user", "content": "旧临时历史"}],
        }, ensure_ascii=False)
        candidates_json = json.dumps([
            {
                "donor_info": {"code": donor_code, "education": "硕士"},
                "match_pct": 91,
                "reason": "历史匹配",
            }
        ], ensure_ascii=False)
        chat_id = int(conn.execute(
            """
            INSERT INTO app.chats (
                user_id, session_id, title, messages_json, candidates_json,
                state_json, storage_version
            ) VALUES (%s, %s, '旧会话', %s, %s, %s, 1) RETURNING id
            """,
            (user_id, str(uuid4()), messages_json, candidates_json, state_json),
        ).fetchone()["id"])
    try:
        yield user_id, donor_id, donor_code, match_id, chat_id, messages_json
    finally:
        close_pools()
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute(
                """
                DELETE FROM app.outbox_events event
                USING app.chat_deletion_audit audit
                WHERE event.aggregate_id = audit.chat_id::text
                  AND audit.user_id = %s
                """,
                (user_id,),
            )
            conn.execute(
                "DELETE FROM app.chat_deletion_audit WHERE user_id = %s", (user_id,)
            )
            conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))
            conn.execute("DELETE FROM donor.donors WHERE id = %s", (donor_id,))


def test_migration_builds_complete_tree_and_match_snapshot_idempotently(legacy_subject):
    user_id, donor_id, donor_code, match_id, chat_id, messages_json = legacy_subject
    assert TEST_DATABASE_URL
    dry = run(_args(dry_run=True, chat_id=chat_id), database_url=TEST_DATABASE_URL)
    assert dry.would_migrate == 1 and dry.migrated == 0
    assert dry.would_legacy_backfills == 1 and dry.legacy_backfills == 0
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        assert conn.execute(
            "SELECT storage_version FROM app.chats WHERE id = %s", (chat_id,)
        ).fetchone()["storage_version"] == 1
        assert conn.execute(
            "SELECT status FROM app.match_runs WHERE id = %s", (match_id,)
        ).fetchone()["status"] == "building"
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM app.match_run_items WHERE match_run_id = %s",
            (match_id,),
        ).fetchone()["count"] == 0
    user_tree = ConversationQueryService().get_conversation(user_id, chat_id)
    admin_tree = ConversationQueryService(admin=True).get_conversation(user_id, chat_id)
    assert user_tree.model_dump() == admin_tree.model_dump()
    assert user_tree.chat.storage_version == 1
    legacy_page = ConversationQueryService().get_message_path(
        user_id, chat_id, user_tree.branches[0].id, limit=2
    )
    assert [message.depth for message in legacy_page.items] == [1, 2]
    assert legacy_page.has_more

    report = run(_args(chat_id=chat_id), database_url=TEST_DATABASE_URL)
    assert report.migrated == 1 and report.failed == 0
    assert report.legacy_backfills == 1
    assert any(
        any("linked_to_last_assistant" in warning for warning in item.get("warnings", []))
        for item in report.errors
    )

    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        chat = conn.execute(
            "SELECT * FROM app.chats WHERE id = %s", (chat_id,)
        ).fetchone()
        assert chat["storage_version"] == 2
        assert chat["active_branch_id"] == legacy_branch_id(chat_id)
        assert chat["branch_count"] == 1 and chat["message_count"] == 3
        assert chat["messages_json"] == messages_json
        messages = conn.execute(
            """
            SELECT id, parent_message_id, role, state_recoverable,
                   state_after_json, match_run_id
            FROM app.chat_messages WHERE chat_id = %s ORDER BY depth
            """,
            (chat_id,),
        ).fetchall()
        assert [row["id"] for row in messages] == [legacy_message_id(chat_id, i) for i in range(3)]
        assert [row["parent_message_id"] for row in messages] == [
            None, legacy_message_id(chat_id, 0), legacy_message_id(chat_id, 1)
        ]
        assert [row["role"] for row in messages] == ["user", "assistant", "user"]
        assert [row["state_recoverable"] for row in messages] == [False, False, True]
        assert messages[1]["match_run_id"] == match_id
        assert messages[2]["state_after_json"]["latest_match_run_id"] == str(match_id)
        item = conn.execute(
            "SELECT * FROM app.match_run_items WHERE match_run_id = %s", (match_id,)
        ).fetchone()
        assert item["rank"] == 1 and item["donor_id"] == donor_id
        assert item["donor_code_snapshot"] == donor_code
        assert item["donor_snapshot_json"]["education"] == "硕士"
        conn.execute("UPDATE donor.donors SET education = '本科' WHERE id = %s", (donor_id,))
        assert conn.execute(
            "SELECT donor_snapshot_json->>'education' AS value FROM app.match_run_items WHERE match_run_id = %s",
            (match_id,),
        ).fetchone()["value"] == "硕士"

    verify = run(_args(verify_only=True, chat_id=chat_id), database_url=TEST_DATABASE_URL)
    assert verify.verified == 1 and verify.failed == 0
    rerun = run(_args(chat_id=chat_id), database_url=TEST_DATABASE_URL)
    assert rerun.scanned == 0 and rerun.migrated == 0


def test_resume_after_and_user_filter_limit_dry_run_scope(legacy_subject):
    user_id, _donor_id, _donor_code, _match_id, chat_id, _messages_json = legacy_subject
    assert TEST_DATABASE_URL
    report = run(
        _args(dry_run=True, user_id=user_id, resume_after=chat_id),
        database_url=TEST_DATABASE_URL,
    )
    assert report.scanned == 0 and report.would_migrate == 0


def test_confirmed_v2_delete_path_also_hard_deletes_unmigrated_v1_chat(legacy_subject):
    user_id, _donor_id, _donor_code, _match_id, chat_id, _messages_json = legacy_subject
    assert TEST_DATABASE_URL
    deleted = hard_delete_chat(user_id, chat_id, uuid4())
    assert deleted is not None
    assert deleted["branch_count"] == 1 and deleted["message_count"] == 3
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        assert conn.execute(
            "SELECT 1 FROM app.chats WHERE id = %s", (chat_id,)
        ).fetchone() is None
