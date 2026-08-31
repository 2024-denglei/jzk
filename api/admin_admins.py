"""管理员中心 API。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.admin_permissions import ADMINS_MANAGE, ADMINS_VIEW, require_permission
from api.auth_utils import hash_password
from db.admin_admins_repo import (
    admin_exists,
    create_admin_account,
    get_admin_profile,
    list_admin_audit,
    list_admins,
    set_admin_account_active,
)

router = APIRouter(prefix="/api/admin/admins", tags=["admin-admins"])


class AdminCreateBody(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["super_admin", "donor_admin"] = "donor_admin"


class AdminStateBody(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


def _state_reason(body: AdminStateBody) -> str:
    reason = body.reason.strip()
    if len(reason) < 2:
        raise HTTPException(status_code=400, detail="操作原因至少需要 2 个字")
    return reason


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


@router.post("")
async def admin_create_admin(
    body: AdminCreateBody,
    admin: dict = Depends(require_permission(ADMINS_MANAGE)),
):
    try:
        row = create_admin_account(
            username=body.username,
            password_hash=hash_password(body.password),
            display_name=body.display_name,
            role=body.role,
            operator_id=int(admin["id"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _serialize(row)


@router.get("")
async def admin_list_admins(
    q: str | None = None,
    status: Literal["active", "disabled"] | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(require_permission(ADMINS_VIEW)),
):
    rows, total, page, page_size = list_admins(
        q=q,
        is_active=None if status is None else status == "active",
        page=page,
        page_size=page_size,
    )
    return {"items": _serialize(rows), "total": total, "page": page, "page_size": page_size}


@router.get("/{admin_id}")
async def admin_get_admin(admin_id: int, admin: dict = Depends(require_permission(ADMINS_VIEW))):
    row = get_admin_profile(admin_id)
    if not row:
        raise HTTPException(status_code=404, detail="管理员不存在")
    return _serialize(row)


@router.delete("/{admin_id}")
async def admin_delete_admin(
    admin_id: int,
    body: AdminStateBody,
    admin: dict = Depends(require_permission(ADMINS_MANAGE)),
):
    try:
        row = set_admin_account_active(
            admin_id,
            is_active=False,
            operator_id=int(admin["id"]),
            reason=_state_reason(body),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="管理员不存在")
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _serialize(row)


@router.post("/{admin_id}/restore")
async def admin_restore_admin(
    admin_id: int,
    body: AdminStateBody,
    admin: dict = Depends(require_permission(ADMINS_MANAGE)),
):
    try:
        row = set_admin_account_active(
            admin_id,
            is_active=True,
            operator_id=int(admin["id"]),
            reason=_state_reason(body),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="管理员不存在")
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _serialize(row)


@router.get("/{admin_id}/audit")
async def admin_get_admin_audit(
    admin_id: int,
    source: Literal["donor", "user", "admin"] | None = None,
    page: int = 1,
    page_size: int = 30,
    admin: dict = Depends(require_permission(ADMINS_VIEW)),
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
