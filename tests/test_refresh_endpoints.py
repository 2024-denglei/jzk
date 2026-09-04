import asyncio
from contextlib import contextmanager

import pytest
from fastapi import HTTPException, Request, Response

from jzk.api import admin as admin_api
from jzk.api import auth as auth_api
from jzk.api.refresh_sessions import RefreshSession


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

ADMIN = {
    "id": 7,
    "username": "operator",
    "display_name": "运营员",
    "role": "super_admin",
    "is_active": True,
    "token_version": 4,
}


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
    monkeypatch.setattr(auth_api, "get_by_id", lambda _user_id: USER)
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
    monkeypatch.setattr(auth_api, "get_by_id", lambda _user_id: USER)
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


def test_admin_refresh_reads_admin_account_and_rotates_cookie(monkeypatch):
    store = _RefreshStore()
    store.session = RefreshSession(7, "admin", 4, "admin-family")

    @contextmanager
    def admin_db_session(*, admin=False):
        assert admin is True

        class AdminConnection:
            def execute(self, _sql, _params=()):
                return type("Cursor", (), {"fetchone": lambda self: ADMIN})()

        yield AdminConnection()

    monkeypatch.setattr(admin_api, "refresh_sessions", store)
    monkeypatch.setattr(admin_api, "db_session", admin_db_session)
    response = Response()

    data = asyncio.run(
        admin_api.admin_refresh(
            _request_with_cookie(admin_api.config.ADMIN_REFRESH_COOKIE_NAME, "old-refresh"),
            response,
        )
    )

    assert store.rotated is True
    assert data["admin"]["id"] == ADMIN["id"]
    assert "new-refresh" in response.headers["set-cookie"].lower()
