"""校验后的偏好画像匹配、严格快照与详情分页。"""

from typing import Any
import logging
import time
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import config
from api.auth_utils import get_current_user_id
from api.match_cursor import InvalidMatchCursor, decode_match_cursor, encode_match_cursor
from api.match_result_store import MatchResultStore, MatchResultStoreUnavailable
from core.preference.pipeline import hydrate_ranked_candidates, match_profile
from core.preference.result_types import MatchResultMeta, RankedCandidateRef
from core.preference.validate import ProfileValidationError, parse_profile
from core.preference.v2_ranker import V2RankerUnavailable
from db.donors_repo import get_active_donors_by_ids, get_donor_dataset_version
from db.match_runs_repo import (
    create_match_run,
    delete_match_run,
    get_all_match_run_refs,
    get_match_run,
    get_match_run_page,
    match_run_is_expired,
    profile_digest,
)

router = APIRouter(tags=["match"])
logger = logging.getLogger(__name__)


class MatchRequest(BaseModel):
    profile: dict[str, Any]
    top_k: int = Field(default=0, ge=0)
    page_size: int | None = Field(default=None, ge=1)


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
    """匹配层实现：校验画像后过滤+排序。HTTP 与对话共用。"""
    t0 = time.perf_counter()
    profile = parse_profile(raw_profile)
    parse_ms = (time.perf_counter() - t0) * 1000
    detail_limit = _initial_page_size(top_k, page_size)
    match_kwargs.setdefault("detail_limit", detail_limit)
    result = match_profile(profile, **match_kwargs)
    candidates = result.candidates[:detail_limit]
    slice_ms = 0.0
    # 兼容 mock/旧自定义 matcher 未识别 detail_limit 的情况。
    if top_k > 0:
        t1 = time.perf_counter()
        candidates = candidates[:top_k]
        slice_ms = (time.perf_counter() - t1) * 1000

    result_set_id: str | None = None
    total = int(result.filtered_count)
    refs = list(result.ranked_refs or [])
    if (
        owner_user_id is not None
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
            model_version=config.MATCH_MODEL_VERSION,
            dataset_version=get_donor_dataset_version(),
            prefer_hits=list(result.prefer_hits or []),
        )
        if config.MATCH_SNAPSHOT_ENABLED:
            meta = create_match_run(meta, refs)
        if config.MATCH_RESULT_PAGING_ENABLED:
            try:
                MatchResultStore().create(meta, refs)
            except MatchResultStoreUnavailable:
                # PostgreSQL 快照已经提交，Redis 失败只影响缓存，不影响严格结果。
                logger.exception("Redis 匹配结果集写入失败 result_set_id=%s", result_set_id[:8])

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
        "total": total,
        "returned_count": len(candidates),
        "bottlenecks": result.bottlenecks,
        "candidates": candidates,
        "items": candidates,
        "result_set_id": result_set_id,
        "next_cursor": next_cursor,
        "timings": timings,
        "prefer_hits": list(result.prefer_hits or []),
        "model_version": config.MATCH_MODEL_VERSION,
    }


@router.post("/api/match")
async def match_donors(body: MatchRequest, user_id: int = Depends(get_current_user_id)):
    """提交完整 PreferenceProfile，内部完成过滤与排序。"""
    try:
        return execute_match(
            body.profile,
            top_k=body.top_k,
            page_size=body.page_size,
            owner_user_id=user_id,
            log=True,
        )
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except V2RankerUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _load_compact_page(
    owner_user_id: int,
    result_set_id: str,
    *,
    offset: int,
    limit: int,
) -> tuple[MatchResultMeta, list[RankedCandidateRef]] | None:
    """优先 Redis；miss/故障时读取严格快照并尽力恢复 Redis。"""
    store = MatchResultStore()
    cached = None
    try:
        cached = store.page(owner_user_id, result_set_id, offset=offset, limit=limit)
    except MatchResultStoreUnavailable:
        logger.warning("Redis 匹配分页降级 result_set_id=%s", result_set_id[:8])
    if cached is not None:
        return cached

    snapshot_page = get_match_run_page(
        result_set_id, owner_user_id, offset=offset, limit=limit
    )
    if snapshot_page is None:
        return None
    meta, refs = snapshot_page
    if match_run_is_expired(meta):
        raise HTTPException(
            status_code=410,
            detail={"code": "MATCH_SNAPSHOT_EXPIRED", "message": "匹配快照已过期"},
        )
    try:
        complete = get_all_match_run_refs(result_set_id, owner_user_id)
        if complete is not None:
            store.create(*complete)
    except MatchResultStoreUnavailable:
        pass
    return meta, refs


