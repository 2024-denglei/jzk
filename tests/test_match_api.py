from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_utils import create_access_token


class _SessionRow:
    def fetchone(self):
        return {"status": "active", "token_version": 0}


class _SessionConn:
    def execute(self, _sql, _params=()):
        return _SessionRow()


@contextmanager
def _active_user_session():
    yield _SessionConn()


@pytest.fixture(autouse=True)
def active_user(monkeypatch):
    monkeypatch.setattr("db.database.db_session", _active_user_session)
from api.match import router as match_router
from core.preference.pipeline import MatchResult


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(match_router)
    return app


def _auth_headers() -> dict[str, str]:
    token = create_access_token({"sub": "42", "ver": 0})
    return {"Authorization": f"Bearer {token}"}


VALID_PROFILE = {
    "schema_version": "1.0",
    "attributes": {
        "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
        "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
    },
}


def test_match_requires_auth():
    res = TestClient(_app()).post("/api/match", json={"profile": {"schema_version": "1.0", "attributes": {}}})
    assert res.status_code == 401


def test_match_rejects_admin_token():
    token = create_access_token({"sub": "1", "kind": "admin", "role": "admin"})
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": {"schema_version": "1.0", "attributes": {}}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401


def test_empty_profile_skips_query():
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": {"schema_version": "1.0", "attributes": {}}},
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["skipped"] is True
    assert data["candidates"] == []
    assert data["match_level"] == "none"


def test_illegal_enum_is_400():
    res = TestClient(_app()).post(
        "/api/match",
        json={
            "profile": {
                "schema_version": "1.0",
                "attributes": {
                    "abo_blood": {"constraint": "must", "weight": 1, "values": ["XX"]},
                },
            }
        },
        headers=_auth_headers(),
    )
    assert res.status_code == 400
    assert "detail" in res.json()


def test_match_returns_503_when_ranker_unavailable(monkeypatch):
    from api import match as match_mod
    from core.preference.v2_ranker import V2RankerUnavailable

    def boom(*args, **kwargs):
        raise V2RankerUnavailable("找不到模型文件")

    monkeypatch.setattr(match_mod, "match_profile", boom)
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE},
        headers=_auth_headers(),
    )
    assert res.status_code == 503
    assert "找不到" in str(res.json()["detail"])


def test_match_ranks_and_returns_field_scores(monkeypatch):
    from api import match as match_mod

    def fake_match(profile, **kwargs):
        return MatchResult(
            candidates=[
                {
                    "rank": 1,
                    "score": 0.9,
                    "match_pct": 90.0,
                    "reason": "匹配：abo_blood",
                    "match_level": "full",
                    "donor_info": {"code": "T", "blood_type": "O"},
                    "field_match": {},
                    "field_scores": [{"field": "abo_blood", "s": 1.0, "weight": 1.0}],
                },
                {
                    "rank": 2,
                    "score": 0.5,
                    "match_pct": 50.0,
                    "reason": "匹配：abo_blood",
                    "match_level": "full",
                    "donor_info": {"code": "S", "blood_type": "O"},
                    "field_match": {},
                    "field_scores": [{"field": "abo_blood", "s": 1.0, "weight": 1.0}],
                },
            ],
            match_level="full",
            bottlenecks=[],
            skipped=False,
            filtered_count=2,
        )

    monkeypatch.setattr(match_mod, "match_profile", fake_match)
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE},
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["filtered_count"] == 2
    assert data["candidates"][0]["donor_info"]["code"] == "T"
    assert "field_scores" in data["candidates"][0]
    assert data["prefer_hits"] == []


def test_zero_hits_returns_bottlenecks(monkeypatch):
    from api import match as match_mod

    monkeypatch.setattr(
        match_mod,
        "match_profile",
        lambda profile, **kwargs: MatchResult(
            candidates=[],
            match_level="none",
            bottlenecks=[{"field": "abo_blood", "recovered": 120}],
            skipped=False,
            filtered_count=0,
        ),
    )
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE},
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["candidates"] == []
    assert data["bottlenecks"][0]["field"] == "abo_blood"


