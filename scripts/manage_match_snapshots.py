"""查看严格匹配快照容量，或按小批次清理过期数据。"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.match_runs_repo import cleanup_expired_match_runs
from db.pg import close_pools, db_session, fetchone


def snapshot_stats(retention_days: int) -> dict[str, int]:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE (status = 'failed'
                           OR created_at < now() - (%s * interval '1 day'))
                      AND NOT EXISTS (
                        SELECT 1 FROM app.chat_messages cm
                        WHERE cm.match_run_id = app.match_runs.id
                      )
                ) AS expired,
                pg_total_relation_size('app.match_runs') AS table_bytes,
                pg_indexes_size('app.match_runs') AS index_bytes
            FROM app.match_runs
            """,
            (retention_days,),
        )
    return {key: int((row or {}).get(key) or 0) for key in (
        "total", "expired", "table_bytes", "index_bytes"
    )}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days", type=int, default=config.MATCH_SNAPSHOT_RETENTION_DAYS
    )
    parser.add_argument("--cleanup", action="store_true", help="实际删除过期快照")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-batches", type=int, default=10)
    args = parser.parse_args()
    if args.retention_days < 1 or args.batch_size < 1 or args.max_batches < 1:
        raise SystemExit("retention-days、batch-size、max-batches 必须为正整数")
    try:
        before = snapshot_stats(args.retention_days)
        print({"mode": "cleanup" if args.cleanup else "dry-run", **before})
        if not args.cleanup:
            return
        removed = 0
        for _ in range(args.max_batches):
            count = cleanup_expired_match_runs(
                retention_days=args.retention_days, batch_size=args.batch_size
            )
            removed += count
            print({"batch_removed": count, "removed_total": removed})
            if count < args.batch_size:
                break
        print({"cleanup_complete": True, "removed_total": removed})
    finally:
        close_pools()


if __name__ == "__main__":
    main()
