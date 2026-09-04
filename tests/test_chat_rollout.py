from argparse import Namespace
import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "scripts"
    / "check_chat_v2_rollout.py"
)
_spec = importlib.util.spec_from_file_location("check_chat_v2_rollout", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_check_chat_v2_rollout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_check_chat_v2_rollout)
evaluate = _check_chat_v2_rollout.evaluate


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
