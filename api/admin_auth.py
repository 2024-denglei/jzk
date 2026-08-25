"""管理端鉴权。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from api.auth_utils import create_access_token, decode_token, hash_password, verify_password
from db.database import db_session

security = HTTPBearer(auto_error=False)


def create_admin_token(admin_id: int, role: str) -> str:
    return create_access_token({"sub": str(admin_id), "kind": "admin", "role": role})


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录管理端")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("kind") != "admin":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要管理员令牌")
        admin_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")

    with db_session(admin=True) as conn:
        row = conn.execute(
            "SELECT * FROM admin.admin_users WHERE id = %s AND is_active = TRUE",
            (admin_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员不存在或已停用")
    return dict(row)


def require_super_admin(admin: dict = Depends(get_current_admin)) -> dict:
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin


def authenticate_admin(username: str, password: str) -> dict | None:
    with db_session(admin=True) as conn:
        row = conn.execute(
            "SELECT * FROM admin.admin_users WHERE username = %s AND is_active = TRUE",
            (username.strip(),),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


def set_admin_password(admin_id: int, new_password: str) -> None:
    with db_session(admin=True) as conn:
        conn.execute(
            "UPDATE admin.admin_users SET password_hash = %s, updated_at = now() WHERE id = %s",
            (hash_password(new_password), admin_id),
        )
