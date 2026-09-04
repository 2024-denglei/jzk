import asyncio

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.auth_utils import create_access_token, get_current_user_id
from api.donors import get_donor


@pytest.fixture(autouse=True)
def active_user(monkeypatch):
    monkeypatch.setattr(
        "api.auth_utils.get_auth_state",
        lambda _user_id: {"status": "active", "token_version": 0},
    )
    monkeypatch.setattr("core.preference.match_log.append_feedback_event", lambda _event: None)


def test_user_token_returns_user_id():
    token = create_access_token({"sub": "42", "ver": 0})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert get_current_user_id(creds) == 42


def test_missing_token_is_401():
    try:
        get_current_user_id(None)
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "未登录"


def test_user_token_version_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "api.auth_utils.get_auth_state",
        lambda _user_id: {"status": "active", "token_version": 2},
    )
    token = create_access_token({"sub": "42", "ver": 1})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(creds)
    assert exc.value.status_code == 401
    assert "重新登录" in exc.value.detail


def test_disabled_user_token_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "api.auth_utils.get_auth_state",
        lambda _user_id: {"status": "disabled", "token_version": 0},
    )
    token = create_access_token({"sub": "42", "ver": 0})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(creds)
    assert exc.value.status_code == 401
    assert exc.value.detail == "账号已停用"


def test_admin_token_is_rejected():
    token = create_access_token({"sub": "1", "kind": "admin", "role": "admin"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    try:
        get_current_user_id(creds)
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "无效令牌"


def test_donor_detail_with_user_token_returns_full_fields():
    import pandas as pd

    class State:
        donor_df = pd.DataFrame(
            [
                {
                    "代号": "ABC",
                    "遗传病史": "无家族史",
                    "性传播疾病史": "无",
                    "个人病史": "无",
                    "标本数量": 3,
                }
            ]
        )

    class App:
        state = State()

    class Request:
        app = App()

    info = asyncio.run(get_donor("ABC", Request(), 42))["donor_info"]
    assert info["code"] == "ABC"
    assert "genetic_history" in info
    assert info["genetic_history"] == "无家族史"
