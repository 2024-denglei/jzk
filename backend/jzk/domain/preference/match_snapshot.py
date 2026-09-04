"""完整排名快照的公开字段白名单与版本化构建。"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import math
from typing import Any

from jzk.domain.data_loader import CARD_DONOR_KEYS, get_donor_display_info, to_card_donor_info
from jzk.domain.preference.result_types import MatchSnapshotItem
from jzk.domain.preference.scorer import FieldScore


MATCH_SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_DONOR_KEYS = frozenset(CARD_DONOR_KEYS)
MAX_SNAPSHOT_ITEM_JSON_BYTES = 64 * 1024


class MatchSnapshotValidationError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _reason(parts: list[FieldScore]) -> str:
    hits = [part.field for part in parts if part.s >= 0.8]
    return "匹配：" + "、".join(hits) if hits else "综合相似度排序"


def _field_match(parts: list[FieldScore]) -> dict[str, dict[str, Any]]:
    return {
        part.field: {
            "match": part.s >= 1.0 - 1e-9,
            "actual": _jsonable(part.actual),
            "target": _jsonable(part.target),
            "score": round(float(part.s), 6),
        }
        for part in parts
    }


def build_match_snapshot_item(
    row: dict[str, Any],
    *,
    donor_id: int,
    rank: int,
    score: float,
    parts: list[FieldScore],
) -> MatchSnapshotItem:
    donor_snapshot = to_card_donor_info(get_donor_display_info(row))
    code = str(donor_snapshot.get("code") or "").strip()
    item = MatchSnapshotItem(
        donor_id=donor_id,
        rank=rank,
        score=round(float(score), 6),
        donor_code_snapshot=code,
        donor_snapshot=donor_snapshot,
        match_explanation={
            "reason": _reason(parts),
            "match_pct": round(100 * float(score), 2),
            "match_level": (
                "full"
                if parts and all(part.s >= 1.0 - 1e-9 for part in parts)
                else "high" if score >= 0.85
                else "medium" if score >= 0.70
                else "low"
            ),
            "field_match": _field_match(parts),
            "field_scores": [_jsonable(asdict(part)) for part in parts],
        },
    )
    validate_match_snapshot_item(item)
    return item


def validate_match_snapshot_item(item: MatchSnapshotItem) -> None:
    if item.snapshot_schema_version != MATCH_SNAPSHOT_SCHEMA_VERSION:
        raise MatchSnapshotValidationError("不支持的候选快照版本")
    if item.donor_id <= 0 or item.rank <= 0:
        raise MatchSnapshotValidationError("候选 ID 和 rank 必须为正整数")
    if not math.isfinite(item.score):
        raise MatchSnapshotValidationError("候选快照 score 必须是有限数值")
    if not item.donor_code_snapshot.strip():
        raise MatchSnapshotValidationError("候选快照必须包含代号")
    unknown = set(item.donor_snapshot) - SNAPSHOT_DONOR_KEYS
    if unknown:
        raise MatchSnapshotValidationError(f"候选快照包含未授权字段：{sorted(unknown)}")
    encoded = json.dumps(
        {
            "donor": item.donor_snapshot,
            "explanation": item.match_explanation,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_ITEM_JSON_BYTES:
        raise MatchSnapshotValidationError("单个候选快照超过大小上限")
