"""将历史 SQLite app.db 用户侧数据迁入 PostgreSQL app schema。

用法（在 agent 目录）:
  python scripts/migrate_sqlite_to_pg.py
  python scripts/migrate_sqlite_to_pg.py --sqlite data/app.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# 保证可导入项目包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db
from db.pg import db_session


def migrate(sqlite_path: str) -> None:
    if not os.path.isfile(sqlite_path):
        raise SystemExit(f"SQLite 文件不存在: {sqlite_path}")

    init_db()
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    tables = [
        ("users", "SELECT id, email, password_hash, nickname, created_at FROM users"),
        (
            "favorites",
            "SELECT id, user_id, donor_code, created_at FROM favorites",
        ),
        (
            "history",
            "SELECT id, user_id, kind, donor_code, payload, created_at FROM history",
        ),
        (
            "preferences",
            "SELECT user_id, filters_json, priority_json, updated_at FROM preferences",
        ),
    ]

    with db_session(admin=True) as conn:
        for name, sql in tables:
            try:
                rows = src.execute(sql).fetchall()
            except sqlite3.Error as e:
                print(f"[skip] {name}: {e}")
                continue
            print(f"迁移 {name}: {len(rows)} 行")
            for r in rows:
                d = dict(r)
                if name == "users":
                    conn.execute(
                        """
                        INSERT INTO app.users (id, email, password_hash, nickname, created_at)
                        VALUES (%(id)s, %(email)s, %(password_hash)s, %(nickname)s, %(created_at)s)
                        ON CONFLICT (id) DO UPDATE SET
                          email = EXCLUDED.email,
                          password_hash = EXCLUDED.password_hash,
                          nickname = EXCLUDED.nickname
                        """,
                        d,
                    )
                elif name == "favorites":
                    conn.execute(
                        """
                        INSERT INTO app.favorites (id, user_id, donor_code, created_at)
                        VALUES (%(id)s, %(user_id)s, %(donor_code)s, %(created_at)s)
                        ON CONFLICT (user_id, donor_code) DO NOTHING
                        """,
                        d,
                    )
                elif name == "history":
                    conn.execute(
                        """
                        INSERT INTO app.history (id, user_id, kind, donor_code, payload, created_at)
                        VALUES (%(id)s, %(user_id)s, %(kind)s, %(donor_code)s, %(payload)s, %(created_at)s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        d,
                    )
                elif name == "preferences":
                    conn.execute(
                        """
                        INSERT INTO app.preferences (user_id, filters_json, priority_json, updated_at)
                        VALUES (%(user_id)s, %(filters_json)s, %(priority_json)s, %(updated_at)s)
                        ON CONFLICT (user_id) DO UPDATE SET
                          filters_json = EXCLUDED.filters_json,
                          priority_json = EXCLUDED.priority_json,
                          updated_at = EXCLUDED.updated_at
                        """,
                        d,
                    )

        # 校正序列
        for seq_table in ("users", "favorites", "history"):
            conn.execute(
                f"""
                SELECT setval(
                  pg_get_serial_sequence('app.{seq_table}', 'id'),
                  COALESCE((SELECT MAX(id) FROM app.{seq_table}), 1),
                  true
                )
                """
            )

    src.close()
    print("迁移完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    default_sqlite = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.db"
    )
    parser.add_argument("--sqlite", default=default_sqlite)
    args = parser.parse_args()
    migrate(args.sqlite)
