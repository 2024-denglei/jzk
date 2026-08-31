"""捐精人数据访问与审计。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from db.donor_fields import DB_TO_MATCH_CN, DONOR_DB_COLUMNS
from db.pg import db_session, fetchall, fetchone


def _jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def row_to_match_dict(row: dict[str, Any]) -> dict[str, Any]:
    """DB 行 → 匹配引擎中文列 dict。"""
    out: dict[str, Any] = {}
    for db_col, cn in DB_TO_MATCH_CN.items():
        if db_col in row:
            val = row[db_col]
            if isinstance(val, datetime):
                val = val.date().isoformat() if hasattr(val, "date") else val.isoformat()
            elif isinstance(val, date):
                val = val.isoformat()
            out[cn] = val
    # 兼容旧匹配逻辑：血型/RH/唇形/体征指数别名
    out["血型"] = out.get("ABO血型")
    out["RH血型"] = out.get("Rh血型")
    out["唇形"] = out.get("唇型")
    out["体征指数"] = out.get("BMI")
    out["头发颜色"] = out.get("发色")
    hobby_pairs = [
        ("爱好运动", "运动健身"),
        ("爱好艺术", "文化艺术"),
        ("爱好休闲", "休闲娱乐"),
        ("爱好旅游", "旅游度假"),
        ("爱好阅读", "小说书籍"),
        ("爱好美食", "美食饮品"),
    ]
    hobby_parts: list[str] = []
    for key, label in hobby_pairs:
        v = out.get(key)
        s = str(v).strip() if v is not None else ""
        if s in ("", "None", "nan"):
            continue
        if s == "有":
            hobby_parts.append(label)
        elif s != "无":
            hobby_parts.append(f"{label}·{s}")
    out["爱好"] = "；".join(hobby_parts)
    return out


def load_donors_dataframe(active_only: bool = False) -> pd.DataFrame:
    """从 PG 加载捐精人到 DataFrame（中文列，供匹配使用）。"""
    sql = "SELECT * FROM donor.donors"
    if active_only:
        sql += " WHERE status = 'active'"
    sql += " ORDER BY specimen_count DESC NULLS LAST, id"
    with db_session() as conn:
        rows = fetchall(conn, sql)
    if not rows:
        return pd.DataFrame(columns=list(DB_TO_MATCH_CN.values()))
    records = [row_to_match_dict(r) for r in rows]
    return pd.DataFrame(records)


def get_donor_by_code(code: str) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            "SELECT * FROM donor.donors WHERE code = %s OR CAST(serial_no AS TEXT) = %s",
            (code, code),
        )


def list_donors(
    *,
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    where = ["1=1"]
    params: list[Any] = []
    if status:
        where.append("status = %s")
        params.append(status)
    if q:
        where.append("(code ILIKE %s OR CAST(serial_no AS TEXT) ILIKE %s OR ethnicity ILIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])
    where_sql = " AND ".join(where)
    with db_session(admin=True) as conn:
        total = fetchone(conn, f"SELECT COUNT(*) AS c FROM donor.donors WHERE {where_sql}", params)["c"]
        rows = fetchall(
            conn,
            f"""
            SELECT * FROM donor.donors
            WHERE {where_sql}
            ORDER BY updated_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, (page - 1) * page_size],
        )
    return rows, int(total)


