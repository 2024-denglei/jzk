from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RangeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "RangeSpec":
        if self.min is None and self.max is None:
            raise ValueError("range.min 和 range.max 不能同时为空")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("range.min 不能大于 range.max")
        return self


class AttributeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["range", "enum", "keyword"]
    constraint: Literal["must", "prefer"]
    weight: float = Field(ge=0.0, le=1.0)
    values: list[Any] | None = None
    range: RangeSpec | None = None
    keywords: list[str] | None = None
    match: Literal["any", "all"] = "any"

    @model_validator(mode="after")
    def validate_target(self) -> "AttributeSpec":
        if self.type == "range":
            if self.range is None or self.values is not None or self.keywords is not None:
                raise ValueError("range 类型必须且只能提供 range")
        elif self.type == "enum":
            if not self.values or self.range is not None or self.keywords is not None:
                raise ValueError("enum 类型必须且只能提供非空 values")
        elif not self.keywords or self.range is not None or self.values is not None:
            raise ValueError("keyword 类型必须且只能提供非空 keywords")
        return self

    def to_engine_spec(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        if "range" in data:
            data["range"] = self.range.model_dump() if self.range else None
        return data


class ProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    attributes: dict[str, AttributeSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights(self) -> "ProfileSpec":
        if sum(attr.weight for attr in self.attributes.values()) <= 0:
            raise ValueError("所有属性的权重总和必须大于0")
        return self

    def to_engine_profile(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "attributes": {
                name: spec.to_engine_spec()
                for name, spec in self.attributes.items()
            },
        }


class CandidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    donor_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=128)
    attributes: dict[str, Any] = Field(default_factory=dict)
    business: dict[str, Any] = Field(default_factory=dict)


class RankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1"]
    request_id: str = Field(min_length=1, max_length=128)
    profile: ProfileSpec
    candidates: list[CandidatePayload] = Field(min_length=1)


class FieldScorePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    actual: Any
    target: Any
    s: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    constraint: Literal["must", "prefer"]


class RankedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    donor_id: int
    rank: int = Field(gt=0)
    match_score: float = Field(ge=0.0, le=1.0)
    ranking_score: float = Field(ge=0.0, le=1.0)
    heuristic_score: float = Field(ge=0.0, le=1.0)
    field_scores: list[FieldScorePayload]


class ModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    checkpoint_role: str
    checkpoint_epoch: int | None
    checkpoint_sha256: str
    max_attributes: int
    candidate_pool: int
    device: str


class RankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1"]
    request_id: str
    model: ModelIdentity
    eligible_count: int = Field(ge=0)
    ranked_count: int = Field(ge=0)
    items: list[RankedItem]
    timings: dict[str, float]