def _page_payload(
    owner_user_id: int,
    result_set_id: str,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """跳过已停用候选并向后补齐当前页，cursor 指向实际扫描位置。"""
    items: list[dict[str, Any]] = []
    scan_offset = offset
    meta: MatchResultMeta | None = None
    profile = None
    while len(items) < limit:
        chunk_size = min(config.MATCH_RESULT_PAGE_SIZE_MAX, max(limit - len(items), 10))
        loaded = _load_compact_page(
            owner_user_id, result_set_id, offset=scan_offset, limit=chunk_size
        )
        if loaded is None:
            raise HTTPException(status_code=404, detail="匹配结果不存在")
        meta, refs = loaded
        if profile is None:
            profile = parse_profile(meta.profile)
        if not refs:
            scan_offset = meta.total
            break
        rows = get_active_donors_by_ids([ref.donor_id for ref in refs])
        hydrated = hydrate_ranked_candidates(profile, refs, rows)
        selected = hydrated[: limit - len(items)]
        items.extend(selected)
        # 只消费到本页最后实际返回的 rank，避免预取时跳过仍未展示的候选。
        if len(items) >= limit and selected:
            scan_offset = int(selected[-1]["rank"])
        else:
            scan_offset += len(refs)
        if scan_offset >= meta.total:
            break
    assert meta is not None
    has_more = scan_offset < meta.total
    return {
        "result_set_id": result_set_id,
        "total": meta.total,
        "returned_count": len(items),
        "items": items,
        "next_cursor": encode_match_cursor(result_set_id, scan_offset) if has_more else None,
        "has_more": has_more,
        "model_version": meta.model_version,
    }


@router.get("/api/match/results/{result_set_id}")
async def get_match_results(
    result_set_id: str,
    cursor: str | None = None,
    limit: int = Query(default=config.MATCH_RESULT_PAGE_SIZE_DEFAULT, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    limit = min(limit, config.MATCH_RESULT_PAGE_SIZE_MAX)
    try:
        offset = decode_match_cursor(cursor, result_set_id).offset if cursor else 0
    except InvalidMatchCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return _page_payload(user_id, result_set_id, offset=offset, limit=limit)
    except ProfileValidationError as exc:
        raise HTTPException(status_code=500, detail="快照画像无法读取") from exc


@router.delete("/api/match/results/{result_set_id}")
async def remove_match_result(
    result_set_id: str,
    user_id: int = Depends(get_current_user_id),
):
    snapshot = get_match_run(result_set_id, user_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    try:
        MatchResultStore().delete(user_id, result_set_id)
    except MatchResultStoreUnavailable:
        pass
    delete_match_run(result_set_id, user_id)
    return {"ok": True}


@router.post("/api/match/results/{result_set_id}/refresh")
async def refresh_match_result(
    result_set_id: str,
    user_id: int = Depends(get_current_user_id),
):
    snapshot = get_match_run(result_set_id, user_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    try:
        return execute_match(snapshot.profile, owner_user_id=user_id, log=True)
    except ProfileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except V2RankerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def invoke_match_endpoint(
    app,
    authorization: str,
    profile: dict[str, Any],
    top_k: int = 0,
    page_size: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """调用 POST /api/match。默认走本进程 ASGI；MATCH_API_URL 指向外部服务时改打 HTTP。"""
    import config

    body = {"profile": profile, "top_k": top_k}
    if page_size is not None:
        body["page_size"] = page_size
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    url = (getattr(config, "MATCH_API_URL", "") or "").strip()
    timeout = httpx.Timeout(60.0)
    if url:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(url, json=body, headers=headers)
    else:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://jzk.internal",
            timeout=timeout,
        ) as client:
            res = await client.post("/api/match", json=body, headers=headers)
    try:
        data = res.json()
    except Exception:
        data = {"detail": res.text}
    if not isinstance(data, dict):
        data = {"detail": data}
    return res.status_code, data
