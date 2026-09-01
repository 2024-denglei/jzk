#!/usr/bin/env python3
"""批量迁移旧 JSON 会话；不删除旧字段，也不读取本地 JSON Trace。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from dialogue.chat_migration import MigrationReport, migrate_legacy_chat, verify_migrated_chat


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="迁移分支化 AI 对话存储 V2")
    value.add_argument("--dry-run", action="store_true")
    value.add_argument("--verify-only", action="store_true")
    value.add_argument("--user-id", type=int)
    value.add_argument("--chat-id", type=int)
    value.add_argument("--batch-size", type=int, default=100)
    value.add_argument("--resume-after", type=int, default=0)
    return value


def _select_batch(conn, *, after: int, batch_size: int, user_id: int | None, chat_id: int | None, verify_only: bool):
    where = ["c.id > %s", "c.storage_version = %s"]
    params: list[Any] = [after, 2 if verify_only else 1]
    if verify_only:
        where.append(
            """EXISTS (
                SELECT 1 FROM app.chat_branches b
                WHERE b.chat_id = c.id AND b.fork_reason = 'root'
                  AND b.system_name = '迁移的主分支'
            )"""
        )
    if user_id is not None:
        where.append("c.user_id = %s")
        params.append(user_id)
    if chat_id is not None:
        where.append("c.id = %s")
        params.append(chat_id)
    params.append(max(1, min(batch_size, 1000)))
    return conn.execute(
        f"SELECT c.* FROM app.chats c WHERE {' AND '.join(where)} ORDER BY c.id LIMIT %s",
        params,
    ).fetchall()


def run(args: argparse.Namespace, *, database_url: str | None = None) -> MigrationReport:
    report = MigrationReport()
    url = database_url or config.DATABASE_MIGRATOR_URL
    after = max(0, int(args.resume_after))
    while True:
        with psycopg.connect(url, row_factory=dict_row) as conn:
            rows = _select_batch(
                conn,
                after=after,
                batch_size=args.batch_size,
                user_id=args.user_id,
                chat_id=args.chat_id,
                verify_only=args.verify_only,
            )
        if not rows:
            break
        for row in rows:
            chat_id = int(row["id"])
            report.scanned += 1
            report.last_chat_id = chat_id
            after = chat_id
            try:
                if args.verify_only:
                    with psycopg.connect(url, row_factory=dict_row) as conn:
                        issues = verify_migrated_chat(conn, chat_id)
                    if issues:
                        report.failed += 1
                        report.errors.append({"chat_id": chat_id, "issues": issues})
                    else:
                        report.verified += 1
                    continue
                if args.dry_run:
                    warnings = migrate_legacy_chat(None, row, report, dry_run=True)
                    report.partial += int(bool(warnings))
                    report.would_migrate += 1
                    if warnings:
                        report.errors.append({"chat_id": chat_id, "warnings": warnings})
                    continue
                with psycopg.connect(url, row_factory=dict_row) as conn:
                    warnings = migrate_legacy_chat(conn, row, report)
                report.migrated += 1
                if warnings:
                    report.partial += 1
                    report.errors.append({"chat_id": chat_id, "warnings": warnings})
            except Exception as exc:
                report.failed += 1
                report.errors.append({"chat_id": chat_id, "error": type(exc).__name__, "message": str(exc)[:300]})
        if args.chat_id is not None:
            break
    return report


def main() -> int:
    args = parser().parse_args()
    if args.dry_run and args.verify_only:
        raise SystemExit("--dry-run 与 --verify-only 不能同时使用")
    report = run(args)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
