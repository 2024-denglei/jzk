"""管理端用户档案、关联记录和账号控制 API。"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.admin_auth import get_current_admin
from db.admin_users_repo import (
    control_user,
    get_user_chat,
    get_user_profile,
    get_user_summary,
    list_user_audit,
    list_user_chats,
    list_user_favorites,
    list_user_history,
    list_users,
)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


class UserControlBody(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return value or ""
    name, domain = value.split("@", 1)
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}***@{domain}"


def _mask_phone(value: str | None) -> str:
    if not value:
        return ""
    return f"{value[:3]}****{value[-4:]}" if len(value) >= 8 else "****"


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    out = _serialize(row)
    out["email"] = _mask_email(row.get("email"))
    out["phone"] = _mask_phone(row.get("phone"))
    return out


def _page(items: list[dict[str, Any]], total: int, page: int, page_size: int):
    return {
        "items": _serialize(items),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/summary")
async def admin_user_summary(admin: dict = Depends(get_current_admin)):
    return get_user_summary()


@router.get("")
async def admin_list_users(
    q: str | None = None,
    status: Literal["active", "disabled"] | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total = list_users(
        q=q,
        status=status,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_public_user(row) for row in rows],
        "total": total,
        "page": max(1, page),
        "page_size": max(1, min(page_size, 100)),
    }


@router.get("/{user_id}")
async def admin_get_user(user_id: int, admin: dict = Depends(get_current_admin)):
    row = get_user_profile(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _public_user(row)


@router.get("/{user_id}/favorites")
async def admin_user_favorites(
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total, page, page_size = list_user_favorites(user_id, page, page_size)
    return _page(rows, total, page, page_size)


@router.get("/{user_id}/history")
async def admin_user_history(
    user_id: int,
    kind: Literal["browse", "search", "match"] | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total, page, page_size = list_user_history(user_id, kind, page, page_size)
    return _page(rows, total, page, page_size)


@router.get("/{user_id}/chats")
async def admin_user_chats(
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total, page, page_size = list_user_chats(user_id, page, page_size)
    return _page(rows, total, page, page_size)


@router.get("/{user_id}/chats/{chat_id}")
async def admin_user_chat(
    user_id: int,
    chat_id: int,
    admin: dict = Depends(get_current_admin),
):
    row = get_user_chat(user_id, chat_id, int(admin["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _serialize(row)


@router.get("/{user_id}/audit")
async def admin_user_audit(
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total, page, page_size = list_user_audit(user_id, page, page_size)
    return _page(rows, total, page, page_size)


async def _control(user_id: int, action: str, body: UserControlBody, admin: dict):
    try:
        row = control_user(user_id, action, int(admin["id"]), body.reason.strip())
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _serialize(row)


@router.post("/{user_id}/kick")
async def admin_kick_user(
    user_id: int,
    body: UserControlBody,
    admin: dict = Depends(get_current_admin),
):
    return await _control(user_id, "kick", body, admin)


@router.post("/{user_id}/disable")
async def admin_disable_user(
    user_id: int,
    body: UserControlBody,
    admin: dict = Depends(get_current_admin),
):
    return await _control(user_id, "disable", body, admin)


@router.post("/{user_id}/enable")
async def admin_enable_user(
    user_id: int,
    body: UserControlBody,
    admin: dict = Depends(get_current_admin),
):
    return await _control(user_id, "enable", body, admin)
