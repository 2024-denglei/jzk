"""管理员中心：管理员资料、操作统计与聚合审计。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg.errors import UniqueViolation

from jzk.db.pg import db_session, fetchall, fetchone


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _write_account_audit(
    conn,
    *,
    target_admin_id: int,
    action: str,
    operator_id: int,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    conn.execute(
        """
        INSERT INTO admin.admin_account_audit_logs
            (target_admin_id, action, operator_id, reason, before_data, after_data)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            target_admin_id,
            action,
            operator_id,
            reason,
            json.dumps(_jsonable(before), ensure_ascii=False) if before is not None else None,
            json.dumps(_jsonable(after), ensure_ascii=False) if after is not None else None,
        ),
    )


def create_admin_account(
    *,
    username: str,
    password_hash: str,
    display_name: str,
    role: str,
    operator_id: int,
) -> dict[str, Any]:
    username = username.strip()
    display_name = display_name.strip()
    try:
        with db_session(admin=True) as conn:
            if fetchone(conn, "SELECT 1 AS ok FROM admin.admin_users WHERE username = %s", (username,)):
                raise ValueError("管理员登录账号已存在")
            row = fetchone(
                conn,
                """
                INSERT INTO admin.admin_users (username, password_hash, display_name, role)
                VALUES (%s, %s, %s, %s)
                RETURNING id, username, display_name, role, is_active, created_at, updated_at
                """,
                (username, password_hash, display_name, role),
            )
            if not row:
                raise RuntimeError("管理员创建失败")
            _write_account_audit(
                conn,
                target_admin_id=int(row["id"]),
                action="create",
                operator_id=operator_id,
                reason="创建管理员账号",
                before=None,
                after=row,
            )
    except UniqueViolation as exc:
        raise ValueError("管理员登录账号已存在") from exc
    return row


def set_admin_account_active(
    admin_id: int,
    *,
    is_active: bool,
    operator_id: int,
    reason: str,
) -> dict[str, Any]:
    if admin_id == operator_id and not is_active:
        raise PermissionError("不能删除当前登录的管理员账号")
    with db_session(admin=True) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(60420260831)")
        before = fetchone(
            conn,
            """
            SELECT id, username, display_name, role, is_active, created_at, updated_at
            FROM admin.admin_users WHERE id = %s FOR UPDATE
            """,
            (admin_id,),
        )
        if not before:
            raise KeyError(admin_id)
        if bool(before["is_active"]) == is_active:
            raise ValueError("管理员账号当前已是该状态")
        if not is_active and before["role"] == "super_admin":
            active_supers = fetchall(
                conn,
                "SELECT id FROM admin.admin_users WHERE role = 'super_admin' AND is_active = TRUE FOR UPDATE",
            )
            if len(active_supers) <= 1:
                raise PermissionError("系统必须至少保留一个启用的超级管理员")
        row = fetchone(
            conn,
            """
            UPDATE admin.admin_users
            SET is_active = %s, token_version = token_version + 1, updated_at = now()
            WHERE id = %s
            RETURNING id, username, display_name, role, is_active, created_at, updated_at
            """,
            (is_active, admin_id),
        )
        if not row:
            raise RuntimeError("管理员状态更新失败")
        _write_account_audit(
            conn,
            target_admin_id=admin_id,
            action="restore" if is_active else "disable",
            operator_id=operator_id,
            reason=reason,
            before=before,
            after=row,
        )
    return row


def _page_args(page: int, page_size: int) -> tuple[int, int, int]:
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 100))
    return safe_page, safe_size, (safe_page - 1) * safe_size


_ADMIN_SELECT = """
    SELECT a.id, a.username, a.display_name, a.role, a.is_active,
           a.created_at, a.updated_at,
           COALESCE(d.operation_count, 0) AS donor_operation_count,
           COALESCE(u.operation_count, 0) AS user_operation_count,
           COALESCE(m.operation_count, 0) AS admin_operation_count,
           COALESCE(d.operation_count, 0) + COALESCE(u.operation_count, 0) + COALESCE(m.operation_count, 0) AS operation_count,
           GREATEST(d.last_operation_at, u.last_operation_at, m.last_operation_at) AS last_operation_at
    FROM admin.admin_users a
    LEFT JOIN (
        SELECT operator_id, COUNT(*) AS operation_count, MAX(created_at) AS last_operation_at
        FROM donor.audit_logs GROUP BY operator_id
    ) d ON d.operator_id = a.id
    LEFT JOIN (
        SELECT operator_id, COUNT(*) AS operation_count, MAX(created_at) AS last_operation_at
        FROM admin.user_audit_logs GROUP BY operator_id
    ) u ON u.operator_id = a.id
    LEFT JOIN (
        SELECT operator_id, COUNT(*) AS operation_count, MAX(created_at) AS last_operation_at
        FROM admin.admin_account_audit_logs GROUP BY operator_id
    ) m ON m.operator_id = a.id
"""


