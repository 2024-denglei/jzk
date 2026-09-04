"""校验后的偏好画像匹配、严格快照与详情分页。"""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from jzk import config
from jzk.api.auth_utils import get_current_user_id
from jzk.matching.cursor import InvalidMatchCursor, decode_match_cursor, encode_match_cursor
from jzk.domain.preference.result_types import MatchResultMeta, MatchSnapshotItem
from jzk.domain.preference.scoring_contract import RankerInputError, RankerUnavailable
from jzk.domain.preference.validate import ProfileValidationError
from jzk.db.donors_repo import get_donor_statuses_by_ids
from jzk.db.match_runs_repo import (
    delete_match_run,
    get_match_run,
    get_match_run_items_page,
    match_run_is_expired,
)
from jzk.chat.match_snapshot_queries import MatchSnapshotNotFound, get_frozen_match_page
from jzk.matching.execute import execute_match

router = APIRouter(tags=["match"])


class MatchRequest(BaseModel):
    profile: dict[str, Any]
    top_k: int = Field(default=0, ge=0)
    page_size: int | None = Field(default=None, ge=1)


@router.get("/api/match/ready")
def match_scoring_readiness():
    """主应用评分依赖 readiness；不加载候选、不访问 donor 数据。"""
    from jzk.domain.preference.ranker_factory import get_scoring_readiness

    try:
        return get_scoring_readiness()
    except (RankerUnavailable, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "MATCH_SCORER_NOT_READY", "message": str(exc)},
        ) from exc


def frozen_match_page_payload(
    owner_user_id: int,
    result_set_id: str,
    *,
    page: int,
    limit: int,
) -> dict[str, Any]:
    try:
        return get_frozen_match_page(
            owner_user_id,
            result_set_id,
            page=page,
            limit=limit,
        )
    except MatchSnapshotNotFound as exc:
        raise HTTPException(status_code=404, detail="完整匹配快照不存在") from exc


@router.post("/api/match")
def match_donors(body: MatchRequest, user_id: int = Depends(get_current_user_id)):
    """提交完整 PreferenceProfile，内部完成过滤与排序。"""
    try:
        return execute_match(
            body.profile,
            top_k=body.top_k,
            page_size=body.page_size,
            owner_user_id=user_id,
            log=True,
        )
    except (ProfileValidationError, RankerInputError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RankerUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _load_snapshot_page(
    owner_user_id: int,
    result_set_id: str,
    *,
    offset: int,
    limit: int,
) -> tuple[MatchResultMeta, list[MatchSnapshotItem]] | None:
    """从 PostgreSQL 完整快照读取严格排名页。"""
    snapshot_page = get_match_run_items_page(
        result_set_id, owner_user_id, offset=offset, limit=limit
    )
    if snapshot_page is None:
        return None
    meta, _refs = snapshot_page
    if match_run_is_expired(meta):
        raise HTTPException(
            status_code=410,
            detail={"code": "MATCH_SNAPSHOT_EXPIRED", "message": "匹配快照已过期"},
        )
    return snapshot_page


def _snapshot_candidate(
    item: MatchSnapshotItem, current_status: str
) -> dict[str, Any]:
    explanation = dict(item.match_explanation or {})
    donor_info = dict(item.donor_snapshot or {})
    donor_info["status_snapshot"] = donor_info.get("status")
    donor_info["status"] = current_status
    return {
        "donor_info": donor_info,
        "score": float(item.score),
        "match_pct": explanation.get("match_pct", round(float(item.score) * 100, 2)),
        "reason": explanation.get("reason", "综合相似度排序"),
        "match_level": explanation.get("match_level", "low"),
        "field_match": explanation.get("field_match") or {},
        "field_scores": explanation.get("field_scores") or [],
        "rank": int(item.rank),
    }


def _page_payload(
    owner_user_id: int,
    result_set_id: str,
    *,
    offset: int,
    limit: int,
    scan_end_offset: int | None = None,
) -> dict[str, Any]:
    """跳过已停用候选并向后补齐当前页，cursor 指向实际扫描位置。"""
    items: list[dict[str, Any]] = []
    scan_offset = offset
    meta: MatchResultMeta | None = None
    while len(items) < limit:
        chunk_size = min(config.MATCH_RESULT_PAGE_SIZE_MAX, max(limit - len(items), 10))
        if scan_end_offset is not None:
            if scan_offset >= scan_end_offset:
                break
            chunk_size = min(chunk_size, scan_end_offset - scan_offset)
        loaded = _load_snapshot_page(
            owner_user_id, result_set_id, offset=scan_offset, limit=chunk_size
        )
        if loaded is None:
            raise HTTPException(status_code=404, detail="匹配结果不存在")
        meta, frozen_items = loaded
        if not frozen_items:
            scan_offset = meta.total
            break
        statuses = get_donor_statuses_by_ids(
            [item.donor_id for item in frozen_items]
        )
        hydrated = [
            _snapshot_candidate(item, "active")
            for item in frozen_items
            if statuses.get(item.donor_id) == "active"
        ]
        selected = hydrated[: limit - len(items)]
        items.extend(selected)
        # 只消费到本页最后实际返回的 rank，避免预取时跳过仍未展示的候选。
        if len(items) >= limit and selected:
            scan_offset = int(selected[-1]["rank"])
        else:
            scan_offset += len(frozen_items)
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
        "model_checkpoint_sha256": meta.model_checkpoint_sha256,
    }


def _resolve_result_offset(
    result_set_id: str,
    *,
    cursor: str | None,
    page: int | None,
    limit: int,
) -> int:
    """页码用于任意跳转；cursor 保留给顺序分页兼容调用方。"""
    if cursor and page is not None:
        raise HTTPException(status_code=400, detail="cursor 与 page 不能同时使用")
    if page is not None:
        return (page - 1) * limit
    try:
        return decode_match_cursor(cursor, result_set_id).offset if cursor else 0
    except InvalidMatchCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/match/results/{result_set_id}")
async def get_match_results(
    result_set_id: str,
    cursor: str | None = None,
    page: int | None = Query(default=None, ge=1, le=1_000_000),
    limit: int = Query(default=config.MATCH_RESULT_PAGE_SIZE_DEFAULT, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    limit = min(limit, config.MATCH_RESULT_PAGE_SIZE_MAX)
    offset = _resolve_result_offset(
        result_set_id, cursor=cursor, page=page, limit=limit
    )
    try:
        payload = _page_payload(
            user_id,
            result_set_id,
            offset=offset,
            limit=limit,
            # 任意页跳转按严格 rank 窗口读取，避免候选停用后与下一页重复。
            scan_end_offset=offset + limit if page is not None else None,
        )
        payload["page"] = page or (offset // limit + 1)
        payload["page_size"] = limit
        return payload
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
    if not delete_match_run(result_set_id, user_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MATCH_SNAPSHOT_REFERENCED",
                "message": "该匹配快照已关联对话消息，将随整个会话保留",
            },
        )
    return {"ok": True}


@router.post("/api/match/results/{result_set_id}/refresh")
def refresh_match_result(
    result_set_id: str,
    user_id: int = Depends(get_current_user_id),
):
    snapshot = get_match_run(result_set_id, user_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    try:
        return execute_match(snapshot.profile, owner_user_id=user_id, log=True)
    except (ProfileValidationError, RankerInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RankerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def invoke_match_endpoint(
    app,
    authorization: str,
    profile: dict[str, Any],
    top_k: int = 0,
    page_size: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """调用 POST /api/match。默认走本进程 ASGI；MATCH_API_URL 指向外部服务时改打 HTTP。"""
    from jzk import config

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
