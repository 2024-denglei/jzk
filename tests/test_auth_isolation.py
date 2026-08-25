from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from api.auth_utils import create_access_token, get_current_user_id
from api.chat import router as chat_router
from api.chat_stream import router as stream_router
from api.donors import router as donors_router


def test_user_token_returns_user_id():
    token = create_access_token({"sub": "42"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert get_current_user_id(creds) == 42


def test_missing_token_is_401():
    try:
        get_current_user_id(None)
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "未登录"


def test_admin_token_is_rejected():
    token = create_access_token({"sub": "1", "kind": "admin", "role": "admin"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    try:
        get_current_user_id(creds)
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "无效令牌"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(donors_router)
    app.include_router(chat_router)
    app.include_router(stream_router)
    return TestClient(app)


def test_donor_detail_with_user_token_returns_full_fields():
    import pandas as pd

    token = create_access_token({"sub": "42"})
    app = FastAPI()
    app.include_router(donors_router)
    app.state.donor_df = pd.DataFrame(
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
    res = TestClient(app).get(
        "/api/donors/ABC",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    info = res.json()["donor_info"]
    assert info["code"] == "ABC"
    assert "genetic_history" in info
    assert info["genetic_history"] == "无家族史"


def test_donor_detail_requires_auth():
    res = _client().get("/api/donors/ABC")
    assert res.status_code == 401


def test_donor_detail_rejects_admin_token():
    token = create_access_token({"sub": "1", "kind": "admin", "role": "admin"})
    res = _client().get("/api/donors/ABC", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


def test_chat_requires_auth():
    res = _client().post("/api/chat", json={"session_id": None, "message": ""})
    assert res.status_code == 401


def test_chat_rejects_admin_token():
    token = create_access_token({"sub": "1", "kind": "admin", "role": "admin"})
    res = _client().post(
        "/api/chat",
        json={"session_id": None, "message": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401


def test_chat_stream_requires_auth():
    res = _client().post("/api/chat/stream", json={"session_id": None, "message": "hello"})
    assert res.status_code == 401


def test_chat_abort_requires_auth():
    res = _client().post("/api/chat/abort", json={"session_id": "s1"})
    assert res.status_code == 401


def test_chat_rewind_requires_auth():
    res = _client().post(
        "/api/chat/rewind",
        json={"session_id": "s1", "history": []},
    )
    assert res.status_code == 401
