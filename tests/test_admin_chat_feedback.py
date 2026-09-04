from datetime import datetime, timezone
from uuid import uuid4

from jzk.api import admin_chat_feedback


ADMIN = {"id": 9, "role": "super_admin"}


def test_admin_feedback_defaults_to_dislikes_and_audits(monkeypatch):
    now = datetime.now(timezone.utc)
    message_id = uuid4()
    seen = {}
    audits = []

    def fake_list(**kwargs):
        seen.update(kwargs)
        return [{
            "message_id": message_id,
            "rating": "dislike",
            "updated_at": now,
        }]

    monkeypatch.setattr(admin_chat_feedback.chat_feedback_repo, "list_admin_feedback", fake_list)
    monkeypatch.setattr(
        admin_chat_feedback.admin_chats_repo,
        "write_sensitive_read_audit",
        lambda *args, **kwargs: audits.append((args, kwargs)),
    )

    page = admin_chat_feedback.list_feedback(
        rating="dislike",
        user_id=None,
        date_from=None,
        date_to=None,
        cursor=None,
        limit=20,
        admin=ADMIN,
    )

    assert page["items"][0]["message_id"] == message_id
    assert seen["rating"] == "dislike"
    assert seen["limit"] == 21
    assert audits[0][0][2] == "view_chat_feedback_list"


def test_admin_feedback_summary_is_audited(monkeypatch):
    audits = []
    monkeypatch.setattr(
        admin_chat_feedback.chat_feedback_repo,
        "get_admin_feedback_summary",
        lambda: {"likes": 3, "dislikes": 4, "recent_dislikes": 2},
    )
    monkeypatch.setattr(
        admin_chat_feedback.admin_chats_repo,
        "write_sensitive_read_audit",
        lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    assert admin_chat_feedback.get_feedback_summary(admin=ADMIN)["dislikes"] == 4
    assert audits[0][0][2] == "view_chat_feedback_summary"
