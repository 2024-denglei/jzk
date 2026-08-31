"""管理员中心 API。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from api.admin_auth import get_current_admin
from db.admin_admins_repo import admin_exists, get_admin_profile, list_admin_audit, list_admins

router = APIRouter(prefix="/api/admin/admins", tags=["admin-admins"])


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


@router.get("")
async def admin_list_admins(
    q: str | None = None,
    status: Literal["active", "disabled"] | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total, page, page_size = list_admins(
        q=q,
        is_active=None if status is None else status == "active",
        page=page,
        page_size=page_size,
    )
    return {"items": _serialize(rows), "total": total, "page": page, "page_size": page_size}


@router.get("/{admin_id}")
async def admin_get_admin(admin_id: int, admin: dict = Depends(get_current_admin)):
    row = get_admin_profile(admin_id)
    if not row:
        raise HTTPException(status_code=404, detail="管理员不存在")
    return _serialize(row)


@router.get("/{admin_id}/audit")
async def admin_get_admin_audit(
    admin_id: int,
    source: Literal["donor", "user"] | None = None,
    page: int = 1,
    page_size: int = 30,
    admin: dict = Depends(get_current_admin),
):
    if not admin_exists(admin_id):
        raise HTTPException(status_code=404, detail="管理员不存在")
    rows, total, page, page_size = list_admin_audit(
        admin_id,
        source=source,
        page=page,
        page_size=page_size,
    )
    return {"items": _serialize(rows), "total": total, "page": page, "page_size": page_size}
