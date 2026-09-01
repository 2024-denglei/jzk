"""完整排名快照、消息关联和历史稳定性的真实 PostgreSQL 测试。"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import config
from core.preference.result_types import MatchResultMeta, MatchSnapshotItem, RankedCandidateRef
from db.match_runs_repo import (
    cleanup_expired_match_runs,
    create_match_run,
    delete_match_run,
    get_match_run_items_page,
)
from db.pg import close_pools, ensure_schema
from db.chat_models import TurnCommand
from dialogue.conversation_commands import create_turn
from dialogue.conversation_queries import ConversationQueryService


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未配置 TEST_DATABASE_URL")


@pytest.fixture
def snapshot_subject(monkeypatch):
    assert TEST_DATABASE_URL
    close_pools()
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(config, "DATABASE_ADMIN_URL", TEST_DATABASE_URL)
    ensure_schema()
    email = f"snapshot-v2-{uuid4()}@example.test"
    donor_code = f"S-{str(uuid4())[:8]}"
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        user_id = int(
            conn.execute(
                """
                INSERT INTO app.users (email, password_hash, nickname)
                VALUES (%s, 'test-only', 'snapshot-v2') RETURNING id
                """,
                (email,),
            ).fetchone()["id"]
        )
        donor_id = int(
            conn.execute(
                """
                INSERT INTO donor.donors
                    (code, education, height_cm, abo_blood, status, specimen_count)
                VALUES (%s, '硕士', 178, 'O', 'active', 10) RETURNING id
                """,
                (donor_code,),
            ).fetchone()["id"]
        )
    try:
        yield user_id, donor_id, donor_code
    finally:
        close_pools()
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))
            conn.execute("DELETE FROM donor.donors WHERE id = %s", (donor_id,))


def test_frozen_snapshot_survives_donor_change_and_lives_with_message(snapshot_subject):
    user_id, donor_id, donor_code = snapshot_subject
    result_id = str(uuid4())
    refs = [RankedCandidateRef(donor_id=donor_id, rank=1, score=0.9234567)]
    frozen = [
        MatchSnapshotItem(
            donor_id=donor_id,
            rank=1,
            score=0.923457,
            donor_code_snapshot=donor_code,
            donor_snapshot={
                "id": donor_id,
                "code": donor_code,
                "education": "硕士",
                "height": "178",
                "blood_type": "O",
                "age": 0,
                "ethnicity": None,
                "hometown": None,
                "figure": None,
                "personality": None,
                "occupation": None,
                "specimen_count": 10,
                "status": "active",
            },
            match_explanation={"reason": "匹配：height_cm", "match_pct": 92.35},
        )
    ]
    meta = create_match_run(
        MatchResultMeta(
            result_set_id=result_id,
            owner_user_id=user_id,
            total=1,
            profile={"schema_version": "1.0", "attributes": {}},
            profile_hash="",
            model_version="v2",
            dataset_version="test-dataset",
        ),
        refs,
        frozen,
    )
    assert meta.status == "ready" and meta.ready_at is not None

    turn = create_turn(user_id, TurnCommand(content="请匹配", client_request_id=uuid4()))
    assert TEST_DATABASE_URL
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute(
            """
            UPDATE app.chat_messages
            SET status = 'completed', content = '匹配完成', match_run_id = %s,
                completed_at = now()
            WHERE id = %s
            """,
            (result_id, turn.assistant_message_id),
        )
        conn.execute(
            "UPDATE app.ai_generation_runs SET status = 'running', started_at = now() WHERE id = %s",
            (turn.generation_id,),
        )
        conn.execute(
            "UPDATE app.ai_generation_runs SET status = 'completed', finished_at = now() WHERE id = %s",
            (turn.generation_id,),
        )
        conn.execute(
            "UPDATE donor.donors SET education = '本科', status = 'disabled' WHERE id = %s",
            (donor_id,),
        )
        conn.execute(
            "UPDATE app.match_runs SET created_at = now() - interval '10 days' WHERE id = %s",
            (result_id,),
        )

    payload = ConversationQueryService().get_message_match_results(
        user_id, turn.assistant_message_id, page=1, limit=20
    )
    admin_payload = ConversationQueryService(admin=True).get_message_match_results(
        user_id, turn.assistant_message_id, page=1, limit=20
    )
    assert admin_payload == payload
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["donor_info"]["education"] == "硕士"
    assert payload["items"][0]["donor_info"]["status_snapshot"] == "active"
    assert payload["items"][0]["current_status"] == "disabled"
    assert payload["items"][0]["currently_selectable"] is False
    assert cleanup_expired_match_runs(retention_days=1) >= 0
    assert get_match_run_items_page(result_id, user_id, offset=0, limit=20) is not None
    assert delete_match_run(result_id, user_id) is False

    loaded = get_match_run_items_page(result_id, user_id, offset=0, limit=20)
    assert loaded and loaded[1][0].donor_code_snapshot == donor_code

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("DELETE FROM app.chats WHERE id = %s", (turn.chat_id,))
    assert delete_match_run(result_id, user_id) is True


def test_message_rejects_building_or_cross_owner_snapshot(snapshot_subject):
    user_id, donor_id, _donor_code = snapshot_subject
    assert TEST_DATABASE_URL
    turn = create_turn(user_id, TurnCommand(content="验证归属", client_request_id=uuid4()))
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
        other_user_id = int(
            conn.execute(
                """
                INSERT INTO app.users (email, password_hash, nickname)
                VALUES (%s, 'test-only', 'other') RETURNING id
                """,
                (f"other-{uuid4()}@example.test",),
            ).fetchone()["id"]
        )
        building_id = uuid4()
        cross_owner_id = uuid4()
        for match_id, owner, status in (
            (building_id, user_id, "building"),
            (cross_owner_id, other_user_id, "ready"),
        ):
            conn.execute(
                """
                INSERT INTO app.match_runs (
                    id, user_id, profile_json, profile_hash, model_version,
                    dataset_version, total, donor_ids, scores, status,
                    snapshot_schema_version, snapshot_source, ready_at
                ) VALUES (%s, %s, '{}'::jsonb, 'h', 'v2', 'd', 0,
                          ARRAY[]::bigint[], ARRAY[]::real[], %s, 1, 'native',
                          CASE WHEN %s = 'ready' THEN now() ELSE NULL END)
                """,
                (match_id, owner, status, status),
            )
        conn.commit()
        for match_id in (building_id, cross_owner_id):
            with pytest.raises(psycopg.errors.CheckViolation, match="same user"):
                conn.execute(
                    """
                    UPDATE app.chat_messages
                    SET status = 'completed', content = '非法关联', match_run_id = %s,
                        completed_at = now()
                    WHERE id = %s
                    """,
                    (match_id, turn.assistant_message_id),
                )
            conn.rollback()
        conn.execute("DELETE FROM app.users WHERE id = %s", (other_user_id,))