def write_audit(
    conn,
    *,
    donor_id: int | None,
    donor_code: str | None,
    action: str,
    operator_id: int | None,
    before: dict | None,
    after: dict | None,
) -> None:
    conn.execute(
        """
        INSERT INTO donor.audit_logs (donor_id, donor_code, action, operator_id, before_data, after_data)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            donor_id,
            donor_code,
            action,
            operator_id,
            json.dumps(_jsonable(before), ensure_ascii=False) if before is not None else None,
            json.dumps(_jsonable(after), ensure_ascii=False) if after is not None else None,
        ),
    )


def _clean_payload(data: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k in DONOR_DB_COLUMNS:
        if k not in data:
            continue
        v = data[k]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out[k] = None
            continue
        if k == "birth_date" and v:
            if isinstance(v, datetime):
                out[k] = v.date()
            elif isinstance(v, date):
                out[k] = v
            else:
                s = str(v)[:10]
                out[k] = s if s and s not in ("NaT", "nan", "None") else None
            continue
        if k in ("height_cm", "specimen_count", "serial_no"):
            try:
                out[k] = int(float(v)) if v != "" and v is not None else None
            except (TypeError, ValueError):
                out[k] = None
            continue
        if k in ("weight_kg", "bmi"):
            try:
                out[k] = float(v) if v != "" and v is not None else None
            except (TypeError, ValueError):
                out[k] = None
            continue
        if k == "status":
            out[k] = v if v in ("active", "disabled") else "active"
            continue
        out[k] = str(v).strip() if v is not None else None
    return out


def upsert_donor(
    data: dict[str, Any],
    *,
    operator_id: int | None = None,
    action: str = "upsert",
) -> dict[str, Any]:
    payload = _clean_payload(data)
    if not payload.get("code"):
        raise ValueError("代号不能为空")
    payload.setdefault("status", "active")
    payload.setdefault("specimen_count", 10)

    cols = [c for c in DONOR_DB_COLUMNS if c in payload]
    with db_session(admin=True) as conn:
        existing = fetchone(conn, "SELECT * FROM donor.donors WHERE code = %s", (payload["code"],))
        if existing:
            sets = ", ".join(f"{c} = %s" for c in cols if c != "code")
            vals = [payload[c] for c in cols if c != "code"]
            vals.extend([operator_id, payload["code"]])
            conn.execute(
                f"""
                UPDATE donor.donors
                SET {sets}, updated_at = now(), updated_by = %s
                WHERE code = %s
                """,
                vals,
            )
            row = fetchone(conn, "SELECT * FROM donor.donors WHERE code = %s", (payload["code"],))
            write_audit(
                conn,
                donor_id=row["id"],
                donor_code=row["code"],
                action="update" if action == "upsert" else action,
                operator_id=operator_id,
                before=dict(existing),
                after=dict(row),
            )
            return row

        col_sql = ", ".join(cols + ["created_by", "updated_by"])
        placeholders = ", ".join(["%s"] * (len(cols) + 2))
        vals = [payload[c] for c in cols] + [operator_id, operator_id]
        row = fetchone(
            conn,
            f"""
            INSERT INTO donor.donors ({col_sql})
            VALUES ({placeholders})
            RETURNING *
            """,
            vals,
        )
        write_audit(
            conn,
            donor_id=row["id"],
            donor_code=row["code"],
            action="create" if action == "upsert" else action,
            operator_id=operator_id,
            before=None,
            after=dict(row),
        )
        return row


def set_donor_status(code: str, status: str, operator_id: int | None) -> dict[str, Any]:
    if status not in ("active", "disabled"):
        raise ValueError("status 必须为 active 或 disabled")
    with db_session(admin=True) as conn:
        before = fetchone(conn, "SELECT * FROM donor.donors WHERE code = %s", (code,))
        if not before:
            raise KeyError(code)
        conn.execute(
            """
            UPDATE donor.donors
            SET status = %s, updated_at = now(), updated_by = %s
            WHERE code = %s
            """,
            (status, operator_id, code),
        )
        row = fetchone(conn, "SELECT * FROM donor.donors WHERE code = %s", (code,))
        write_audit(
            conn,
            donor_id=row["id"],
            donor_code=code,
            action="disable" if status == "disabled" else "enable",
            operator_id=operator_id,
            before=dict(before),
            after=dict(row),
        )
        return row


def list_audit(page: int = 1, page_size: int = 50, donor_code: str | None = None):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    where = "1=1"
    params: list[Any] = []
    if donor_code:
        where = "donor_code = %s"
        params.append(donor_code)
    with db_session(admin=True) as conn:
        total = fetchone(conn, f"SELECT COUNT(*) AS c FROM donor.audit_logs WHERE {where}", params)["c"]
        rows = fetchall(
            conn,
            f"""
            SELECT l.*, COALESCE(NULLIF(a.display_name, ''), a.username) AS operator_name
            FROM donor.audit_logs l
            LEFT JOIN admin.admin_users a ON a.id = l.operator_id
            WHERE {where}
            ORDER BY l.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, (page - 1) * page_size],
        )
    return rows, int(total)


def clear_all_donors() -> int:
    """清空捐精人主表（审计日志 donor_id 置空）。返回删除行数。"""
    with db_session(admin=True) as conn:
        row = fetchone(conn, "SELECT COUNT(*) AS c FROM donor.donors")
        before = int(row["c"]) if row else 0
        conn.execute("DELETE FROM donor.donors")
        return before


def create_import_batch(filename: str, operator_id: int | None, success: int, fail: int, errors: list) -> dict:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            INSERT INTO donor.import_batches (filename, operator_id, success_count, fail_count, error_summary)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            RETURNING *
            """,
            (filename, operator_id, success, fail, json.dumps(errors, ensure_ascii=False)),
        )
        return row
