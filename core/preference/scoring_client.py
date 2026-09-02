from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import math
import threading
from typing import Any
from uuid import uuid4

import httpx
from pydantic import ValidationError

from core.preference.schema import EnumAttr, KeywordAttr, PreferenceProfile, RangeAttr
from core.preference.scorer import FieldScore, Ranker
from core.preference.scoring_contract import (
    RankerContractError,
    RankerInputError,
    RankerUnavailable,
    ScoringMetadata,
)
from core.preference.v2_adapter import donor_row_to_v2
from services.match_scorer.api_models import ModelIdentity, RankRequest, RankResponse


def profile_to_scoring_spec(profile: PreferenceProfile) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for name, attr in profile.attributes.items():
        if isinstance(attr, RangeAttr):
            attributes[name] = {
                "type": "range",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "range": {"min": attr.range.min, "max": attr.range.max},
            }
        elif isinstance(attr, EnumAttr):
            attributes[name] = {
                "type": "enum",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "values": list(attr.values),
            }
        elif isinstance(attr, KeywordAttr):
            attributes[name] = {
                "type": "keyword",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "keywords": list(attr.keywords),
                "match": attr.match,
            }
        else:  # pragma: no cover - schema union protects this branch
            raise RankerInputError(f"不支持的画像字段类型：{name}")
    return {"schema_version": profile.schema_version, "attributes": attributes}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _donor_id(row: dict[str, Any]) -> int:
    try:
        donor_id = int(row.get("id"))
    except (TypeError, ValueError) as exc:
        raise RankerInputError("评分服务要求候选包含正整数 donor id") from exc
    if donor_id <= 0:
        raise RankerInputError("评分服务要求候选包含正整数 donor id")
    return donor_id


def _candidate_payload(
    profile: PreferenceProfile,
    row: dict[str, Any],
) -> dict[str, Any]:
    normalized = donor_row_to_v2(row)
    attributes: dict[str, Any] = {}
    business: dict[str, Any] = {}
    for field in profile.attributes:
        value = _jsonable(normalized.get(field))
        if field == "specimen_count":
            business[field] = value
        else:
            attributes[field] = value
    code = str(row.get("code") or "").strip()
    if not code:
        raise RankerInputError("评分服务要求候选包含 code")
    return {
        "donor_id": _donor_id(row),
        "code": code,
        "attributes": attributes,
        "business": business,
    }


def _remote_message(response: httpx.Response) -> tuple[str, bool]:
    try:
        error = response.json().get("error") or {}
    except Exception:
        error = {}
    message = str(error.get("message") or f"评分服务返回 HTTP {response.status_code}")
    return message, bool(error.get("retryable"))


