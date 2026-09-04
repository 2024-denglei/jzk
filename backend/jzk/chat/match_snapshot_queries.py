"""冻结匹配排名的共享加载逻辑。"""

from __future__ import annotations

from typing import Any

from jzk import config
from jzk.db.donors_repo import get_donor_statuses_by_ids
from jzk.db.match_runs_repo import get_match_run_items_page


class MatchSnapshotNotFound(LookupError):
    pass


def get_frozen_match_page(
    owner_user_id: int,
    result_set_id: str,
    *,
    page: int,
    limit: int,
) -> dict[str, Any]:
    """按严格 rank 返回冻结资料，并只把当前可用状态作为附加信息。"""
    page = max(1, int(page))
    limit = max(1, min(int(limit), config.MATCH_RESULT_PAGE_SIZE_MAX))
    offset = (page - 1) * limit
    loaded = get_match_run_items_page(
        result_set_id,
        owner_user_id,
        offset=offset,
        limit=limit,
    )
    if loaded is None:
        raise MatchSnapshotNotFound("完整匹配快照不存在")
    meta, frozen_items = loaded
    current_statuses = get_donor_statuses_by_ids([item.donor_id for item in frozen_items])
    items = []
    for item in frozen_items:
        current_status = current_statuses.get(item.donor_id, "deleted")
        donor_info = dict(item.donor_snapshot)
        # status_snapshot 保留匹配当时值；status 表示当前状态，便于旧卡片组件迁移。
        donor_info["status_snapshot"] = donor_info.get("status")
        donor_info["status"] = current_status
        items.append(
            {
                "rank": item.rank,
                "score": item.score,
                "donor_id": item.donor_id,
                "donor_code_snapshot": item.donor_code_snapshot,
                "donor_info": donor_info,
                "match_explanation": item.match_explanation,
                "current_status": current_status,
                "currently_selectable": current_status == "active",
                "snapshot_schema_version": item.snapshot_schema_version,
            }
        )
    return {
        "result_set_id": result_set_id,
        "total": meta.total,
        "page": page,
        "page_size": limit,
        "returned_count": len(items),
        "items": items,
        "has_more": offset + len(items) < meta.total,
        "model_version": meta.model_version,
        "model_checkpoint_sha256": meta.model_checkpoint_sha256,
        "dataset_version": meta.dataset_version,
        "snapshot_schema_version": meta.snapshot_schema_version,
        "snapshot_source": meta.snapshot_source,
    }
