from __future__ import annotations

from dataclasses import dataclass, field


class RankerUnavailable(RuntimeError):
    """The configured scoring backend cannot complete inference."""


class RankerInputError(ValueError):
    """The validated business profile is unsupported by the scoring backend."""


class RankerContractError(RankerUnavailable):
    """The scoring service returned a response that violates contract v1."""


@dataclass(frozen=True)
class ScoringMetadata:
    model_name: str
    model_version: str
    checkpoint_role: str = ""
    checkpoint_sha256: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    eligible_count: int = 0
    ranked_count: int = 0