class HttpScoringRanker(Ranker):
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        contract_version: str,
        timeout_seconds: float,
        max_candidates: int,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.contract_version = contract_version
        self.max_candidates = max_candidates
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
        )
        self._local = threading.local()
        self.last_timings: dict[str, float] = {}

    def metadata(self) -> ScoringMetadata | None:
        return getattr(self._local, "metadata", None)

    def model_info(self) -> ModelIdentity:
        """探测远端模型能力；供主应用 readiness 使用，不发送候选资料。"""
        try:
            response = self._client.get(
                f"{self.base_url}/v1/model",
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except httpx.TransportError as exc:
            raise RankerUnavailable(f"评分服务不可用：{exc}") from exc
        if response.status_code != 200:
            message, _retryable = _remote_message(response)
            raise RankerUnavailable(message)
        try:
            model = ModelIdentity.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise RankerContractError("评分服务模型信息格式错误") from exc
        self._validate_model_identity(model)
        return model

    def rank(
        self,
        profile: PreferenceProfile,
        rows: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], float, list[FieldScore]]]:
        if not rows:
            return []
        if len(rows) > self.max_candidates:
            raise RankerInputError(
                f"must 合格人数超过评分服务上限 {self.max_candidates}"
            )
        request_id = str(uuid4())
        try:
            request = RankRequest.model_validate({
                "contract_version": self.contract_version,
                "request_id": request_id,
                "profile": profile_to_scoring_spec(profile),
                "candidates": [
                    _candidate_payload(profile, row) for row in rows
                ],
            })
        except ValidationError as exc:
            raise RankerInputError(str(exc)) from exc

        try:
            response = self._client.post(
                f"{self.base_url}/v1/rank",
                json=request.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except httpx.TransportError as exc:
            raise RankerUnavailable(f"评分服务不可用：{exc}") from exc
        if response.status_code in {400, 413, 422}:
            message, _retryable = _remote_message(response)
            raise RankerInputError(message)
        if response.status_code != 200:
            message, _retryable = _remote_message(response)
            raise RankerUnavailable(message)
        try:
            payload = RankResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise RankerContractError("评分服务响应格式错误") from exc
        self._validate_response(payload, request_id, rows)

        by_id = {_donor_id(row): row for row in rows}
        ranked = []
        for item in payload.items:
            parts = [
                FieldScore(
                    field=part.field,
                    actual=part.actual,
                    target=part.target,
                    s=float(part.s),
                    weight=float(part.weight),
                    constraint=part.constraint,
                )
                for part in item.field_scores
            ]
            ranked.append((by_id[item.donor_id], float(item.match_score), parts))
        metadata = ScoringMetadata(
            model_name=payload.model.name,
            model_version=payload.model.version,
            checkpoint_role=payload.model.checkpoint_role,
            checkpoint_sha256=payload.model.checkpoint_sha256,
            timings=dict(payload.timings),
            eligible_count=payload.eligible_count,
            ranked_count=payload.ranked_count,
        )
        self._local.metadata = metadata
        self.last_timings = {
            f"scorer_{key}": float(value)
            for key, value in payload.timings.items()
        }
        self.last_timings.update({
            "scorer_eligible_rows": float(payload.eligible_count),
            "scorer_ranked_rows": float(payload.ranked_count),
        })
        return ranked

    def _validate_response(
        self,
        payload: RankResponse,
        request_id: str,
        rows: list[dict[str, Any]],
    ) -> None:
        if payload.contract_version != self.contract_version:
            raise RankerContractError("评分服务契约版本不一致")
        if payload.request_id != request_id:
            raise RankerContractError("评分服务 request_id 不一致")
        if payload.eligible_count != len(rows):
            raise RankerContractError("评分服务 eligible_count 不一致")
        if payload.ranked_count != len(payload.items):
            raise RankerContractError("评分服务 ranked_count 不一致")
        if payload.ranked_count > len(rows):
            raise RankerContractError("评分服务返回了过多候选")
        expected_ranks = list(range(1, len(payload.items) + 1))
        if [item.rank for item in payload.items] != expected_ranks:
            raise RankerContractError("评分服务 rank 不连续")
        allowed = {_donor_id(row) for row in rows}
        returned = [item.donor_id for item in payload.items]
        if len(returned) != len(set(returned)) or not set(returned) <= allowed:
            raise RankerContractError("评分服务返回未知或重复 donor")
        self._validate_model_identity(payload.model)
        if payload.ranked_count > payload.model.candidate_pool:
            raise RankerContractError("评分服务返回条数超过模型候选池")
        for item in payload.items:
            for value in (
                item.match_score,
                item.ranking_score,
                item.heuristic_score,
            ):
                if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                    raise RankerContractError("评分服务返回无效分数")

    @staticmethod
    def _validate_model_identity(model: ModelIdentity) -> None:
        if not model.name or not model.version or not model.checkpoint_role:
            raise RankerContractError("评分服务缺少模型身份")
        digest = model.checkpoint_sha256.lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RankerContractError("评分服务 checkpoint 哈希无效")
        if model.max_attributes <= 0 or model.candidate_pool <= 0:
            raise RankerContractError("评分服务模型能力声明无效")
