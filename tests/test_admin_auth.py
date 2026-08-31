from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api import admin_auth


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row

    def execute(self, _sql, _params=()):
        return _Cursor(self.row)


def _session(row):
    @contextmanager
    def context(*_args, **_kwargs):
        yield _Connection(row)

    return context


def test_admin_token_version_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "db_session",
        _session({"id": 8, "is_active": True, "token_version": 2, "role": "super_admin"}),
    )
    token = admin_auth.create_admin_token(8, "super_admin", token_version=1)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        admin_auth.get_current_admin(credentials)
    assert exc.value.status_code == 401
    assert "失效" in exc.value.detail


def test_current_admin_token_version_is_accepted(monkeypatch):
    row = {"id": 8, "is_active": True, "token_version": 2, "role": "super_admin"}
    monkeypatch.setattr(admin_auth, "db_session", _session(row))
    token = admin_auth.create_admin_token(8, "super_admin", token_version=2)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    assert admin_auth.get_current_admin(credentials)["id"] == 8
