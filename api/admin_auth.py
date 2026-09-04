"""管理端鉴权。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from api.auth_utils import create_access_token, decode_token
from db import admin_admins_repo
from passwords import verify_password

security = HTTPBearer(auto_error=False)


def create_admin_token(admin_id: int, role: str, token_version: int = 0) -> str:
    return create_access_token(
        {
            "sub": str(admin_id),
            "kind": "admin",
            "role": role,
            "ver": token_version,
        }
    )


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
        token_version = payload.get("ver")
        if token_version is not None:
            token_version = int(token_version)
    except (JWTError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")

    row = admin_admins_repo.get_active_admin(admin_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员不存在或已停用")
    if token_version is not None and int(row["token_version"]) != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="管理端登录已失效")
    return dict(row)


def require_super_admin(admin: dict = Depends(get_current_admin)) -> dict:
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin


def authenticate_admin(username: str, password: str) -> dict | None:
    row = admin_admins_repo.get_active_admin_by_username(username)
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return dict(row)


def set_admin_password(admin_id: int, old_password: str, new_password: str) -> bool:
    return admin_admins_repo.change_admin_password(admin_id, old_password, new_password)
