from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from db.chat_models import ChatErrorCode
from dialogue import conversation_queries
from dialogue.conversation_cursors import (
    InvalidConversationCursor,
    decode_chat_list_cursor,
    decode_message_cursor,
    encode_chat_list_cursor,
    encode_message_cursor,
)
from dialogue.conversation_queries import ConversationQueryError, ConversationQueryService


def _chat_row(chat_id: int, updated_at: datetime, branch_id):
    return {
        "id": chat_id,
        "title": f"会话 {chat_id}",
        "storage_version": 2,
        "active_branch_id": branch_id,
        "active_branch_name": "主分支",
        "branch_count": 1,
        "message_count": 2,
        "last_message_preview": "你好",
        "created_at": updated_at - timedelta(hours=1),
        "updated_at": updated_at,
    }


def test_conversation_cursors_reject_tampering_and_cross_resource_use(monkeypatch):
    monkeypatch.setattr(conversation_queries.config, "JWT_SECRET", "test-secret")
    now = datetime.now(timezone.utc)
    branch_id = uuid4()
    list_cursor = encode_chat_list_cursor(7, now, 12, now=100)
    assert decode_chat_list_cursor(list_cursor, 7, now=101) == (now, 12)
    with pytest.raises(InvalidConversationCursor):
        decode_chat_list_cursor(list_cursor, 8, now=101)
    with pytest.raises(InvalidConversationCursor):
        decode_chat_list_cursor(list_cursor + "x", 7, now=101)

    message_cursor = encode_message_cursor(7, 12, branch_id, uuid4(), now=100)
    with pytest.raises(InvalidConversationCursor):
        decode_message_cursor(message_cursor, 7, 12, uuid4(), now=101)


def test_chat_list_uses_stable_keyset_cursor_and_same_admin_service(monkeypatch):
    now = datetime.now(timezone.utc)
    branch_id = uuid4()
    rows = [_chat_row(i, now - timedelta(minutes=i), branch_id) for i in (3, 2, 1)]
    admin_flags = []

    @contextmanager
    def fake_session(admin=False):
        admin_flags.append(admin)
        yield object()

    monkeypatch.setattr(conversation_queries, "db_session", fake_session)
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "list_chats",
        lambda *_args, **_kwargs: rows,
    )

    user_page = ConversationQueryService().list_chats(9, limit=2)
    admin_page = ConversationQueryService(admin=True).list_chats(9, limit=2)

    assert [item.id for item in user_page.items] == [3, 2]
    assert user_page.has_more and user_page.next_cursor
    assert admin_page.model_dump() == user_page.model_dump()
    assert admin_flags == [False, True]
    assert decode_chat_list_cursor(user_page.next_cursor, 9) == (rows[1]["updated_at"], 2)


def test_message_path_returns_chronological_page_and_lazy_match_summary(monkeypatch):
    now = datetime.now(timezone.utc)
    branch_id = uuid4()
    message_ids = [uuid4() for _ in range(4)]
    rows = []
    for depth in reversed(range(4)):
        row = {
            "id": message_ids[depth],
            "parent_message_id": message_ids[depth - 1] if depth else None,
            "derived_from_message_id": None,
            "created_in_branch_id": branch_id,
            "role": "assistant" if depth % 2 else "user",
            "status": "completed",
            "content": f"message-{depth}",
            "content_format": "markdown",
            "depth": depth,
            "state_recoverable": True,
            "generation_id": uuid4() if depth == 3 else None,
            "created_at": now + timedelta(seconds=depth),
            "completed_at": now + timedelta(seconds=depth),
            "match_total": 25 if depth == 3 else None,
            "model_version": "v2" if depth == 3 else None,
            "dataset_version": "d1" if depth == 3 else None,
            "snapshot_schema_version": 1 if depth == 3 else None,
            "snapshot_source": "native" if depth == 3 else None,
            "match_created_at": now if depth == 3 else None,
        }
        rows.append(row)

    @contextmanager
    def fake_session(admin=False):
        yield object()

    monkeypatch.setattr(conversation_queries, "db_session", fake_session)
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_chat_path_source",
        lambda *_args: _chat_row(10, now, branch_id),
    )
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_branch_for_user",
        lambda *_args: {"id": branch_id, "head_message_id": message_ids[3]},
    )
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_message_path",
        lambda *_args, **_kwargs: rows,
    )

    page = ConversationQueryService().get_message_path(5, 10, branch_id, limit=3)

    assert [item.depth for item in page.items] == [1, 2, 3]
    assert page.items[-1].match_run and page.items[-1].match_run.total == 25
    assert page.items[-1].generation_id == rows[0]["generation_id"]
    assert page.has_more and page.next_before
    assert decode_message_cursor(page.next_before, 5, 10, branch_id) == message_ids[0]


