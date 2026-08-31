"""管理端：登录、捐精人 CRUD/启停/导入、审计。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from api.admin_auth import authenticate_admin, create_admin_token, get_current_admin, set_admin_password
from core.data_loader import get_donor_display_info
from core.runtime_cache import refresh_donor_cache, update_donor_status_cache
from db.donor_import import import_excel_bytes
from db.donors_repo import (
    get_donor_by_code,
    list_audit,
    list_donors,
    set_donor_status,
    upsert_donor,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminLoginBody(BaseModel):
    username: str
    password: str


class AdminPasswordBody(BaseModel):
    new_password: str = Field(min_length=8, max_length=72)


class DonorUpsertBody(BaseModel):
    code: str
    serial_no: int | None = None
    abo_blood: str | None = None
    rh_blood: str | None = None
    ethnicity: str | None = None
    hometown: str | None = None
    education: str | None = None
    occupation: str | None = None
    birth_date: str | None = None
    constellation: str | None = None
    height_cm: int | None = None
    weight_kg: float | None = None
    bmi: float | None = None
    figure: str | None = None
    face_shape: str | None = None
    skin_color: str | None = None
    hair_color: str | None = None
    hair_style: str | None = None
    hair_volume: str | None = None
    eyelid: str | None = None
    nose_bridge: str | None = None
    lip_shape: str | None = None
    sideburns: str | None = None
    mustache: str | None = None
    personality: str | None = None
    hobby_sports: str | None = None
    hobby_arts: str | None = None
    hobby_leisure: str | None = None
    hobby_travel: str | None = None
    hobby_reading: str | None = None
    hobby_food: str | None = None
    drink_history: str | None = None
    smoke_history: str | None = None
    personal_disease: str | None = None
    present_illness: str | None = None
    past_illness: str | None = None
    surgery_history: str | None = None
    personal_life_hist: str | None = None
    partners_6m: str | None = None
    std_history: str | None = None
    marital_fertility: str | None = None
    marriage_age: str | None = None
    children_info: str | None = None
    genetic_history: str | None = None
    chromosome_disease: str | None = None
    monogenic_disease: str | None = None
    polygenic_disease: str | None = None
    consanguinity: str | None = None
    status: str | None = "active"
    specimen_count: int | None = 10


class StatusBody(BaseModel):
    status: str


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    out["donor_info"] = get_donor_display_info(row)
    return out


@router.post("/login")
async def admin_login(body: AdminLoginBody):
    admin = authenticate_admin(body.username, body.password)
    if not admin:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    token = create_admin_token(int(admin["id"]), admin["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": {
            "id": admin["id"],
            "username": admin["username"],
            "display_name": admin["display_name"],
            "role": admin["role"],
        },
    }


@router.get("/me")
async def admin_me(admin: dict = Depends(get_current_admin)):
    return {
        "id": admin["id"],
        "username": admin["username"],
        "display_name": admin["display_name"],
        "role": admin["role"],
    }


@router.post("/change-password")
async def admin_change_password(body: AdminPasswordBody, admin: dict = Depends(get_current_admin)):
    set_admin_password(int(admin["id"]), body.new_password)
    return {"ok": True}


@router.get("/donors")
async def admin_list_donors(
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
):
    rows, total = list_donors(q=q, status=status, page=page, page_size=page_size)
    return {
        "items": [_serialize_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/donors/{code}")
async def admin_get_donor(code: str, admin: dict = Depends(get_current_admin)):
    row = get_donor_by_code(code)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该捐献者")
    return _serialize_row(row)


@router.post("/donors")
async def admin_create_donor(
    body: DonorUpsertBody,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    try:
        row = upsert_donor(body.model_dump(), operator_id=int(admin["id"]), action="create")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    refresh_donor_cache(request.app)
    return _serialize_row(row)


@router.put("/donors/{code}")
async def admin_update_donor(
    code: str,
    body: DonorUpsertBody,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    data = body.model_dump()
    data["code"] = code
    try:
        row = upsert_donor(data, operator_id=int(admin["id"]), action="update")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    refresh_donor_cache(request.app)
    return _serialize_row(row)


@router.post("/donors/{code}/status")
async def admin_set_status(
    code: str,
    body: StatusBody,
    request: Request,
    admin: dict = Depends(get_current_admin),
):
    try:
        row = set_donor_status(code, body.status, int(admin["id"]))
    except KeyError:
        raise HTTPException(status_code=404, detail="未找到该捐献者")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not update_donor_status_cache(request.app, code, body.status):
        refresh_donor_cache(request.app)
    return _serialize_row(row)


@router.post("/donors/import")
async def admin_import_donors(
    request: Request,
    file: UploadFile = File(...),
    admin: dict = Depends(get_current_admin),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    result = import_excel_bytes(content, file.filename or "import.xlsx", int(admin["id"]))
    refresh_donor_cache(request.app)
    return result


@router.get("/audit")
async def admin_audit(
    page: int = 1,
    page_size: int = 50,
    donor_code: str | None = None,
    admin: dict = Depends(get_current_admin),
):
    rows, total = list_audit(page=page, page_size=page_size, donor_code=donor_code)
    items = []
    for r in rows:
        items.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/cache/refresh")
async def admin_refresh_cache(request: Request, admin: dict = Depends(get_current_admin)):
    return refresh_donor_cache(request.app)
