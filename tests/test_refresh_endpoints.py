import asyncio
from contextlib import contextmanager

import pytest
from fastapi import HTTPException, Request, Response

from api import auth as auth_api
from api.refresh_sessions import RefreshSession


USER = {
    "id": 42,
    "email": "member@example.com",
    "phone": "+8613800138000",
    "nickname": "会员",
    "status": "active",
    "token_version": 3,
    "created_at": "2026-08-31T00:00:00Z",
    "last_login_at": None,
}


class _Cursor:
    def fetchone(self):
        return USER


class _Connection:
    def execute(self, _sql, _params=()):
        return _Cursor()


@contextmanager
def _db_session():
    yield _Connection()


class _RefreshStore:
    def __init__(self):
        self.session = RefreshSession(42, "user", 3, "family")
        self.rotated = False
        self.revoked = []

    def inspect(self, token):
        assert token == "old-refresh"
        return self.session

    def rotate(self, token, session, ttl):
        assert token == "old-refresh"
        assert session == self.session
        assert ttl > 0
        self.rotated = True
        return "new-refresh"

    def revoke_all(self, kind, subject_id):
        self.revoked.append((kind, subject_id))
        return 1


def _request_with_cookie(name: str, value: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/refresh",
            "headers": [(b"cookie", f"{name}={value}".encode())],
        }
    )


def test_refresh_rotates_cookie_and_returns_short_access_token(monkeypatch):
    store = _RefreshStore()
    monkeypatch.setattr(auth_api, "refresh_sessions", store)
    monkeypatch.setattr(auth_api, "db_session", _db_session)
    monkeypatch.setattr(auth_api.config, "ENVIRONMENT", "production")
    response = Response()

    data = asyncio.run(
        auth_api.refresh_login(
            _request_with_cookie(auth_api.config.USER_REFRESH_COOKIE_NAME, "old-refresh"),
            response,
        )
    )

    assert store.rotated is True
    assert data["access_token"]
    cookie = response.headers["set-cookie"].lower()
    assert "new-refresh" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie


def test_refresh_rejects_token_version_mismatch(monkeypatch):
    store = _RefreshStore()
    store.session = RefreshSession(42, "user", 2, "family")
    monkeypatch.setattr(auth_api, "refresh_sessions", store)
    monkeypatch.setattr(auth_api, "db_session", _db_session)
    response = Response()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth_api.refresh_login(
                _request_with_cookie(auth_api.config.USER_REFRESH_COOKIE_NAME, "old-refresh"),
                response,
            )
        )
    assert exc.value.status_code == 401
    assert ("user", 42) in store.revoked
