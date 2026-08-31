import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import admin_users as admin_users_mod


ADMIN = {"id": 9, "username": "admin", "display_name": "管理员"}


def test_admin_user_list_masks_contact_and_returns_counts(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        admin_users_mod,
        "list_users",
        lambda **_kwargs: ([{
            "id": 1,
            "email": "member@example.com",
            "phone": "+8613800138000",
            "nickname": "测试用户",
            "status": "active",
            "created_at": now,
            "last_login_at": now,
            "favorite_count": 2,
            "history_count": 3,
            "chat_count": 4,
        }], 1),
    )
    data = asyncio.run(admin_users_mod.admin_list_users(q="member", admin=ADMIN))
    assert data["total"] == 1
    assert data["items"][0]["email"] == "me***@example.com"
    assert data["items"][0]["phone"] == "+86****8000"
    assert data["items"][0]["chat_count"] == 4


def test_admin_can_kick_user_with_reason(monkeypatch):
    called = {}

    def fake_control(user_id, action, operator_id, reason):
        called.update(user_id=user_id, action=action, operator_id=operator_id, reason=reason)
        return {"id": user_id, "status": "active", "token_version": 3}

    monkeypatch.setattr(admin_users_mod, "control_user", fake_control)
    body = admin_users_mod.UserControlBody(reason="异常登录处理")
    data = asyncio.run(admin_users_mod.admin_kick_user(12, body, ADMIN))
    assert called == {"user_id": 12, "action": "kick", "operator_id": 9, "reason": "异常登录处理"}
    assert data["token_version"] == 3


def test_admin_chat_lookup_is_scoped_to_user_and_operator(monkeypatch):
    called = {}

    def fake_chat(user_id, chat_id, operator_id):
        called.update(user_id=user_id, chat_id=chat_id, operator_id=operator_id)
        return {"id": chat_id, "messages": [{"role": "user", "content": "你好"}]}

    monkeypatch.setattr(admin_users_mod, "get_user_chat", fake_chat)
    data = asyncio.run(admin_users_mod.admin_user_chat(7, 88, ADMIN))
    assert called == {"user_id": 7, "chat_id": 88, "operator_id": 9}
    assert data["messages"][0]["content"] == "你好"


def test_admin_chat_returns_404_when_not_owned_by_user(monkeypatch):
    monkeypatch.setattr(admin_users_mod, "get_user_chat", lambda *_args: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_users_mod.admin_user_chat(7, 99, ADMIN))
    assert exc.value.status_code == 404
