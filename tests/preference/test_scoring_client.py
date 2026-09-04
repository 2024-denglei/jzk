from datetime import date
from decimal import Decimal

import httpx
import pytest

from jzk.domain.preference.scoring_client import HttpScoringRanker, normalize_donor_row
from jzk.domain.preference.scoring_contract import (
    RankerContractError,
    RankerInputError,
    RankerUnavailable,
)
from jzk.domain.preference.validate import parse_profile


PROFILE = parse_profile({
    "schema_version": "1.0",
    "attributes": {
        "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
        "height_cm": {"constraint": "prefer", "weight": 0.8, "range": {"min": 175}},
    },
})


def _ranker(handler) -> HttpScoringRanker:
    return HttpScoringRanker(
        base_url="http://scorer.test",
        token="secret-token",
        contract_version="1",
        timeout_seconds=2,
        max_candidates=20000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _success(request: httpx.Request, *, donor_id: int = 7):
    payload = __import__("json").loads(request.content)
    return httpx.Response(200, json={
        "contract_version": "1",
        "request_id": payload["request_id"],
        "model": {
            "name": "sperm-match-v4-tender-multitask",
            "version": "v32-v4-best-mae",
            "checkpoint_role": "best_mae",
            "checkpoint_epoch": 33,
            "checkpoint_sha256": "a" * 64,
            "max_attributes": 11,
            "candidate_pool": 300,
            "device": "cpu",
        },
        "eligible_count": len(payload["candidates"]),
        "ranked_count": 1,
        "items": [{
            "donor_id": donor_id,
            "rank": 1,
            "match_score": 0.91,
            "ranking_score": 0.95,
            "heuristic_score": 0.9,
            "field_scores": [{
                "field": "height_cm",
                "actual": 180,
                "target": {"min": 175, "max": None},
                "s": 1.0,
                "weight": 0.8,
                "constraint": "prefer",
            }],
        }],
        "timings": {"model_ms": 2.5},
    })


def test_sends_only_profile_fields_and_maps_response():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(__import__("json").loads(request.content))
        assert request.headers["authorization"] == "Bearer secret-token"
        return _success(request)

    ranker = _ranker(handler)
    row = {
        "id": 7,
        "code": "A7",
        "abo_blood": "O",
        "height_cm": Decimal("180"),
        "birth_date": date(1995, 1, 1),
        "personal_disease": "不得发送",
        "updated_by": 99,
    }
    ranked = ranker.rank(PROFILE, [row])
    sent = captured["candidates"][0]
    assert sent == {
        "donor_id": 7,
        "code": "A7",
        "attributes": {"abo_blood": "O", "height_cm": 180.0},
        "business": {},
    }
    assert ranked[0][0] is row
    assert ranked[0][1] == 0.91
    assert ranked[0][2][0].field == "height_cm"
    assert ranker.metadata().model_version == "v32-v4-best-mae"
    assert ranker.last_timings["scorer_model_ms"] == 2.5


def test_normalizes_rh_and_calculates_age():
    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "rh_blood": {"constraint": "must", "weight": 1, "values": ["阳性"]},
            "age": {"constraint": "prefer", "weight": 1, "range": {"max": 40}},
        },
    })
    captured = {}

    def handler(request):
        captured.update(__import__("json").loads(request.content))
        return _success(request)

    ranker = _ranker(handler)
    with pytest.raises(RankerContractError):
        # The fake response intentionally returns a different donor ID.
        ranker.rank(profile, [{
            "id": 8, "code": "A8", "rh_blood": "+", "birth_date": "1995-01-01"
        }])
    attrs = captured["candidates"][0]["attributes"]
    assert attrs["rh_blood"] == "阳性"
    assert isinstance(attrs["age"], int)


def test_input_error_and_service_error_are_distinct():
    def bad_input(_request):
        return httpx.Response(422, json={
            "error": {"code": "PROFILE_TOO_WIDE", "message": "太多属性", "retryable": False}
        })

    with pytest.raises(RankerInputError, match="太多属性"):
        _ranker(bad_input).rank(PROFILE, [{
            "id": 7, "code": "A7", "abo_blood": "O", "height_cm": 180
        }])

    def unavailable(_request):
        return httpx.Response(503, json={
            "error": {"code": "MODEL_NOT_READY", "message": "未就绪", "retryable": True}
        })

    with pytest.raises(RankerUnavailable, match="未就绪"):
        _ranker(unavailable).rank(PROFILE, [{
            "id": 7, "code": "A7", "abo_blood": "O", "height_cm": 180
        }])


def test_transport_and_malformed_response_are_service_failures():
    def disconnected(request):
        raise httpx.ConnectError("connection refused", request=request)

    row = {"id": 7, "code": "A7", "abo_blood": "O", "height_cm": 180}
    with pytest.raises(RankerUnavailable, match="评分服务不可用"):
        _ranker(disconnected).rank(PROFILE, [row])

    def malformed(_request):
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(RankerContractError, match="响应格式错误"):
        _ranker(malformed).rank(PROFILE, [row])


def test_unknown_returned_donor_is_rejected():
    ranker = _ranker(lambda request: _success(request, donor_id=999))
    with pytest.raises(RankerContractError, match="未知或重复"):
        ranker.rank(PROFILE, [{
            "id": 7, "code": "A7", "abo_blood": "O", "height_cm": 180
        }])


def test_model_info_readiness_sends_no_candidate_payload():
    def handler(request: httpx.Request):
        assert request.method == "GET"
        assert request.url.path == "/v1/model"
        assert request.content == b""
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(200, json={
            "name": "sperm-match-v4-tender-multitask",
            "version": "v32-v4-best-mae",
            "checkpoint_role": "best_mae",
            "checkpoint_epoch": 33,
            "checkpoint_sha256": "a" * 64,
            "max_attributes": 11,
            "candidate_pool": 300,
            "device": "cpu",
        })

    model = _ranker(handler).model_info()
    assert model.version == "v32-v4-best-mae"
    assert model.candidate_pool == 300


def test_donor_row_is_normalized_to_what_the_contract_expects():
    """库里的形态与契约要求的形态不同，转换发生在发请求之前。

    这个转换过去住在 core/preference/v2_adapter.py，与进程内模型副本同源；副本
    删除后它是打分客户端唯一的职责，因此并入此处。
    """
    row = {
        "code": "A1",
        "abo_blood": "O",
        "rh_blood": "+",
        "height_cm": 180,
        "birth_date": date(2000, 1, 1),
        "sideburns": "无",
    }

    out = normalize_donor_row(row)

    assert out["age"] >= 25
    assert out["rh_blood"] == "阳性"
    assert out["height_cm"] == 180
    assert out["code"] == "A1"
