import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from jzk.api import admin_requests as requests_mod

REGULAR = {"id": 7, "username": "viewer", "role": "donor_admin"}
SUPER = {"id": 1, "username": "root", "role": "super_admin"}


def test_regular_admin_submits_donor_status_request(monkeypatch):
    captured = {}
    monkeypatch.setattr(requests_mod, "get_donor_by_code", lambda code: {"code": code, "updated_at": "v1"})

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": 12, "status": "pending", **kwargs}

    monkeypatch.setattr(requests_mod, "create_operation_request", fake_create)
    body = requests_mod.OperationRequestBody(
        action="donor_status", target_id="D001", payload={"status": "disabled"}, reason="资料需要复核"
    )
    data = asyncio.run(requests_mod.submit_operation_request(body, REGULAR))
    assert data["status"] == "pending"
    assert captured["requester_id"] == 7
    assert captured["before_snapshot"]["updated_at"] == "v1"


def test_regular_admin_cannot_submit_unknown_permission_type(monkeypatch):
    body = requests_mod.OperationRequestBody(
        action="user_kick", target_id="3", reason="异常登录", payload={}
    )
    no_user_request = {"id": 8, "role": "unknown"}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(requests_mod.submit_operation_request(body, no_user_request))
    assert exc.value.status_code == 403


def test_super_admin_approval_executes_and_completes_request(monkeypatch):
    item = {
        "id": 21,
        "requester_id": 7,
        "action": "donor_status",
        "target_type": "donor",
        "target_id": "D001",
        "payload": {"status": "disabled"},
        "before_snapshot": {"updated_at": "v1"},
        "reason": "资料需要复核",
    }
    completed = {}
    status_call = {}
    monkeypatch.setattr(requests_mod, "claim_operation_request", lambda request_id, reviewer_id: item)
    monkeypatch.setattr(requests_mod, "get_donor_by_code", lambda code: {"code": code, "updated_at": "v1"})
    monkeypatch.setattr(requests_mod, "set_donor_status", lambda code, status, operator_id, **kwargs: status_call.update(code=code, status=status, operator_id=operator_id, **kwargs))
    monkeypatch.setattr(requests_mod, "update_donor_status_cache", lambda app, code, status: True)

    def fake_complete(request_id, **kwargs):
        completed.update(request_id=request_id, **kwargs)
        return {"id": request_id, **kwargs}

    monkeypatch.setattr(requests_mod, "complete_operation_request", fake_complete)
    data = asyncio.run(requests_mod.approve_operation_request(
        21,
        requests_mod.ReviewBody(comment="同意"),
        SimpleNamespace(app=object()),
        SUPER,
    ))
    assert status_call == {"code": "D001", "status": "disabled", "operator_id": 1, "expected_updated_at": "v1"}
    assert completed["status"] == "approved"
    assert data["status"] == "approved"


def test_approval_marks_changed_target_as_failed(monkeypatch):
    item = {
        "id": 22,
        "requester_id": 7,
        "action": "user_disable",
        "target_type": "user",
        "target_id": "9",
        "payload": {},
        "before_snapshot": {"updated_at": "v1"},
        "reason": "异常账号",
    }
    completed = {}
    monkeypatch.setattr(requests_mod, "claim_operation_request", lambda request_id, reviewer_id: item)
    monkeypatch.setattr(requests_mod, "get_user_profile", lambda user_id: {"id": user_id, "updated_at": "v2"})
    monkeypatch.setattr(requests_mod, "complete_operation_request", lambda request_id, **kwargs: completed.update(request_id=request_id, **kwargs) or {})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(requests_mod.approve_operation_request(
            22,
            requests_mod.ReviewBody(comment="同意"),
            SimpleNamespace(app=object()),
            SUPER,
        ))
    assert exc.value.status_code == 409
    assert completed["status"] == "failed"
    assert "已发生变化" in completed["execution_error"]


def test_reviewer_cannot_approve_own_or_processed_request(monkeypatch):
    monkeypatch.setattr(requests_mod, "claim_operation_request", lambda request_id, reviewer_id: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(requests_mod.approve_operation_request(
            99,
            requests_mod.ReviewBody(),
            SimpleNamespace(app=object()),
            SUPER,
        ))
    assert exc.value.status_code == 409
