"""管理端用户档案查询、账号控制与审计。"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from db.pg import db_session, fetchall, fetchone


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _page_args(page: int, page_size: int) -> tuple[int, int, int]:
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 100))
    return safe_page, safe_size, (safe_page - 1) * safe_size


def get_user_summary() -> dict[str, int]:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE status = 'active') AS active,
              COUNT(*) FILTER (WHERE status = 'disabled') AS disabled,
              COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS today_new
            FROM app.users
            """,
        ) or {}
    return {key: int(row.get(key) or 0) for key in ("total", "active", "disabled", "today_new")}


def list_users(
    *,
    q: str | None = None,
    status: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    page, page_size, offset = _page_args(page, page_size)
    where = ["1=1"]
    params: list[Any] = []
    if q:
        where.append(
            "(CAST(u.id AS TEXT) ILIKE %s OR u.nickname ILIKE %s OR u.email ILIKE %s OR COALESCE(u.phone, '') ILIKE %s)"
        )
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like])
    if status:
        where.append("u.status = %s")
        params.append(status)
    if created_from:
        where.append("u.created_at >= %s")
        params.append(created_from)
    if created_to:
        where.append("u.created_at < %s::date + INTERVAL '1 day'")
        params.append(created_to)
    where_sql = " AND ".join(where)

    with db_session(admin=True) as conn:
        total_row = fetchone(conn, f"SELECT COUNT(*) AS c FROM app.users u WHERE {where_sql}", params)
        rows = fetchall(
            conn,
            f"""
            SELECT u.id, u.email, u.phone, u.nickname, u.status, u.created_at,
                   u.updated_at, u.last_login_at, u.disabled_at, u.disabled_reason,
                   COALESCE(f.c, 0) AS favorite_count,
                   COALESCE(h.c, 0) AS history_count,
                   COALESCE(ch.c, 0) AS chat_count
            FROM app.users u
            LEFT JOIN (SELECT user_id, COUNT(*) AS c FROM app.favorites GROUP BY user_id) f ON f.user_id = u.id
            LEFT JOIN (SELECT user_id, COUNT(*) AS c FROM app.history GROUP BY user_id) h ON h.user_id = u.id
            LEFT JOIN (SELECT user_id, COUNT(*) AS c FROM app.chats GROUP BY user_id) ch ON ch.user_id = u.id
            WHERE {where_sql}
            ORDER BY u.created_at DESC, u.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
    return rows, int((total_row or {}).get("c") or 0)


def get_user_profile(user_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            SELECT u.id, u.email, u.phone, u.nickname, u.status, u.created_at,
                   u.updated_at, u.last_login_at, u.disabled_at, u.disabled_reason,
                   COALESCE(f.c, 0) AS favorite_count,
                   COALESCE(h.c, 0) AS history_count,
                   COALESCE(ch.c, 0) AS chat_count,
                   p.filters_json, p.priority_json, p.updated_at AS preferences_updated_at
            FROM app.users u
            LEFT JOIN (SELECT user_id, COUNT(*) AS c FROM app.favorites GROUP BY user_id) f ON f.user_id = u.id
            LEFT JOIN (SELECT user_id, COUNT(*) AS c FROM app.history GROUP BY user_id) h ON h.user_id = u.id
            LEFT JOIN (SELECT user_id, COUNT(*) AS c FROM app.chats GROUP BY user_id) ch ON ch.user_id = u.id
            LEFT JOIN app.preferences p ON p.user_id = u.id
            WHERE u.id = %s
            """,
            (user_id,),
        )
    if not row:
        return None
    row["preferences"] = {
        "filters": _loads(row.pop("filters_json", None), {}),
        "priority": _loads(row.pop("priority_json", None), []),
        "updated_at": row.pop("preferences_updated_at", None),
    }
    return row


