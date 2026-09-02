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
class MatchSnapshotItem:
    """匹配发生时冻结的单个排名项；不包含后台私密候选字段。"""

    donor_id: int
    rank: int
    score: float
    donor_code_snapshot: str
    donor_snapshot: dict[str, Any]
    match_explanation: dict[str, Any]
    snapshot_schema_version: int = 1


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
    model_checkpoint_sha256: str = ""
    status: str = "ready"
    snapshot_schema_version: int = 1
    snapshot_source: str = "native"
    created_at: datetime | None = None
    ready_at: datetime | None = None
