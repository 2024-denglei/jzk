"""JWT 与密码工具。"""

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from jzk import config
from jzk.db.users_repo import get_auth_state
from jzk.passwords import hash_password, verify_password

SECRET_KEY = config.JWT_SECRET
ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)


def create_access_token(
    data: dict[str, Any],
    expires_days: int | None = None,
    expires_minutes: int | None = None,
) -> str:
    payload = data.copy()
    now = datetime.now(timezone.utc)
    if expires_days is not None:
        expire = now + timedelta(days=expires_days)
    else:
        expire = now + timedelta(
            minutes=expires_minutes or config.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    payload.setdefault("kind", "user")
    payload.update(
        {
            "iss": config.JWT_ISSUER,
            "aud": config.JWT_AUDIENCE,
            "iat": now,
            "exp": expire,
            "jti": str(uuid.uuid4()),
        }
    )
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    unverified = jwt.get_unverified_claims(token)
    if "iss" not in unverified and "aud" not in unverified:
        # 短期兼容迁移前签发的、没有 iss/aud 的旧 Bearer Token。
        return jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_aud": False},
        )
    return jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        issuer=config.JWT_ISSUER,
        audience=config.JWT_AUDIENCE,
    )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("kind") not in (None, "user"):
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

    row = get_auth_state(user_id)
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