def list_user_favorites(user_id: int, page: int = 1, page_size: int = 20):
    page, page_size, offset = _page_args(page, page_size)
    with db_session(admin=True) as conn:
        total = fetchone(conn, "SELECT COUNT(*) AS c FROM app.favorites WHERE user_id = %s", (user_id,))
        rows = fetchall(
            conn,
            """
            SELECT f.id, f.donor_code, f.created_at,
                   d.status AS donor_status, d.education, d.ethnicity, d.height_cm, d.specimen_count
            FROM app.favorites f
            LEFT JOIN donor.donors d ON d.code = f.donor_code
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, page_size, offset),
        )
    return rows, int((total or {}).get("c") or 0), page, page_size


def list_user_history(user_id: int, kind: str | None = None, page: int = 1, page_size: int = 20):
    page, page_size, offset = _page_args(page, page_size)
    where = "user_id = %s"
    params: list[Any] = [user_id]
    if kind:
        where += " AND kind = %s"
        params.append(kind)
    with db_session(admin=True) as conn:
        total = fetchone(conn, f"SELECT COUNT(*) AS c FROM app.history WHERE {where}", params)
        rows = fetchall(
            conn,
            f"""
            SELECT id, kind, donor_code, payload, created_at
            FROM app.history WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
    for row in rows:
        row["payload"] = _loads(row.get("payload"), None)
    return rows, int((total or {}).get("c") or 0), page, page_size


def list_user_chats(user_id: int, page: int = 1, page_size: int = 20):
    page, page_size, offset = _page_args(page, page_size)
    with db_session(admin=True) as conn:
        total = fetchone(conn, "SELECT COUNT(*) AS c FROM app.chats WHERE user_id = %s", (user_id,))
        rows = fetchall(
            conn,
            """
            SELECT id, session_id, title, messages_json, created_at, updated_at
            FROM app.chats WHERE user_id = %s
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, page_size, offset),
        )
    for row in rows:
        row["message_count"] = len(_loads(row.pop("messages_json", None), []))
    return rows, int((total or {}).get("c") or 0), page, page_size


def get_user_chat(user_id: int, chat_id: int, operator_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        row = fetchone(conn, "SELECT * FROM app.chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
        if not row:
            return None
        conn.execute(
            """
            INSERT INTO admin.user_audit_logs (user_id, action, operator_id, reason)
            VALUES (%s, 'view_chat', %s, %s)
            """,
            (user_id, operator_id, f"查看会话 {chat_id}"),
        )
    row["messages"] = _loads(row.pop("messages_json", None), [])
    row["candidates"] = _loads(row.pop("candidates_json", None), [])
    row["state"] = _loads(row.pop("state_json", None), {})
    # 本地 JSON Trace 已停用；V2 管理端只通过 generation_steps 读取数据库 Trace。
    row["turns"] = []
    return row


def control_user(
    user_id: int,
    action: str,
    operator_id: int,
    reason: str,
    *,
    expected_updated_at: str | None = None,
) -> dict[str, Any]:
    if action not in {"kick", "disable", "enable"}:
        raise ValueError("不支持的账号操作")
    with db_session(admin=True) as conn:
        before = fetchone(
            conn,
            "SELECT id, status, token_version, disabled_at, disabled_reason, updated_at FROM app.users WHERE id = %s FOR UPDATE",
            (user_id,),
        )
        if not before:
            raise KeyError(user_id)
        if expected_updated_at is not None and _jsonable(before.get("updated_at")) != expected_updated_at:
            raise ValueError("目标数据在申请后已发生变化，请重新提交申请")
        if action == "kick":
            conn.execute(
                "UPDATE app.users SET token_version = token_version + 1, updated_at = now() WHERE id = %s",
                (user_id,),
            )
        elif action == "disable":
            conn.execute(
                """
                UPDATE app.users
                SET status = 'disabled', token_version = token_version + 1,
                    disabled_at = now(), disabled_reason = %s, updated_at = now()
                WHERE id = %s
                """,
                (reason, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE app.users
                SET status = 'active', disabled_at = NULL, disabled_reason = NULL, updated_at = now()
                WHERE id = %s
                """,
                (user_id,),
            )
        after = fetchone(
            conn,
            "SELECT id, status, token_version, disabled_at, disabled_reason, updated_at FROM app.users WHERE id = %s",
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO admin.user_audit_logs
                (user_id, action, operator_id, reason, before_data, after_data)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                user_id,
                action,
                operator_id,
                reason,
                json.dumps(_jsonable(before), ensure_ascii=False),
                json.dumps(_jsonable(after), ensure_ascii=False),
            ),
        )
    return after or {}


def list_user_audit(user_id: int, page: int = 1, page_size: int = 20):
    page, page_size, offset = _page_args(page, page_size)
    with db_session(admin=True) as conn:
        total = fetchone(conn, "SELECT COUNT(*) AS c FROM admin.user_audit_logs WHERE user_id = %s", (user_id,))
        rows = fetchall(
            conn,
            """
            SELECT l.id, l.action, l.reason, l.created_at, l.operator_id,
                   COALESCE(NULLIF(a.display_name, ''), a.username) AS operator_name
            FROM admin.user_audit_logs l
            LEFT JOIN admin.admin_users a ON a.id = l.operator_id
            WHERE l.user_id = %s
            ORDER BY l.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, page_size, offset),
        )
    return rows, int((total or {}).get("c") or 0), page, page_size