def test_top_k_truncates(monkeypatch):
    from api import match as match_mod

    monkeypatch.setattr(
        match_mod,
        "match_profile",
        lambda profile, **kwargs: MatchResult(
            candidates=[
                {"rank": 1, "score": 0.9, "donor_info": {"code": "A"}, "field_scores": []},
                {"rank": 2, "score": 0.8, "donor_info": {"code": "B"}, "field_scores": []},
            ],
            match_level="full",
            bottlenecks=[],
            skipped=False,
            filtered_count=2,
        ),
    )
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE, "top_k": 1},
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    assert len(res.json()["candidates"]) == 1
    assert res.json()["filtered_count"] == 2


def test_execute_match_returns_prefer_hits_before_top_k(monkeypatch):
    from api import match as match_mod

    hits = [{"field": "hometown", "label": "籍贯", "hits": 2, "of": 3}]
    monkeypatch.setattr(
        match_mod,
        "match_profile",
        lambda profile, **kwargs: MatchResult(
            candidates=[
                {"rank": 1, "score": 0.9, "donor_info": {"code": "A"}, "field_scores": []},
                {"rank": 2, "score": 0.8, "donor_info": {"code": "B"}, "field_scores": []},
                {"rank": 3, "score": 0.1, "donor_info": {"code": "C"}, "field_scores": []},
            ],
            match_level="full",
            bottlenecks=[],
            skipped=False,
            filtered_count=3,
            prefer_hits=hits,
        ),
    )
    res = TestClient(_app()).post(
        "/api/match",
        json={"profile": VALID_PROFILE, "top_k": 1},
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["candidates"]) == 1
    assert data["prefer_hits"] == hits
    assert data["filtered_count"] == 3


def test_invoke_match_endpoint_hits_route():
    import asyncio

    from api.match import invoke_match_endpoint

    token = create_access_token({"sub": "42", "ver": 0})
    status, data = asyncio.run(
        invoke_match_endpoint(
            _app(),
            f"Bearer {token}",
            {"schema_version": "1.0", "attributes": {}},
        )
    )
    assert status == 200
    assert data["ok"] is True
    assert data["skipped"] is True


def test_apply_match_api_response_400_keeps_session():
    from dialogue.agent_tools import apply_match_api_response
    from dialogue.session import SessionContext

    session = SessionContext()
    good = {
        "schema_version": "1.0",
        "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}},
    }
    session.replace_profile(good)
    cands, payload = apply_match_api_response(
        session,
        {"schema_version": "1.0", "attributes": {"code": {"constraint": "must", "weight": 1, "keywords": ["x"]}}},
        400,
        {"detail": "unknown or blocked field: code"},
    )
    assert cands == []
    assert payload["ok"] is False
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]


def test_apply_match_api_response_200_updates_session():
    from dialogue.agent_tools import apply_match_api_response
    from dialogue.session import SessionContext

    session = SessionContext()
    raw = {
        "schema_version": "1.0",
        "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}},
    }
    cands, payload = apply_match_api_response(
        session,
        raw,
        200,
        {
            "ok": True,
            "skipped": False,
            "match_level": "full",
            "filtered_count": 1,
            "bottlenecks": [],
            "candidates": [{"donor_info": {"code": "T", "height": 180}, "score": 1.0}],
            "prefer_hits": [
                {"field": "hometown", "label": "籍贯", "hits": 2, "of": 3},
            ],
        },
    )
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["prefer_hits"] == [
        {"field": "hometown", "label": "籍贯", "hits": 2, "of": 3},
    ]
    assert "已按偏好重排" in payload["note"]
    assert cands[0]["donor_info"]["code"] == "T"
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert session.candidates[0]["donor_info"]["code"] == "T"
