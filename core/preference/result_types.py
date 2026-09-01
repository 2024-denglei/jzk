"""匹配结果集的紧凑、可持久化类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RankedCandidateRef:
    """排名中的最小引用；rank 从 1 开始。"""

    donor_id: int
    rank: int
    score: float


@dataclass(frozen=True)
class MatchResultMeta:
    result_set_id: str
    owner_user_id: int
    total: int
    profile: dict[str, Any]
    profile_hash: str
    model_version: str
    dataset_version: str
    prefer_hits: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None
    expires_at: datetime | None = None

