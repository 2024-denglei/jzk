"""管理端：登录、捐精人 CRUD/启停/导入、审计。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

import config
from api.admin_auth import authenticate_admin, create_admin_token, get_current_admin, set_admin_password
from api.admin_permissions import (
    DONORS_AUDIT_VIEW,
    DONORS_IMPORT,
    DONORS_VIEW,
    DONORS_WRITE,
    SYSTEM_CACHE_REFRESH,
    permissions_for_role,
    require_permission,
)
from api.rate_limit import RateLimitError, RateLimitUnavailable, get_client_ip, rate_limiter
from api.refresh_sessions import (
    InvalidRefreshToken,
    RefreshSessionUnavailable,
    refresh_sessions,
)
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
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=72)


class AdminPasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=72)
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


def _admin_refresh_ttl() -> int:
    return config.ADMIN_REFRESH_TOKEN_HOURS * 60 * 60


def _set_admin_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.ADMIN_REFRESH_COOKIE_NAME,
        value=token,
        max_age=_admin_refresh_ttl(),
        path="/api/admin",
        secure=config.ENVIRONMENT == "production",
        httponly=True,
        samesite="strict",
    )


def _delete_admin_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.ADMIN_REFRESH_COOKIE_NAME,
        path="/api/admin",
        secure=config.ENVIRONMENT == "production",
        httponly=True,
        samesite="strict",
    )


def _admin_access_response(admin: dict) -> dict:
    version = int(admin.get("token_version") or 0)
    token = create_admin_token(int(admin["id"]), admin["role"], version)
    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": {
            "id": admin["id"],
            "username": admin["username"],
            "display_name": admin["display_name"],
            "role": admin["role"],
            "permissions": permissions_for_role(admin["role"]),
        },
    }


@router.post("/login")
async def admin_login(
    body: AdminLoginBody,
    response: Response,
    client_ip: str = Depends(get_client_ip),
):
    account = body.username.strip().lower()
    try:
        rate_limiter.check(
            "admin-login:account",
            account,
            config.ADMIN_LOGIN_LIMIT,
            config.ADMIN_LOGIN_WINDOW_SECONDS,
        )
        rate_limiter.check(
            "admin-login:ip",
            client_ip,
            config.ADMIN_LOGIN_LIMIT,
            config.ADMIN_LOGIN_WINDOW_SECONDS,
        )
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except RateLimitUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    admin = authenticate_admin(body.username, body.password)
    if not admin:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    try:
        rate_limiter.reset("admin-login:account", account)
    except RateLimitUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        refresh_token = refresh_sessions.create(
            int(admin["id"]),
            "admin",
            int(admin.get("token_version") or 0),
            _admin_refresh_ttl(),
        )
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _set_admin_refresh_cookie(response, refresh_token)
    return _admin_access_response(admin)


@router.post("/refresh")
async def admin_refresh(request: Request, response: Response):
    token = request.cookies.get(config.ADMIN_REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="管理端刷新凭证缺失")
    try:
        session = refresh_sessions.inspect(token)
        if session.kind != "admin":
            raise InvalidRefreshToken("刷新凭证类型错误")
        with db_session(admin=True) as conn:
            admin = conn.execute(
                "SELECT * FROM admin.admin_users WHERE id = %s AND is_active = TRUE",
                (session.subject_id,),
            ).fetchone()
        if not admin or int(admin["token_version"]) != session.token_version:
            refresh_sessions.revoke_all("admin", session.subject_id)
            raise InvalidRefreshToken("管理端登录状态已失效")
        new_token = refresh_sessions.rotate(token, session, _admin_refresh_ttl())
    except InvalidRefreshToken as exc:
        _delete_admin_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _set_admin_refresh_cookie(response, new_token)
    return _admin_access_response(dict(admin))


@router.post("/logout")
async def admin_logout(request: Request, response: Response):
    token = request.cookies.get(config.ADMIN_REFRESH_COOKIE_NAME)
    if token:
        try:
            refresh_sessions.revoke(token)
        except RefreshSessionUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    _delete_admin_refresh_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def admin_logout_all(
    response: Response,
    admin: dict = Depends(get_current_admin),
):
    with db_session(admin=True) as conn:
        conn.execute(
            """
            UPDATE admin.admin_users
            SET token_version = token_version + 1, updated_at = now()
            WHERE id = %s
            """,
            (admin["id"],),
        )
    try:
        refresh_sessions.revoke_all("admin", int(admin["id"]))
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _delete_admin_refresh_cookie(response)
    return {"ok": True}


@router.get("/me")
async def admin_me(admin: dict = Depends(get_current_admin)):
    return {
        "id": admin["id"],
        "username": admin["username"],
        "display_name": admin["display_name"],
        "role": admin["role"],
        "permissions": permissions_for_role(admin["role"]),
    }


@router.post("/change-password")
async def admin_change_password(
    body: AdminPasswordBody,
    response: Response,
    admin: dict = Depends(get_current_admin),
):
    if not set_admin_password(int(admin["id"]), body.old_password, body.new_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    try:
        refresh_sessions.revoke_all("admin", int(admin["id"]))
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _delete_admin_refresh_cookie(response)
    return {"ok": True}


@router.get("/donors")
async def admin_list_donors(
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(require_permission(DONORS_VIEW)),
):
    rows, total = list_donors(q=q, status=status, page=page, page_size=page_size)
    return {
        "items": [_serialize_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/donors/{code}")
async def admin_get_donor(code: str, admin: dict = Depends(require_permission(DONORS_VIEW))):
    row = get_donor_by_code(code)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该捐献者")
    return _serialize_row(row)


@router.post("/donors")
async def admin_create_donor(
    body: DonorUpsertBody,
    request: Request,
    admin: dict = Depends(require_permission(DONORS_WRITE)),
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
    admin: dict = Depends(require_permission(DONORS_WRITE)),
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
    admin: dict = Depends(require_permission(DONORS_WRITE)),
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
    admin: dict = Depends(require_permission(DONORS_IMPORT)),
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
    admin: dict = Depends(require_permission(DONORS_AUDIT_VIEW)),
):
    rows, total = list_audit(page=page, page_size=page_size, donor_code=donor_code)
    items = []
    for r in rows:
        items.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/cache/refresh")
async def admin_refresh_cache(request: Request, admin: dict = Depends(require_permission(SYSTEM_CACHE_REFRESH))):
    return refresh_donor_cache(request.app)
