import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import admin_admins as admin_admins_mod


ADMIN = {"id": 9, "username": "admin", "display_name": "张管理员"}


def test_admin_center_list_maps_status_and_serializes_profile(monkeypatch):
    called = {}
    now = datetime.now(timezone.utc)

    def fake_list(**kwargs):
        called.update(kwargs)
        return ([{
            "id": 9,
            "username": "admin",
            "display_name": "张管理员",
            "role": "super_admin",
            "is_active": True,
            "operation_count": 12,
            "created_at": now,
        }], 1, 1, 20)

    monkeypatch.setattr(admin_admins_mod, "list_admins", fake_list)

    data = asyncio.run(admin_admins_mod.admin_list_admins(q="张", status="active", admin=ADMIN))

    assert called["q"] == "张"
    assert called["is_active"] is True
    assert data["items"][0]["created_at"] == now.isoformat()
    assert data["items"][0]["operation_count"] == 12


def test_admin_center_detail_returns_404_for_unknown_admin(monkeypatch):
    monkeypatch.setattr(admin_admins_mod, "get_admin_profile", lambda _admin_id: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_admins_mod.admin_get_admin(404, ADMIN))
    assert exc.value.status_code == 404


def test_admin_audit_is_scoped_to_selected_operator(monkeypatch):
    called = {}
    monkeypatch.setattr(admin_admins_mod, "admin_exists", lambda admin_id: admin_id == 7)

    def fake_audit(admin_id, **kwargs):
        called.update(admin_id=admin_id, **kwargs)
        return ([{
            "source": "user",
            "record_id": 1,
            "action": "kick",
            "target_id": "42",
            "target_name": "测试用户",
            "created_at": "2026-08-31T12:00:00+00:00",
        }], 1, 2, 30)

    monkeypatch.setattr(admin_admins_mod, "list_admin_audit", fake_audit)

    data = asyncio.run(admin_admins_mod.admin_get_admin_audit(7, source="user", page=2, admin=ADMIN))

    assert called == {"admin_id": 7, "source": "user", "page": 2, "page_size": 30}
    assert data["items"][0]["action"] == "kick"


def test_admin_audit_rejects_unknown_operator(monkeypatch):
    monkeypatch.setattr(admin_admins_mod, "admin_exists", lambda _admin_id: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_admins_mod.admin_get_admin_audit(404, admin=ADMIN))
    assert exc.value.status_code == 404
