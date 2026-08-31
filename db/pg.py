"""PostgreSQL 连接与会话。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

import config

_SCHEMA_DIR = Path(__file__).resolve().parent / "postgres"


def connect(url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(url or config.DATABASE_URL, row_factory=dict_row)
    conn.execute("SET search_path TO app, donor, admin, public")
    return conn


def connect_admin() -> psycopg.Connection:
    return connect(config.DATABASE_ADMIN_URL)


@contextmanager
def db_session(admin: bool = False) -> Iterator[psycopg.Connection]:
    conn = connect_admin() if admin else connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema() -> None:
    """若表不存在则执行官方建库脚本（适合开发；生产应事先执行 SQL）。"""
    from db.sql_runner import run_sql_file

    with db_session(admin=True) as conn:
        row = conn.execute(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'donor' AND table_name = 'donors'
            ) AS ok
            """
        ).fetchone()
        if not (row and row["ok"]):
            for name in ("01_init_db.sql", "02_schema.sql", "03_roles.sql"):
                path = _SCHEMA_DIR / name
                if path.exists():
                    run_sql_file(conn, path)

        # 可重复执行的小型迁移，确保已有开发库也能随应用升级。
        for name in ("05_add_user_phone.sql", "06_add_admin_user_archives.sql", "07_add_operation_requests.sql"):
            path = _SCHEMA_DIR / name
            if path.exists():
                run_sql_file(conn, path)


def bootstrap_admin() -> None:
    """无管理员时创建引导账号。"""
    from api.auth_utils import hash_password

    with db_session(admin=True) as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM admin.admin_users").fetchone()["c"]
        if n and int(n) > 0:
            return
        conn.execute(
            """
            INSERT INTO admin.admin_users (username, password_hash, display_name, role)
            VALUES (%s, %s, %s, 'super_admin')
            """,
            (
                config.ADMIN_BOOTSTRAP_USERNAME,
                hash_password(config.ADMIN_BOOTSTRAP_PASSWORD),
                "系统管理员",
            ),
        )


def init_db() -> None:
    ensure_schema()
    bootstrap_admin()


def _cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: _cell(v) for k, v in row.items()}


def fetchone(conn: psycopg.Connection, sql: str, params: tuple | list | None = None) -> dict[str, Any] | None:
    cur = conn.execute(sql, params or ())
    return _row(cur.fetchone())


def fetchall(conn: psycopg.Connection, sql: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params or ())
    return [_row(r) or {} for r in cur.fetchall()]
