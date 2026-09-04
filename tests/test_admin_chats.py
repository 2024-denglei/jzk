from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from jzk.api import admin_chats
from jzk.db import admin_chats_repo


ADMIN = {"id": 9, "role": "super_admin"}


class FakeService:
    def __init__(self, *, admin=False):
        assert admin is True

    def list_chats(self, user_id, **kwargs):
        return {"items": [{"id": 11, "message_count": 4}], "user_id": user_id, **kwargs}

    def get_conversation(self, user_id, chat_id):
        return {"chat": {"id": chat_id, "user_id": user_id}, "branches": []}

    def get_message_path(self, user_id, chat_id, branch_id, **kwargs):
        return {"chat_id": chat_id, "branch_id": branch_id, "items": [], **kwargs}

    def get_message_match_results(self, user_id, message_id, **kwargs):
        return {"owner": user_id, "message_id": message_id, **kwargs}

    def get_message_context(self, user_id, chat_id, branch_id, message_id):
        return {"chat_id": chat_id, "branch_id": branch_id, "items": [{"id": message_id}]}

    def get_generation(self, user_id, generation_id):
        return SimpleNamespace(id=generation_id, user_id=user_id, chat_id=11)

    def get_generation_steps(self, user_id, generation_id, **kwargs):
        return [{"step_order": 0, "generation_id": generation_id, "user_id": user_id, **kwargs}]


@pytest.fixture
def admin_v2(monkeypatch):
    monkeypatch.setattr(admin_chats, "ConversationQueryService", FakeService)
    monkeypatch.setattr(admin_chats.admin_chats_repo, "user_exists", lambda _user_id: True)
    monkeypatch.setattr(
        admin_chats.admin_chats_repo,
        "message_belongs_to_chat",
        lambda *_args: True,
    )
    audits = []
    monkeypatch.setattr(
        admin_chats.admin_chats_repo,
        "write_sensitive_read_audit",
        lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    return audits


def test_every_admin_conversation_resource_read_is_audited(admin_v2):
    branch_id = uuid4()
    message_id = uuid4()
    generation_id = uuid4()

    admin_chats.list_admin_conversations(7, cursor=None, limit=20, admin=ADMIN)
    admin_chats.get_admin_conversation(7, 11, admin=ADMIN)
    admin_chats.get_admin_message_path(7, 11, branch_id, before=None, limit=40, admin=ADMIN)
    admin_chats.get_admin_message_match(7, 11, message_id, page=1, limit=20, admin=ADMIN)
    context = admin_chats.get_admin_message_context(7, 11, branch_id, message_id, admin=ADMIN)
    trace = admin_chats.get_admin_generation_trace(
        7, 11, generation_id, after_order=-1, limit=100, admin=ADMIN
    )

    assert [call[0][2] for call in admin_v2] == [
        "view_chat_list",
        "view_chat_tree",
        "view_chat_path",
        "view_chat_match",
        "view_chat_message_context",
        "view_chat_trace",
    ]
    assert context["items"][0]["id"] == message_id
    assert trace["steps"][0]["step_order"] == 0


def test_admin_nested_message_and_generation_ids_cannot_cross_chat(admin_v2, monkeypatch):
    monkeypatch.setattr(
        admin_chats.admin_chats_repo,
        "message_belongs_to_chat",
        lambda *_args: False,
    )
    with pytest.raises(HTTPException) as message_error:
        admin_chats.get_admin_message_match(7, 11, uuid4(), page=1, limit=20, admin=ADMIN)
    assert message_error.value.status_code == 404

    class WrongChatService(FakeService):
        def get_generation(self, user_id, generation_id):
            return SimpleNamespace(id=generation_id, user_id=user_id, chat_id=99)

    monkeypatch.setattr(admin_chats, "ConversationQueryService", WrongChatService)
    with pytest.raises(HTTPException) as generation_error:
        admin_chats.get_admin_generation_trace(
            7, 11, uuid4(), after_order=-1, limit=100, admin=ADMIN
        )
    assert generation_error.value.status_code == 404
    assert admin_v2 == []


def test_sensitive_read_audit_contains_only_resource_metadata(monkeypatch):
    executed = []

    class Conn:
        def execute(self, sql, params=()):
            executed.append((" ".join(sql.split()), params))

    @contextmanager
    def fake_session(admin=False):
        assert admin is True
        yield Conn()

    monkeypatch.setattr(admin_chats_repo, "db_session", fake_session)
    admin_chats_repo.write_sensitive_read_audit(
        7,
        9,
        "view_chat_path",
        resource_type="message_path",
        resource_id="branch-1",
        chat_id=11,
        metadata={"limit": 40},
    )
    _, params = executed[0]
    assert params[:3] == (7, "view_chat_path", 9)
    assert "message content" not in str(params)
    assert "branch-1" in str(params)
