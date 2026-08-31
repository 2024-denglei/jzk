"""JWT 与密码工具。"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

import config

SECRET_KEY = config.JWT_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict[str, Any], expires_days: int = ACCESS_TOKEN_EXPIRE_DAYS) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=expires_days)
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("kind") == "admin":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
        user_id = payload.get("sub")
        token_version = payload.get("ver")
        if user_id is None or token_version is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
        user_id = int(user_id)
        token_version = int(token_version)
    except HTTPException:
        raise
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")

    from db.database import db_session

    with db_session() as conn:
        row = conn.execute(
            "SELECT status, token_version FROM app.users WHERE id = %s",
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if row["status"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已停用")
    if int(row["token_version"]) != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
    return user_id


def get_optional_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int | None:
    if credentials is None:
        return None
    try:
        return get_current_user_id(credentials)
    except (HTTPException, JWTError, ValueError, TypeError):
        return None
