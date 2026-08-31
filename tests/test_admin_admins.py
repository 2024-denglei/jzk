import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import admin_admins as admin_admins_mod
from db import admin_admins_repo


ADMIN = {"id": 9, "username": "admin", "display_name": "张管理员"}


def test_super_admin_can_create_admin_account(monkeypatch):
    captured = {}
    monkeypatch.setattr(admin_admins_mod, "hash_password", lambda password: f"hashed:{password}")
    monkeypatch.setattr(admin_admins_mod, "create_admin_account", lambda **kwargs: captured.update(kwargs) or {"id": 10, "username": kwargs["username"], "is_active": True})
    body = admin_admins_mod.AdminCreateBody(username="operator", password="Password1", display_name="运营管理员", role="donor_admin")

    data = asyncio.run(admin_admins_mod.admin_create_admin(body, ADMIN))

    assert data["id"] == 10
    assert captured["password_hash"] == "hashed:Password1"
    assert captured["operator_id"] == 9


def test_delete_admin_rejects_self_or_last_super(monkeypatch):
    monkeypatch.setattr(admin_admins_mod, "set_admin_account_active", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("不能删除")))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_admins_mod.admin_delete_admin(9, admin_admins_mod.AdminStateBody(reason="账号清理"), ADMIN))
    assert exc.value.status_code == 409


def test_repository_never_disables_current_admin():
    with pytest.raises(PermissionError, match="当前登录"):
        admin_admins_repo.set_admin_account_active(9, is_active=False, operator_id=9, reason="账号清理")


def test_repository_keeps_at_least_one_active_super_admin(monkeypatch):
    class Connection:
        def execute(self, *_args, **_kwargs): return None

    class Session:
        def __enter__(self): return Connection()
        def __exit__(self, *_args): return False

    monkeypatch.setattr(admin_admins_repo, "db_session", lambda admin=False: Session())
    monkeypatch.setattr(admin_admins_repo, "fetchone", lambda *_args, **_kwargs: {"id": 1, "username": "root", "display_name": "Root", "role": "super_admin", "is_active": True})
    monkeypatch.setattr(admin_admins_repo, "fetchall", lambda *_args, **_kwargs: [{"id": 1}])

    with pytest.raises(PermissionError, match="至少保留一个"):
        admin_admins_repo.set_admin_account_active(1, is_active=False, operator_id=2, reason="账号清理")


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
