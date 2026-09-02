from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.match import MatchRequest, match_donors
from core.preference.pipeline import MatchResult


def _match(payload: dict):
    return match_donors(MatchRequest.model_validate(payload), user_id=42)


VALID_PROFILE = {
    "schema_version": "1.0",
    "attributes": {
        "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
        "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
    },
}


def test_empty_profile_skips_query():
    data = _match({"profile": {"schema_version": "1.0", "attributes": {}}})
    assert data["ok"] is True
    assert data["skipped"] is True
    assert data["candidates"] == []
    assert data["match_level"] == "none"


def test_illegal_enum_is_400():
    with pytest.raises(HTTPException) as exc_info:
        _match({
            "profile": {
                "schema_version": "1.0",
                "attributes": {
                    "abo_blood": {"constraint": "must", "weight": 1, "values": ["XX"]},
                },
            }
        })
    assert exc_info.value.status_code == 400


def test_match_returns_503_when_ranker_unavailable(monkeypatch):
    from api import match as match_mod
    from core.preference.scoring_contract import RankerUnavailable

    def boom(*args, **kwargs):
        raise RankerUnavailable("找不到评分服务")

    monkeypatch.setattr(match_mod, "match_profile", boom)
    with pytest.raises(HTTPException) as exc_info:
        _match({"profile": VALID_PROFILE})
    assert exc_info.value.status_code == 503
    assert "找不到" in str(exc_info.value.detail)


def test_match_scoring_readiness_maps_dependency_failure(monkeypatch):
    from api import match as match_mod
    from core.preference import ranker_factory
    from core.preference.scoring_contract import RankerUnavailable

    monkeypatch.setattr(
        ranker_factory,
        "get_scoring_readiness",
        lambda: (_ for _ in ()).throw(RankerUnavailable("连接失败")),
    )
    with pytest.raises(HTTPException) as exc_info:
        match_mod.match_scoring_readiness()
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "MATCH_SCORER_NOT_READY"


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
    data = _match({"profile": VALID_PROFILE})
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
    data = _match({"profile": VALID_PROFILE})
    assert data["candidates"] == []
    assert data["result_set_id"] is None
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
    data = _match({"profile": VALID_PROFILE, "top_k": 1})
    assert len(data["candidates"]) == 1
    assert data["filtered_count"] == 2


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
    data = _match({"profile": VALID_PROFILE, "top_k": 1})
    assert len(data["candidates"]) == 1
    assert data["prefer_hits"] == hits
    assert data["filtered_count"] == 3


def test_invoke_match_endpoint_hits_route():
    data = _match({"profile": {"schema_version": "1.0", "attributes": {}}})
    assert data["ok"] is True
    assert data["skipped"] is True


def test_delete_referenced_match_snapshot_returns_conflict(monkeypatch):
    import asyncio

    from api import match as match_mod

    monkeypatch.setattr(match_mod, "get_match_run", lambda *_args: object())
    monkeypatch.setattr(match_mod, "delete_match_run", lambda *_args: False)

    with pytest.raises(match_mod.HTTPException) as exc_info:
        asyncio.run(match_mod.remove_match_result(str(uuid4()), user_id=7))
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "MATCH_SNAPSHOT_REFERENCED"


def test_apply_match_api_response_400_keeps_session():
    from dialogue.agent_tools import apply_match_api_response
    from dialogue.session import SessionContext

    session = SessionContext(owner_user_id=1)
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

    session = SessionContext(owner_user_id=1)
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
            "filtered_count": 4303,
            "bottlenecks": [],
            "candidates": [{"donor_info": {"code": "T", "height": 180}, "score": 1.0}],
            "prefer_hits": [
                {"field": "hometown", "label": "籍贯", "hits": 2, "of": 3},
            ],
        },
    )
    assert payload["ok"] is True
    assert payload["count"] == 4303
    assert payload["prefer_hits"] == [
        {"field": "hometown", "label": "籍贯", "hits": 2, "of": 3},
    ]
    assert "已按偏好重排" in payload["note"]
    assert cands[0]["donor_info"]["code"] == "T"
    assert session.preference_profile["attributes"]["abo_blood"]["values"] == ["O"]
    assert session.candidates[0]["donor_info"]["code"] == "T"


def test_apply_match_api_response_stores_result_reference():
    from dialogue.agent_tools import apply_match_api_response
    from dialogue.session import SessionContext

    session = SessionContext(owner_user_id=1)
    raw = {
        "schema_version": "1.0",
        "attributes": {"abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]}},
    }
    apply_match_api_response(
        session,
        raw,
        200,
        {
            "ok": True, "skipped": False, "match_level": "full", "total": 4303,
            "candidates": [{"donor_info": {"code": "T"}, "score": 1.0}],
            "result_set_id": "11111111-1111-1111-1111-111111111111",
            "next_cursor": "signed-cursor", "prefer_hits": [], "bottlenecks": [],
        },
    )
    assert session.match_result_id == "11111111-1111-1111-1111-111111111111"
    assert session.match_total == 4303
    assert session.match_next_cursor == "signed-cursor"
