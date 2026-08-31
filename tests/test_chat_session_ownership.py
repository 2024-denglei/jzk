import asyncio

import pytest
from fastapi import HTTPException

from api import feedback as feedback_api
from api.auth_utils import get_current_user_id
from dialogue.session import SessionContext, SessionManager


def test_session_context_requires_valid_owner():
    with pytest.raises(ValueError, match="owner_user_id"):
        SessionContext(owner_user_id=0)


def test_same_session_id_is_isolated_by_user():
    manager = SessionManager()
    first = manager.put_session(SessionContext(owner_user_id=1, session_id="shared-id"))
    second = manager.put_session(SessionContext(owner_user_id=2, session_id="shared-id"))

    first.add_message("user", "用户一")
    second.add_message("user", "用户二")

    assert manager.get_session(1, "shared-id") is first
    assert manager.get_session(2, "shared-id") is second
    assert manager.get_session(3, "shared-id") is None
    assert first.history != second.history


def test_restore_session_is_scoped_to_user():
    manager = SessionManager()
    first = manager.restore_session(1, "resume-id", state={"history": [{"role": "user", "content": "A"}]})
    second = manager.restore_session(2, "resume-id", state={"history": [{"role": "user", "content": "B"}]})

    assert first.owner_user_id == 1
    assert second.owner_user_id == 2
    assert first.history[0]["content"] == "A"
    assert second.history[0]["content"] == "B"


def test_feedback_routes_require_user_authentication():
    protected_paths = {"/api/feedback", "/api/session/{session_id}"}
    for route in feedback_api.router.routes:
        if getattr(route, "path", None) not in protected_paths:
            continue
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        assert get_current_user_id in dependency_calls


def test_feedback_rejects_other_users_session(monkeypatch):
    manager = SessionManager()
    session = manager.put_session(SessionContext(owner_user_id=1, session_id="private"))
    session.candidates = [{"donor_info": {"code": "A001"}}]
    monkeypatch.setitem(feedback_api._deps, "session_manager", manager)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            feedback_api.submit_feedback(
                feedback_api.FeedbackRequest(
                    session_id="private",
                    candidate_id="A001",
                    feedback="like",
                ),
                user_id=2,
            )
        )
    assert exc.value.status_code == 404


def test_feedback_only_accepts_candidate_from_session(monkeypatch):
    manager = SessionManager()
    session = manager.put_session(SessionContext(owner_user_id=1, session_id="private"))
    session.candidates = [{"donor_info": {"code": "A001"}}]
    monkeypatch.setitem(feedback_api._deps, "session_manager", manager)
    monkeypatch.setattr(feedback_api, "record_feedback", lambda *_args: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            feedback_api.submit_feedback(
                feedback_api.FeedbackRequest(
                    session_id="private",
                    candidate_id="B002",
                    feedback="dislike",
                ),
                user_id=1,
            )
        )
    assert exc.value.status_code == 404

    response = asyncio.run(
        feedback_api.submit_feedback(
            feedback_api.FeedbackRequest(
                session_id="private",
                candidate_id="A001",
                feedback="like",
            ),
            user_id=1,
        )
    )
    assert response.success is True
    assert session.feedback_log[-1]["candidate_id"] == "A001"