def test_message_path_maps_cursor_errors_to_stable_domain_code(monkeypatch):
    branch_id = uuid4()
    now = datetime.now(timezone.utc)

    @contextmanager
    def fake_session(admin=False):
        yield object()

    monkeypatch.setattr(conversation_queries, "db_session", fake_session)
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_chat_path_source",
        lambda *_args: _chat_row(10, now, branch_id),
    )
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_branch_for_user",
        lambda *_args: {"id": branch_id, "head_message_id": uuid4()},
    )

    with pytest.raises(ConversationQueryError) as exc_info:
        ConversationQueryService().get_message_path(5, 10, branch_id, before="invalid")
    assert exc_info.value.code == ChatErrorCode.INVALID_MESSAGE_CURSOR


def test_message_match_results_are_scoped_by_message_and_shared_with_admin(monkeypatch):
    message_id = uuid4()
    match_run_id = uuid4()
    admin_flags = []

    @contextmanager
    def fake_session(admin=False):
        admin_flags.append(admin)
        yield object()

    monkeypatch.setattr(conversation_queries, "db_session", fake_session)
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_message_match_snapshot",
        lambda *_args: {"chat_id": 10, "match_run_id": match_run_id},
    )
    monkeypatch.setattr(
        conversation_queries,
        "get_frozen_match_page",
        lambda owner, result, **kwargs: {
            "owner": owner,
            "result_set_id": result,
            "page": kwargs["page"],
        },
    )

    user = ConversationQueryService().get_message_match_results(7, message_id, page=2)
    admin = ConversationQueryService(admin=True).get_message_match_results(7, message_id, page=2)
    assert user == admin == {"owner": 7, "result_set_id": str(match_run_id), "page": 2}
    assert admin_flags == [False, True]


def test_message_without_owned_snapshot_returns_stable_not_found(monkeypatch):
    @contextmanager
    def fake_session(admin=False):
        yield object()

    monkeypatch.setattr(conversation_queries, "db_session", fake_session)
    monkeypatch.setattr(
        conversation_queries.chat_queries_repo,
        "get_message_match_snapshot",
        lambda *_args: None,
    )
    with pytest.raises(ConversationQueryError) as exc_info:
        ConversationQueryService().get_message_match_results(7, uuid4())
    assert exc_info.value.code == ChatErrorCode.MATCH_SNAPSHOT_NOT_FOUND


def test_generation_and_database_trace_use_same_user_admin_query_service(monkeypatch):
    generation_id = uuid4()
    calls = []
    run = object()
    monkeypatch.setattr(
        conversation_queries.generation_runs_repo,
        "get_generation",
        lambda user_id, gid, *, admin: calls.append(("run", user_id, gid, admin)) or run,
    )
    monkeypatch.setattr(
        conversation_queries.generation_runs_repo,
        "list_generation_steps",
        lambda user_id, gid, **kwargs: calls.append(
            ("steps", user_id, gid, kwargs["admin"])
        )
        or [{"step_order": 0, "step_type": "generation_claimed"}],
    )

    assert ConversationQueryService().get_generation(7, generation_id) is run
    assert ConversationQueryService(admin=True).get_generation_steps(7, generation_id)[0][
        "step_order"
    ] == 0
    assert calls == [
        ("run", 7, generation_id, False),
        ("steps", 7, generation_id, True),
    ]
