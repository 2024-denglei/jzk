from argparse import Namespace

import config
from dialogue.chat_rollout import rollout_bucket, user_can_write_v2
from scripts.check_chat_v2_rollout import evaluate


def test_write_rollout_is_stable_and_allowlist_bypasses_percentage(monkeypatch):
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_ROLLOUT_SALT", "stable-test")
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_PERCENT", 0)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_USER_IDS", frozenset({7}))
    assert user_can_write_v2(7) is True
    assert user_can_write_v2(8) is False
    assert rollout_bucket(8) == rollout_bucket(8)

    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_PERCENT", 25)
    assert user_can_write_v2(8) is (rollout_bucket(8) < 2500)
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_ENABLED", False)
    assert user_can_write_v2(7) is False


def test_rollout_gate_reports_threshold_failures():
    args = Namespace(
        strict=True,
        require_v1_zero=False,
        require_redis=False,
        max_queued=2,
        max_oldest_queued_seconds=30,
        max_expired_leases=0,
        max_outbox_backlog=1,
        max_oldest_outbox_seconds=60,
    )
    metrics = {
        "chats_v1": 3,
        "queued": 4,
        "oldest_queued_seconds": 45,
        "expired_leases": 1,
        "exhausted_active": 0,
        "orphan_generating_messages": 0,
        "stale_building_snapshots": 0,
        "incomplete_ready_snapshots": 0,
        "outbox_backlog": 2,
        "oldest_outbox_seconds": 90,
    }
    issues = evaluate(metrics, args, redis_ok=False)
    assert any("chats_v1=3" in issue for issue in issues)
    assert any("queued=4" in issue for issue in issues)
    assert any("expired_leases=1" in issue for issue in issues)
    assert "Redis ping 失败" in issues
