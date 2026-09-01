import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import admin_users as admin_users_mod
from db import admin_users_repo


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
    monkeypatch.setattr(admin_users_mod.refresh_sessions, "revoke_all", lambda *_args: 1)
    body = admin_users_mod.UserControlBody(reason="异常登录处理")
    data = asyncio.run(admin_users_mod.admin_kick_user(12, body, ADMIN))
    assert called == {"user_id": 12, "action": "kick", "operator_id": 9, "reason": "异常登录处理"}
    assert data["token_version"] == 3


@pytest.mark.parametrize(
    ("action", "before_status", "expected_status", "expected_token_version", "sql_fragment"),
    [
        ("kick", "active", "active", 3, "token_version = token_version + 1"),
        ("disable", "active", "disabled", 3, "SET status = 'disabled', token_version = token_version + 1"),
        ("enable", "disabled", "active", 2, "SET status = 'active'"),
    ],
)
def test_user_control_repository_applies_status_and_token_rules(monkeypatch, action, before_status, expected_status, expected_token_version, sql_fragment):
    before = {"id": 12, "status": before_status, "token_version": 2, "disabled_at": None, "disabled_reason": None}
    after = {"id": 12, "status": expected_status, "token_version": expected_token_version, "disabled_at": None, "disabled_reason": None}
    fetched = iter([before, after])
    executed = []

    class Conn:
        def execute(self, sql, params=()):
            executed.append((" ".join(sql.split()), params))

    @contextmanager
    def fake_session(admin=False):
        assert admin is True
        yield Conn()

    monkeypatch.setattr(admin_users_repo, "db_session", fake_session)
    monkeypatch.setattr(admin_users_repo, "fetchone", lambda _conn, _sql, _params: next(fetched))

    result = admin_users_repo.control_user(12, action, 9, "安全处理")

    assert result["status"] == expected_status
    assert result["token_version"] == expected_token_version
    assert any(sql_fragment in sql for sql, _params in executed)
    assert any("INSERT INTO admin.user_audit_logs" in sql for sql, _params in executed)


def test_admin_chat_lookup_is_scoped_to_user_and_operator(monkeypatch):
    called = {}

    def fake_chat(user_id, chat_id, operator_id):
        called.update(user_id=user_id, chat_id=chat_id, operator_id=operator_id)
        return {
            "id": chat_id,
            "messages": [{"role": "user", "content": "你好"}],
            "turns": [{"trace_id": "trace-1", "steps": [{"type": "tool_call", "name": "match"}]}],
        }

    monkeypatch.setattr(admin_users_mod, "get_user_chat", fake_chat)
    data = asyncio.run(admin_users_mod.admin_user_chat(7, 88, ADMIN))
    assert called == {"user_id": 7, "chat_id": 88, "operator_id": 9}
    assert data["messages"][0]["content"] == "你好"
    assert data["turns"][0]["steps"][0]["name"] == "match"


def test_admin_chat_returns_404_when_not_owned_by_user(monkeypatch):
    monkeypatch.setattr(admin_users_mod, "get_user_chat", lambda *_args: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_users_mod.admin_user_chat(7, 99, ADMIN))
    assert exc.value.status_code == 404


def test_legacy_admin_chat_no_longer_reads_local_trace_files(monkeypatch):
    class Conn:
        def execute(self, _sql, _params=()):
            return None

    @contextmanager
    def fake_session(admin=False):
        assert admin is True
        yield Conn()

    monkeypatch.setattr(admin_users_repo, "db_session", fake_session)
    monkeypatch.setattr(
        admin_users_repo,
        "fetchone",
        lambda _conn, _sql, _params: {
            "id": 88,
            "user_id": 7,
            "session_id": "session-unique-id",
            "messages_json": '[{"role":"user","content":"你好"}]',
            "candidates_json": "[]",
            "state_json": "{}",
        },
    )
    row = admin_users_repo.get_user_chat(7, 88, 9)

    assert row["turns"] == []
