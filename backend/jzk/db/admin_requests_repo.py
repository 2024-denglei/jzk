"""管理员操作申请数据访问。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from jzk.db.pg import db_session, fetchall, fetchone


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


_REQUEST_SELECT = """
    SELECT r.*,
           COALESCE(NULLIF(requester.display_name, ''), requester.username) AS requester_name,
           COALESCE(NULLIF(reviewer.display_name, ''), reviewer.username) AS reviewer_name
    FROM admin.operation_requests r
    JOIN admin.admin_users requester ON requester.id = r.requester_id
    LEFT JOIN admin.admin_users reviewer ON reviewer.id = r.reviewer_id
"""


def create_operation_request(
    *,
    requester_id: int,
    action: str,
    target_type: str,
    target_id: str,
    payload: dict[str, Any],
    before_snapshot: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            INSERT INTO admin.operation_requests
                (requester_id, action, target_type, target_id, payload, before_snapshot, reason)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            RETURNING *
            """,
            (
                requester_id,
                action,
                target_type,
                target_id,
                json.dumps(_jsonable(payload), ensure_ascii=False),
                json.dumps(_jsonable(before_snapshot), ensure_ascii=False) if before_snapshot is not None else None,
                reason,
            ),
        )
    return row or {}


def get_operation_request(request_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        return fetchone(conn, f"{_REQUEST_SELECT} WHERE r.id = %s", (request_id,))


def list_operation_requests(
    *,
    requester_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int, int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where = ["1=1"]
    params: list[Any] = []
    if requester_id is not None:
        where.append("r.requester_id = %s")
        params.append(requester_id)
    if status:
        where.append("r.status = %s")
        params.append(status)
    where_sql = " AND ".join(where)
    with db_session(admin=True) as conn:
        total = fetchone(conn, f"SELECT COUNT(*) AS c FROM admin.operation_requests r WHERE {where_sql}", params)
        rows = fetchall(
            conn,
            f"""
            {_REQUEST_SELECT}
            WHERE {where_sql}
            ORDER BY CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END, r.created_at DESC, r.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, (page - 1) * page_size],
        )
    return rows, int((total or {}).get("c") or 0), page, page_size


def claim_operation_request(request_id: int, reviewer_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        return fetchone(
            conn,
            """
            UPDATE admin.operation_requests
            SET status = 'processing', reviewer_id = %s, reviewed_at = now(), updated_at = now(),
                execution_error = NULL
            WHERE id = %s AND status = 'pending' AND requester_id <> %s
            RETURNING *
            """,
            (reviewer_id, request_id, reviewer_id),
        )


def complete_operation_request(
    request_id: int,
    *,
    status: str,
    review_comment: str | None = None,
    execution_error: str | None = None,
) -> dict[str, Any]:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            UPDATE admin.operation_requests
            SET status = %s, review_comment = %s, execution_error = %s,
                executed_at = CASE WHEN %s IN ('approved', 'failed') THEN now() ELSE executed_at END,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (status, review_comment, execution_error, status, request_id),
        )
    return row or {}


def reject_operation_request(request_id: int, reviewer_id: int, comment: str) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        return fetchone(
            conn,
            """
            UPDATE admin.operation_requests
            SET status = 'rejected', reviewer_id = %s, review_comment = %s,
                reviewed_at = now(), updated_at = now()
            WHERE id = %s AND status = 'pending' AND requester_id <> %s
            RETURNING *
            """,
            (reviewer_id, comment, request_id, reviewer_id),
        )


def cancel_operation_request(request_id: int, requester_id: int) -> dict[str, Any] | None:
    with db_session(admin=True) as conn:
        return fetchone(
            conn,
            """
            UPDATE admin.operation_requests
            SET status = 'cancelled', updated_at = now()
            WHERE id = %s AND requester_id = %s AND status = 'pending'
            RETURNING *
            """,
            (request_id, requester_id),
        )

