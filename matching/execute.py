"""执行一次匹配：校验画像、硬过滤、打分、落快照。

HTTP 与对话顾问都只调这里，彼此不 import。这是拆掉 api ↔ dialogue 环的那一层。
"""

from __future__ import annotations

from typing import Any
import time
from uuid import uuid4

import config
from core.preference.pipeline import match_profile
from core.preference.result_types import MatchResultMeta
from core.preference.validate import parse_profile
from db.donors_repo import (
    count_matching_donors,
    fetch_matching_donors,
    get_donor_dataset_version,
)
from db.match_runs_repo import (
    MatchRunValidationError,
    create_match_run,
    profile_digest,
)
from matching.cursor import encode_match_cursor


def _initial_page_size(top_k: int, page_size: int | None) -> int:
    if top_k > 0:  # 兼容迁移期旧调用方
        return min(top_k, 100)
    requested = page_size or config.MATCH_RESULT_PAGE_SIZE_DEFAULT
    return max(1, min(requested, config.MATCH_RESULT_PAGE_SIZE_MAX))


def execute_match(
    raw_profile: dict[str, Any],
    top_k: int = 0,
    *,
    page_size: int | None = None,
    owner_user_id: int | None = None,
    **match_kwargs,
) -> dict[str, Any]:
    """校验画像后过滤+排序。HTTP 与对话共用。"""
    t0 = time.perf_counter()
    profile = parse_profile(raw_profile)
    parse_ms = (time.perf_counter() - t0) * 1000
    detail_limit = _initial_page_size(top_k, page_size)
    match_kwargs.setdefault("detail_limit", detail_limit)
    match_kwargs.setdefault(
        "build_snapshot",
        bool(
            owner_user_id is not None
            and (config.MATCH_SNAPSHOT_ENABLED or config.MATCH_RESULT_PAGING_ENABLED)
        ),
    )
    match_kwargs.setdefault("fetch_rows", fetch_matching_donors)
    match_kwargs.setdefault("count_rows", count_matching_donors)
    result = match_profile(profile, **match_kwargs)
    candidates = result.candidates[:detail_limit]
    slice_ms = 0.0
    # 兼容 mock/旧自定义 matcher 未识别 detail_limit 的情况。
    if top_k > 0:
        t1 = time.perf_counter()
        candidates = candidates[:top_k]
        slice_ms = (time.perf_counter() - t1) * 1000

    result_set_id: str | None = None
    refs = list(result.ranked_refs or [])
    total = (
        len(refs)
        if refs
        else int(
            result.ranked_count
            if result.ranked_count is not None
            else result.filtered_count
        )
    )
    model_version = result.model_version or config.MATCH_MODEL_VERSION
    if (
        owner_user_id is not None
        and total > 0
        and not result.skipped
        and len(refs) == total
        and (config.MATCH_SNAPSHOT_ENABLED or config.MATCH_RESULT_PAGING_ENABLED)
    ):
        result_set_id = str(uuid4())
        meta = MatchResultMeta(
            result_set_id=result_set_id,
            owner_user_id=owner_user_id,
            total=total,
            profile=profile.model_dump(mode="json"),
            profile_hash=profile_digest(profile.model_dump(mode="json")),
            model_version=model_version,
            model_checkpoint_sha256=result.checkpoint_sha256,
            dataset_version=get_donor_dataset_version(),
            prefer_hits=list(result.prefer_hits or []),
        )
        if len(result.snapshot_items) != total:
            raise MatchRunValidationError("匹配结果缺少完整候选展示快照")
        meta = create_match_run(meta, refs, result.snapshot_items)

    timings = dict(result.timings or {})
    timings["parse_profile_ms"] = round(parse_ms, 1)
    if top_k > 0:
        timings["top_k_slice_ms"] = round(slice_ms, 1)
    next_offset = len(candidates)
    next_cursor = (
        encode_match_cursor(result_set_id, next_offset)
        if result_set_id and next_offset < total
        else None
    )
    return {
        "ok": True,
        "skipped": result.skipped,
        "match_level": result.match_level,
        "filtered_count": result.filtered_count,
        "ranked_count": total,
        "total": total,
        "returned_count": len(candidates),
        "bottlenecks": result.bottlenecks,
        "candidates": candidates,
        "items": candidates,
        "result_set_id": result_set_id,
        "next_cursor": next_cursor,
        "timings": timings,
        "prefer_hits": list(result.prefer_hits or []),
        "model_version": model_version,
        "model_checkpoint_sha256": result.checkpoint_sha256,
    }
