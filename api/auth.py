"""邮箱注册 / 登录 / 资料 API。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.auth_utils import (
    create_access_token,
    get_current_user_id,
    hash_password,
    verify_password,
)
from db.database import db_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _valid_email(v: str) -> str:
    v = v.strip().lower()
    if "@" not in v or "." not in v.split("@")[-1]:
        raise ValueError("邮箱格式不正确")
    return v


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=72)
    nickname: str = Field(default="", max_length=40)

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        return _valid_email(v)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        return _valid_email(v)


class UpdateMeRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=72)


def _user_dict(row) -> dict:
    created = row["created_at"]
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return {
        "id": row["id"],
        "email": row["email"],
        "nickname": row["nickname"] or row["email"].split("@")[0],
        "created_at": created,
    }


@router.post("/register")
async def register(body: RegisterRequest):
    email = body.email.lower().strip()
    nickname = (body.nickname or email.split("@")[0]).strip()
    with db_session() as conn:
        exists = conn.execute(
            "SELECT id FROM app.users WHERE email = %s", (email,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="该邮箱已注册")
        row = conn.execute(
            """
            INSERT INTO app.users (email, password_hash, nickname)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (email, hash_password(body.password), nickname),
        ).fetchone()
    token = create_access_token({"sub": str(row["id"])})
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(row)}


@router.post("/login")
async def login(body: LoginRequest):
    email = body.email.lower().strip()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM app.users WHERE email = %s", (email,)
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="邮箱或密码错误")
    token = create_access_token({"sub": str(row["id"])})
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(row)}


@router.get("/me")
async def me(user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM app.users WHERE id = %s", (user_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_dict(row)


@router.patch("/me")
async def update_me(body: UpdateMeRequest, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            """
            UPDATE app.users SET nickname = %s WHERE id = %s
            RETURNING *
            """,
            (body.nickname.strip(), user_id),
        ).fetchone()
    return _user_dict(row)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM app.users WHERE id = %s", (user_id,)
        ).fetchone()
        if not row or not verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        conn.execute(
            "UPDATE app.users SET password_hash = %s WHERE id = %s",
            (hash_password(body.new_password), user_id),
        )
    return {"ok": True}
