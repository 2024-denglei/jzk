"""管理员中心：管理员资料、操作统计与聚合审计。"""

from __future__ import annotations

from typing import Any

from db.pg import db_session, fetchall, fetchone


def _page_args(page: int, page_size: int) -> tuple[int, int, int]:
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 100))
    return safe_page, safe_size, (safe_page - 1) * safe_size


_ADMIN_SELECT = """
    SELECT a.id, a.username, a.display_name, a.role, a.is_active,
           a.created_at, a.updated_at,
           COALESCE(d.operation_count, 0) AS donor_operation_count,
           COALESCE(u.operation_count, 0) AS user_operation_count,
           COALESCE(d.operation_count, 0) + COALESCE(u.operation_count, 0) AS operation_count,
           GREATEST(d.last_operation_at, u.last_operation_at) AS last_operation_at
    FROM admin.admin_users a
    LEFT JOIN (
        SELECT operator_id, COUNT(*) AS operation_count, MAX(created_at) AS last_operation_at
        FROM donor.audit_logs GROUP BY operator_id
    ) d ON d.operator_id = a.id
    LEFT JOIN (
        SELECT operator_id, COUNT(*) AS operation_count, MAX(created_at) AS last_operation_at
        FROM admin.user_audit_logs GROUP BY operator_id
    ) u ON u.operator_id = a.id
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
            ) operations
            GROUP BY source, action
            ORDER BY source, count DESC, action
            """,
            (admin_id, admin_id),
        )
    row["action_counts"] = counts
    return row


def admin_exists(admin_id: int) -> bool:
    with db_session(admin=True) as conn:
        row = fetchone(conn, "SELECT 1 AS ok FROM admin.admin_users WHERE id = %s", (admin_id,))
    return bool(row)


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
    else:
        audit_sql = f"{_DONOR_AUDIT_SELECT} UNION ALL {_USER_AUDIT_SELECT}"
        params = [admin_id, admin_id]
        count_sql = """
            SELECT
              (SELECT COUNT(*) FROM donor.audit_logs WHERE operator_id = %s) +
              (SELECT COUNT(*) FROM admin.user_audit_logs WHERE operator_id = %s) AS c
        """
        count_params = (admin_id, admin_id)

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
