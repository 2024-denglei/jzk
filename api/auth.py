"""邮箱/手机号注册、登录与密码找回 API。"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from psycopg.errors import UniqueViolation

import config
from api.auth_utils import create_access_token, get_current_user_id
from api.rate_limit import (
    RateLimitError,
    RateLimitUnavailable,
    get_client_ip,
    rate_limiter,
)
from api.refresh_sessions import (
    InvalidRefreshToken,
    RefreshSessionUnavailable,
    refresh_sessions,
)
from api.security import validate_cookie_origin
from api.verification_codes import VerificationCodeError, VerificationCodeRateLimitError, verification_codes
from db.users_repo import (
    bump_token_version,
    create_user,
    find_email_or_phone,
    get_by_id,
    get_by_login_field,
    get_by_phone,
    get_id_by_phone,
    record_login,
    update_nickname,
    update_password,
)
from password_policy import validate_password_strength
from passwords import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
CodePurpose = Literal["register", "login", "reset_password"]


def _valid_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or "." not in value.split("@")[-1]:
        raise ValueError("邮箱格式不正确")
    return value


def _valid_phone(value: str) -> str:
    """将中国大陆手机号统一保存为 +86xxxxxxxxxxx。"""
    value = re.sub(r"[\s-]", "", value.strip())
    if value.startswith("0086"):
        value = "+86" + value[4:]
    digits = value[3:] if value.startswith("+86") else value
    if not re.fullmatch(r"1[3-9]\d{9}", digits):
        raise ValueError("手机号格式不正确")
    return f"+86{digits}"


class SendCodeRequest(BaseModel):
    phone: str
    purpose: CodePurpose

    @field_validator("phone")
    @classmethod
    def phone_ok(cls, value: str) -> str:
        return _valid_phone(value)


class RegisterRequest(BaseModel):
    email: str
    phone: str
    password: str = Field(min_length=10, max_length=72)
    code: str = Field(pattern=r"^\d{6}$")
    nickname: str = Field(default="", max_length=40)

    @field_validator("email")
    @classmethod
    def email_ok(cls, value: str) -> str:
        return _valid_email(value)

    @field_validator("phone")
    @classmethod
    def phone_ok(cls, value: str) -> str:
        return _valid_phone(value)

    @field_validator("password")
    @classmethod
    def password_ok(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, max_length=254)
    # 暂时兼容旧客户端提交的 {email, password}。
    email: str | None = Field(default=None, max_length=254)
    password: str

    @model_validator(mode="after")
    def account_ok(self):
        account = (self.identifier or self.email or "").strip()
        if not account:
            raise ValueError("请输入邮箱或手机号")
        self.identifier = _valid_email(account) if "@" in account else _valid_phone(account)
        return self


class PhoneCodeRequest(BaseModel):
    phone: str
    code: str = Field(pattern=r"^\d{6}$")

    @field_validator("phone")
    @classmethod
    def phone_ok(cls, value: str) -> str:
        return _valid_phone(value)


class ResetPasswordRequest(PhoneCodeRequest):
    new_password: str = Field(min_length=10, max_length=72)

    @field_validator("new_password")
    @classmethod
    def password_ok(cls, value: str) -> str:
        return validate_password_strength(value)


class UpdateMeRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=10, max_length=72)

    @field_validator("new_password")
    @classmethod
    def password_ok(cls, value: str) -> str:
        return validate_password_strength(value)


def _user_dict(row) -> dict:
    created = row["created_at"]
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    phone = row.get("phone") if hasattr(row, "get") else row["phone"]
    last_login = row.get("last_login_at") if hasattr(row, "get") else None
    if hasattr(last_login, "isoformat"):
        last_login = last_login.isoformat()
    return {
        "id": row["id"],
        "email": row["email"],
        "phone": phone,
        "nickname": row["nickname"] or row["email"].split("@")[0],
        "status": (row.get("status") if hasattr(row, "get") else None) or "active",
        "created_at": created,
        "last_login_at": last_login,
    }


def _access_response(row) -> dict:
    version = int((row.get("token_version") if hasattr(row, "get") else None) or 0)
    token = create_access_token({"sub": str(row["id"]), "kind": "user", "ver": version})
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(row)}


def _user_refresh_ttl() -> int:
    return config.USER_REFRESH_TOKEN_DAYS * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.USER_REFRESH_COOKIE_NAME,
        value=token,
        max_age=_user_refresh_ttl(),
        path="/api/auth",
        secure=config.ENVIRONMENT == "production",
        httponly=True,
        samesite="strict",
    )


def _delete_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.USER_REFRESH_COOKIE_NAME,
        path="/api/auth",
        secure=config.ENVIRONMENT == "production",
        httponly=True,
        samesite="strict",
    )


def _token_response(row, response: Response) -> dict:
    version = int((row.get("token_version") if hasattr(row, "get") else None) or 0)
    try:
        refresh_token = refresh_sessions.create(
            int(row["id"]),
            "user",
            version,
            _user_refresh_ttl(),
        )
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _set_refresh_cookie(response, refresh_token)
    return _access_response(row)


def _ensure_login_allowed(row) -> None:
    if (row.get("status") if hasattr(row, "get") else "active") == "disabled":
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")


def _record_login(user_id: int):
    return record_login(user_id)


def _consume_code(purpose: CodePurpose, phone: str, code: str) -> None:
    try:
        valid = verification_codes.verify_and_consume(purpose, phone, code)
    except VerificationCodeRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except VerificationCodeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")


def _check_rate(bucket: str, subject: str, limit: int, window_seconds: int) -> None:
    try:
        rate_limiter.check(bucket, subject, limit, window_seconds)
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except RateLimitUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _reset_rate(bucket: str, subject: str) -> None:
    try:
        rate_limiter.reset(bucket, subject)
    except RateLimitUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _check_code_verification_ip(client_ip: str) -> None:
    _check_rate(
        "code-verify:ip-hour",
        client_ip,
        config.CODE_VERIFY_IP_HOURLY_LIMIT,
        3600,
    )


@router.post("/send-code")
async def send_code(body: SendCodeRequest, client_ip: str = Depends(get_client_ip)):
    _check_rate("send-code:phone-hour", body.phone, config.CODE_PHONE_HOURLY_LIMIT, 3600)
    _check_rate("send-code:phone-day", body.phone, config.CODE_PHONE_DAILY_LIMIT, 86400)
    _check_rate("send-code:ip-hour", client_ip, config.CODE_IP_HOURLY_LIMIT, 3600)

    user_id = get_id_by_phone(body.phone)
    # 对已注册/未注册状态返回相同外部响应，避免通过发码接口枚举账号。
    should_issue = (body.purpose == "register" and not user_id) or (
        body.purpose != "register" and user_id
    )
    code = None
    expires_in = config.VERIFICATION_CODE_TTL_SECONDS

    if should_issue:
        try:
            code, expires_in = verification_codes.issue(body.purpose, body.phone)
        except VerificationCodeRateLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except VerificationCodeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    response = {
        "ok": True,
        "expires_in": expires_in,
        "retry_after": config.VERIFICATION_CODE_COOLDOWN_SECONDS,
    }
    if config.EXPOSE_TEST_VERIFICATION_CODE and code is not None:
        response["test_code"] = code
    return response


@router.post("/register")
async def register(
    body: RegisterRequest,
    response: Response,
    client_ip: str = Depends(get_client_ip),
    _origin: None = Depends(validate_cookie_origin),
):
    _check_code_verification_ip(client_ip)
    nickname = (body.nickname or body.email.split("@")[0]).strip()
    exists = find_email_or_phone(body.email, body.phone)
    if exists:
        if exists["email"] == body.email:
            raise HTTPException(status_code=400, detail="该邮箱已注册")
        raise HTTPException(status_code=400, detail="该手机号已注册")

    _consume_code("register", body.phone, body.code)

    try:
        row = create_user(
            email=body.email,
            phone=body.phone,
            password_hash=hash_password(body.password),
            nickname=nickname,
        )
    except UniqueViolation as exc:
        raise HTTPException(status_code=400, detail="邮箱或手机号已注册") from exc
    return _token_response(_record_login(int(row["id"])) or row, response)


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    client_ip: str = Depends(get_client_ip),
    _origin: None = Depends(validate_cookie_origin),
):
    identifier = body.identifier or ""
    _check_rate("login:account", identifier, config.USER_LOGIN_LIMIT, config.USER_LOGIN_WINDOW_SECONDS)
    _check_rate("login:ip", client_ip, config.USER_LOGIN_LIMIT, config.USER_LOGIN_WINDOW_SECONDS)
    field = "email" if "@" in identifier else "phone"
    row = get_by_login_field(field, identifier)
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="邮箱/手机号或密码错误")
    _ensure_login_allowed(row)
    _reset_rate("login:account", identifier)
    return _token_response(_record_login(int(row["id"])) or row, response)


@router.post("/phone-login")
async def phone_login(
    body: PhoneCodeRequest,
    response: Response,
    client_ip: str = Depends(get_client_ip),
    _origin: None = Depends(validate_cookie_origin),
):
    _check_code_verification_ip(client_ip)
    row = get_by_phone(body.phone)
    if not row:
        raise HTTPException(status_code=400, detail="手机号或验证码错误")
    _ensure_login_allowed(row)
    _consume_code("login", body.phone, body.code)
    return _token_response(_record_login(int(row["id"])) or row, response)


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, client_ip: str = Depends(get_client_ip)):
    _check_code_verification_ip(client_ip)
    user_id = get_id_by_phone(body.phone)
    if not user_id:
        raise HTTPException(status_code=400, detail="手机号或验证码错误")

    _consume_code("reset_password", body.phone, body.code)
    update_password(user_id, hash_password(body.new_password))
    try:
        refresh_sessions.revoke_all("user", int(user_id))
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/refresh")
async def refresh_login(
    request: Request,
    response: Response,
    _origin: None = Depends(validate_cookie_origin),
):
    token = request.cookies.get(config.USER_REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="刷新凭证缺失")
    try:
        session = refresh_sessions.inspect(token)
        if session.kind != "user":
            raise InvalidRefreshToken("刷新凭证类型错误")
        row = get_by_id(session.subject_id)
        if (
            not row
            or row["status"] != "active"
            or int(row["token_version"]) != session.token_version
        ):
            refresh_sessions.revoke_all("user", session.subject_id)
            raise InvalidRefreshToken("登录状态已失效")
        new_token = refresh_sessions.rotate(token, session, _user_refresh_ttl())
    except InvalidRefreshToken as exc:
        _delete_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _set_refresh_cookie(response, new_token)
    return _access_response(row)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    _origin: None = Depends(validate_cookie_origin),
):
    token = request.cookies.get(config.USER_REFRESH_COOKIE_NAME)
    if token:
        try:
            refresh_sessions.revoke(token)
        except RefreshSessionUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    _delete_refresh_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    response: Response,
    user_id: int = Depends(get_current_user_id),
    _origin: None = Depends(validate_cookie_origin),
):
    bump_token_version(user_id)
    try:
        refresh_sessions.revoke_all("user", user_id)
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _delete_refresh_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user_id: int = Depends(get_current_user_id)):
    row = get_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_dict(row)


@router.patch("/me")
async def update_me(body: UpdateMeRequest, user_id: int = Depends(get_current_user_id)):
    row = update_nickname(user_id, body.nickname.strip())
    return _user_dict(row)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user_id: int = Depends(get_current_user_id),
    _origin: None = Depends(validate_cookie_origin),
):
    row = get_by_id(user_id)
    if not row or not verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    update_password(user_id, hash_password(body.new_password))
    try:
        refresh_sessions.revoke_all("user", user_id)
    except RefreshSessionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _delete_refresh_cookie(response)
    return {"ok": True}
