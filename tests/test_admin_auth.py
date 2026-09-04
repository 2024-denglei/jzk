import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from jzk.api import admin_auth


def test_admin_token_version_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "jzk.db.admin_admins_repo.get_active_admin",
        lambda _admin_id: {
            "id": 8,
            "is_active": True,
            "token_version": 2,
            "role": "super_admin",
        },
    )
    token = admin_auth.create_admin_token(8, "super_admin", token_version=1)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        admin_auth.get_current_admin(credentials)
    assert exc.value.status_code == 401
    assert "失效" in exc.value.detail


def test_current_admin_token_version_is_accepted(monkeypatch):
    row = {"id": 8, "is_active": True, "token_version": 2, "role": "super_admin"}
    monkeypatch.setattr(
        "jzk.db.admin_admins_repo.get_active_admin",
        lambda _admin_id: row,
    )
    token = admin_auth.create_admin_token(8, "super_admin", token_version=2)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    assert admin_auth.get_current_admin(credentials)["id"] == 8