def list_admins(
    *,
    q: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int, int, int]:
    page, page_size, offset = _page_args(page, page_size)
    where = ["1=1"]
    params: list[Any] = []
    if q:
        where.append("(a.username ILIKE %s OR a.display_name ILIKE %s)")
        like = f"%{q.strip()}%"
        params.extend([like, like])
    if is_active is not None:
        where.append("a.is_active = %s")
        params.append(is_active)
    where_sql = " AND ".join(where)

    with db_session(admin=True) as conn:
        total = fetchone(conn, f"SELECT COUNT(*) AS c FROM admin.admin_users a WHERE {where_sql}", params)
        rows = fetchall(
            conn,
            f"""
            {_ADMIN_SELECT}
            WHERE {where_sql}
            ORDER BY a.is_active DESC, operation_count DESC, a.id
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
    return rows, int((total or {}).get("c") or 0), page, page_size


def get_admin_profile(admin_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        row = fetchone(conn, f"{_ADMIN_SELECT} WHERE a.id = %s", (admin_id,))
        if not row:
            return None
        counts = fetchall(
            conn,
            """
            SELECT source, action, COUNT(*) AS count
            FROM (
                SELECT 'donor'::text AS source, action
                FROM donor.audit_logs WHERE operator_id = %s
                UNION ALL
                SELECT 'user'::text AS source, action
                FROM admin.user_audit_logs WHERE operator_id = %s
                UNION ALL
                SELECT 'admin'::text AS source, action
                FROM admin.admin_account_audit_logs WHERE operator_id = %s
            ) operations
            GROUP BY source, action
            ORDER BY source, count DESC, action
            """,
            (admin_id, admin_id, admin_id),
        )
    row["action_counts"] = counts
    return row


def admin_exists(admin_id: int) -> bool:
    with db_session(admin=True) as conn:
        row = fetchone(conn, "SELECT 1 AS ok FROM admin.admin_users WHERE id = %s", (admin_id,))
    return bool(row)


def get_active_admin(admin_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        return fetchone(
            conn,
            "SELECT * FROM admin.admin_users WHERE id = %s AND is_active = TRUE",
            (admin_id,),
        )


def get_active_admin_by_username(username: str) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        return fetchone(
            conn,
            "SELECT * FROM admin.admin_users WHERE username = %s AND is_active = TRUE",
            (username.strip(),),
        )


def change_admin_password(admin_id: int, old_password: str, new_password: str) -> bool:
    """在同一事务里校验原密码并轮换哈希。失败返回 False，不抛错。"""
    from jzk.passwords import hash_password, verify_password

    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            "SELECT password_hash FROM admin.admin_users WHERE id = %s FOR UPDATE",
            (admin_id,),
        )
        if not row or not verify_password(old_password, row["password_hash"]):
            return False
        conn.execute(
            """
            UPDATE admin.admin_users
            SET password_hash = %s, token_version = token_version + 1, updated_at = now()
            WHERE id = %s
            """,
            (hash_password(new_password), admin_id),
        )
    return True


_DONOR_AUDIT_SELECT = """
    SELECT 'donor'::text AS source, l.id AS record_id, l.action,
           l.donor_code AS target_id,
           COALESCE(l.donor_code, '已删除档案') AS target_name,
           NULL::text AS reason, l.before_data, l.after_data, l.created_at
    FROM donor.audit_logs l
    WHERE l.operator_id = %s
"""

_USER_AUDIT_SELECT = """
    SELECT 'user'::text AS source, l.id AS record_id, l.action,
           CAST(l.user_id AS text) AS target_id,
           COALESCE(NULLIF(u.nickname, ''), NULLIF(u.email, ''), 'UID ' || CAST(l.user_id AS text), '已删除用户') AS target_name,
           l.reason, l.before_data, l.after_data, l.created_at
    FROM admin.user_audit_logs l
    LEFT JOIN app.users u ON u.id = l.user_id
    WHERE l.operator_id = %s
"""

_ADMIN_AUDIT_SELECT = """
    SELECT 'admin'::text AS source, l.id AS record_id, l.action,
           CAST(l.target_admin_id AS text) AS target_id,
           COALESCE(NULLIF(target.display_name, ''), target.username, '已删除管理员') AS target_name,
           l.reason, l.before_data, l.after_data, l.created_at
    FROM admin.admin_account_audit_logs l
    LEFT JOIN admin.admin_users target ON target.id = l.target_admin_id
    WHERE l.operator_id = %s
"""


def list_admin_audit(
    admin_id: int,
    *,
    source: str | None = None,
    page: int = 1,
    page_size: int = 30,
) -> tuple[list[dict[str, Any]], int, int, int]:
    page, page_size, offset = _page_args(page, page_size)
    if source == "donor":
        audit_sql = _DONOR_AUDIT_SELECT
        params: list[Any] = [admin_id]
        count_sql = "SELECT COUNT(*) AS c FROM donor.audit_logs WHERE operator_id = %s"
        count_params = (admin_id,)
    elif source == "user":
        audit_sql = _USER_AUDIT_SELECT
        params = [admin_id]
        count_sql = "SELECT COUNT(*) AS c FROM admin.user_audit_logs WHERE operator_id = %s"
        count_params = (admin_id,)
    elif source == "admin":
        audit_sql = _ADMIN_AUDIT_SELECT
        params = [admin_id]
        count_sql = "SELECT COUNT(*) AS c FROM admin.admin_account_audit_logs WHERE operator_id = %s"
        count_params = (admin_id,)
    else:
        audit_sql = f"{_DONOR_AUDIT_SELECT} UNION ALL {_USER_AUDIT_SELECT} UNION ALL {_ADMIN_AUDIT_SELECT}"
        params = [admin_id, admin_id, admin_id]
        count_sql = """
            SELECT
              (SELECT COUNT(*) FROM donor.audit_logs WHERE operator_id = %s) +
              (SELECT COUNT(*) FROM admin.user_audit_logs WHERE operator_id = %s) +
              (SELECT COUNT(*) FROM admin.admin_account_audit_logs WHERE operator_id = %s) AS c
        """
        count_params = (admin_id, admin_id, admin_id)

    with db_session(admin=True) as conn:
        total = fetchone(conn, count_sql, count_params)
        rows = fetchall(
            conn,
            f"""
            SELECT * FROM ({audit_sql}) operations
            ORDER BY created_at DESC, source, record_id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
    return rows, int((total or {}).get("c") or 0), page, page_size
