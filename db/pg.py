"""PostgreSQL 连接与会话。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal
from threading import Lock
from typing import Any, Iterator

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

import config

_SCHEMA_DIR = Path(__file__).resolve().parent / "postgres"
_pool_lock = Lock()
_app_pool: ConnectionPool | None = None
_admin_pool: ConnectionPool | None = None


def connect(url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(url or config.DATABASE_URL, row_factory=dict_row)
    conn.execute("SET search_path TO app, donor, admin, public")
    return conn


def connect_admin() -> psycopg.Connection:
    return connect(config.DATABASE_ADMIN_URL)


def _configure_connection(conn: psycopg.Connection) -> None:
    conn.execute("SET search_path TO app, donor, admin, public")
    conn.commit()


def _create_pool(url: str, name: str) -> ConnectionPool:
    return ConnectionPool(
        conninfo=url,
        min_size=config.PG_POOL_MIN_SIZE,
        max_size=config.PG_POOL_MAX_SIZE,
        timeout=config.PG_POOL_TIMEOUT_SECONDS,
        kwargs={"row_factory": dict_row},
        configure=_configure_connection,
        check=ConnectionPool.check_connection,
        name=name,
        open=False,
    )


def initialize_pools() -> None:
    global _app_pool, _admin_pool
    created: list[ConnectionPool] = []
    with _pool_lock:
        if _app_pool is None:
            _app_pool = _create_pool(config.DATABASE_URL, "jzk-app")
            _app_pool.open()
            created.append(_app_pool)
        if _admin_pool is None:
            _admin_pool = _create_pool(config.DATABASE_ADMIN_URL, "jzk-admin")
            _admin_pool.open()
            created.append(_admin_pool)
    try:
        for pool in created:
            pool.wait(timeout=config.PG_POOL_TIMEOUT_SECONDS)
    except Exception:
        close_pools()
        raise


def close_pools() -> None:
    global _app_pool, _admin_pool
    with _pool_lock:
        app_pool, admin_pool = _app_pool, _admin_pool
        _app_pool = None
        _admin_pool = None
    if app_pool is not None:
        app_pool.close()
    if admin_pool is not None:
        admin_pool.close()


def _get_pool(admin: bool) -> ConnectionPool:
    initialize_pools()
    pool = _admin_pool if admin else _app_pool
    if pool is None:  # pragma: no cover - initialize_pools guarantees this
        raise RuntimeError("数据库连接池未初始化")
    return pool


@contextmanager
def db_session(admin: bool = False) -> Iterator[psycopg.Connection]:
    pool = _get_pool(admin)
    with pool.connection(timeout=config.PG_POOL_TIMEOUT_SECONDS) as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


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
        for name in (
            "05_add_user_phone.sql",
            "06_add_admin_user_archives.sql",
            "07_add_operation_requests.sql",
            "08_add_admin_account_audit.sql",
            "09_add_admin_token_version.sql",
            "10_add_match_runs.sql",
        ):
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
