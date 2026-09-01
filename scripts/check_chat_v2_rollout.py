#!/usr/bin/env python3
"""只读检查 V2 对话灰度状态；可作为发布门禁和回滚诊断。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.chat_rollout_repo import get_chat_v2_rollout_metrics, rollout_config_view
from db.pg import close_pools
from redis_client import close_redis_pool, get_redis_client


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--strict", action="store_true", help="要求迁移完成且所有异常指标为 0")
    value.add_argument("--require-v1-zero", action="store_true")
    value.add_argument("--require-redis", action="store_true")
    value.add_argument("--max-queued", type=int)
    value.add_argument("--max-oldest-queued-seconds", type=int)
    value.add_argument("--max-expired-leases", type=int)
    value.add_argument("--max-outbox-backlog", type=int)
    value.add_argument("--max-oldest-outbox-seconds", type=int)
    return value


def evaluate(metrics: dict[str, int], args: argparse.Namespace, redis_ok: bool) -> list[str]:
    issues: list[str] = []
    zero_fields = (
        "expired_leases",
        "exhausted_active",
        "orphan_generating_messages",
        "stale_building_snapshots",
        "incomplete_ready_snapshots",
        "outbox_exhausted",
    )
    if args.strict:
        for field in zero_fields:
            if metrics.get(field, 0) != 0:
                issues.append(f"{field}={metrics[field]}，严格门禁要求为 0")
        if metrics.get("chats_v1", 0) != 0:
            issues.append(f"chats_v1={metrics['chats_v1']}，严格门禁要求迁移完成")
    if args.require_v1_zero and metrics.get("chats_v1", 0) != 0:
        issues.append(f"chats_v1={metrics['chats_v1']}，要求为 0")
    if (args.require_redis or args.strict) and not redis_ok:
        issues.append("Redis ping 失败")
    limits = {
        "queued": args.max_queued,
        "oldest_queued_seconds": args.max_oldest_queued_seconds,
        "expired_leases": args.max_expired_leases,
        "outbox_backlog": args.max_outbox_backlog,
        "oldest_outbox_seconds": args.max_oldest_outbox_seconds,
    }
    for field, maximum in limits.items():
        if maximum is not None and metrics.get(field, 0) > maximum:
            issues.append(f"{field}={metrics[field]} 超过上限 {maximum}")
    return issues


def run(args: argparse.Namespace) -> dict[str, Any]:
    metrics = get_chat_v2_rollout_metrics()
    redis_ok = False
    try:
        redis_ok = bool(get_redis_client().ping())
    except Exception:
        redis_ok = False
    issues = evaluate(metrics, args, redis_ok)
    return {
        "ok": not issues,
        "config": rollout_config_view(),
        "metrics": metrics,
        "redis_ok": redis_ok,
        "issues": issues,
    }


def main() -> int:
    args = parser().parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    finally:
        close_pools()
        close_redis_pool()


if __name__ == "__main__":
    raise SystemExit(main())
