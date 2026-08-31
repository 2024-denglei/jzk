"""邮箱/手机号注册、登录与密码找回 API。"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from psycopg.errors import UniqueViolation

import config
from api.auth_utils import create_access_token, get_current_user_id, hash_password, verify_password
from api.verification_codes import VerificationCodeError, VerificationCodeRateLimitError, verification_codes
from db.database import db_session

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
    password: str = Field(min_length=6, max_length=72)
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
    new_password: str = Field(min_length=6, max_length=72)


class UpdateMeRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=72)


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


def _token_response(row) -> dict:
    version = int((row.get("token_version") if hasattr(row, "get") else None) or 0)
    token = create_access_token({"sub": str(row["id"]), "ver": version})
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(row)}


def _ensure_login_allowed(row) -> None:
    if (row.get("status") if hasattr(row, "get") else "active") == "disabled":
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")


def _record_login(user_id: int):
    with db_session() as conn:
        return conn.execute(
            "UPDATE app.users SET last_login_at = now(), updated_at = now() WHERE id = %s RETURNING *",
            (user_id,),
        ).fetchone()


def _consume_code(purpose: CodePurpose, phone: str, code: str) -> None:
    try:
        valid = verification_codes.verify_and_consume(purpose, phone, code)
    except VerificationCodeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")


@router.post("/send-code")
async def send_code(body: SendCodeRequest):
    with db_session() as conn:
        row = conn.execute("SELECT id FROM app.users WHERE phone = %s", (body.phone,)).fetchone()

    if body.purpose == "register" and row:
        raise HTTPException(status_code=400, detail="该手机号已注册")
    if body.purpose != "register" and not row:
        raise HTTPException(status_code=400, detail="该手机号尚未注册")

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
    if config.EXPOSE_TEST_VERIFICATION_CODE:
        response["test_code"] = code
    return response


@router.post("/register")
async def register(body: RegisterRequest):
    nickname = (body.nickname or body.email.split("@")[0]).strip()
    with db_session() as conn:
        exists = conn.execute(
            "SELECT email, phone FROM app.users WHERE email = %s OR phone = %s",
            (body.email, body.phone),
        ).fetchone()
        if exists:
            if exists["email"] == body.email:
                raise HTTPException(status_code=400, detail="该邮箱已注册")
            raise HTTPException(status_code=400, detail="该手机号已注册")

    _consume_code("register", body.phone, body.code)

    try:
        with db_session() as conn:
            row = conn.execute(
                """
                INSERT INTO app.users (email, phone, password_hash, nickname)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (body.email, body.phone, hash_password(body.password), nickname),
            ).fetchone()
    except UniqueViolation as exc:
        raise HTTPException(status_code=400, detail="邮箱或手机号已注册") from exc
    return _token_response(_record_login(int(row["id"])) or row)


@router.post("/login")
async def login(body: LoginRequest):
    identifier = body.identifier or ""
    field = "email" if "@" in identifier else "phone"
    with db_session() as conn:
        row = conn.execute(f"SELECT * FROM app.users WHERE {field} = %s", (identifier,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="邮箱/手机号或密码错误")
    _ensure_login_allowed(row)
    return _token_response(_record_login(int(row["id"])) or row)


@router.post("/phone-login")
async def phone_login(body: PhoneCodeRequest):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM app.users WHERE phone = %s", (body.phone,)).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="该手机号尚未注册")
    _ensure_login_allowed(row)
    _consume_code("login", body.phone, body.code)
    return _token_response(_record_login(int(row["id"])) or row)


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    with db_session() as conn:
        row = conn.execute("SELECT id FROM app.users WHERE phone = %s", (body.phone,)).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="该手机号尚未注册")

    _consume_code("reset_password", body.phone, body.code)
    with db_session() as conn:
        conn.execute(
            "UPDATE app.users SET password_hash = %s, token_version = token_version + 1, updated_at = now() WHERE id = %s",
            (hash_password(body.new_password), row["id"]),
        )
    return {"ok": True}


@router.get("/me")
async def me(user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM app.users WHERE id = %s", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_dict(row)


@router.patch("/me")
async def update_me(body: UpdateMeRequest, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            "UPDATE app.users SET nickname = %s, updated_at = now() WHERE id = %s RETURNING *",
            (body.nickname.strip(), user_id),
        ).fetchone()
    return _user_dict(row)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM app.users WHERE id = %s", (user_id,)).fetchone()
        if not row or not verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        conn.execute(
            "UPDATE app.users SET password_hash = %s, token_version = token_version + 1, updated_at = now() WHERE id = %s",
            (hash_password(body.new_password), user_id),
        )
    return {"ok": True}
