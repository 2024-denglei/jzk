"""Excel 导入捐精人（对齐《文本信息》模板，兼容旧人造表）。"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from db.donor_fields import map_excel_columns
from db.donors_repo import clear_all_donors, create_import_batch, upsert_donor


def _cell(v) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str) and v.strip() in ("", "nan", "NaT", "None"):
        return None
    return v


def dataframe_to_donor_payloads(df: pd.DataFrame) -> list[dict[str, Any]]:
    colmap = map_excel_columns(list(df.columns))
    payloads = []
    for _, row in df.iterrows():
        data: dict[str, Any] = {}
        for excel_col, db_col in colmap.items():
            data[db_col] = _cell(row.get(excel_col))
        if not data.get("code"):
            continue
        data.setdefault("status", "active")
        if data.get("specimen_count") is None:
            data["specimen_count"] = 10
        payloads.append(data)
    return payloads


def import_excel_bytes(
    content: bytes,
    filename: str,
    operator_id: int | None,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    bio = BytesIO(content)
    # 兼容 xls / xlsx
    try:
        df = pd.read_excel(bio, sheet_name=0)
    except Exception:
        bio.seek(0)
        df = pd.read_excel(bio, sheet_name=0, engine="xlrd")

    cleared = 0
    if replace:
        cleared = clear_all_donors()

    payloads = dataframe_to_donor_payloads(df)
    success = 0
    errors: list[dict] = []
    for i, payload in enumerate(payloads):
        try:
            upsert_donor(payload, operator_id=operator_id, action="import")
            success += 1
        except Exception as e:
            errors.append({"row": i + 2, "code": payload.get("code"), "error": str(e)})
    fail = len(errors)
    # 无有效行也记批次
    if not payloads and len(df) > 0:
        errors.append({"row": 0, "error": "未识别到有效列或代号为空，请使用《文本信息》模板"})
        fail = max(fail, 1)

    batch = create_import_batch(filename, operator_id, success, fail, errors[:50])
    return {
        "batch_id": batch["id"],
        "filename": filename,
        "success_count": success,
        "fail_count": fail,
        "errors": errors[:50],
        "total_rows": len(df),
        "mapped_rows": len(payloads),
        "cleared_count": cleared,
        "replaced": replace,
    }
