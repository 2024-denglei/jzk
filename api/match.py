"""校验后的偏好画像匹配：must 过滤 + 打分排序。"""

from typing import Any
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_utils import get_current_user_id
from core.preference.pipeline import match_profile
from core.preference.validate import ProfileValidationError, parse_profile
from core.preference.v2_ranker import V2RankerUnavailable

router = APIRouter(tags=["match"])


class MatchRequest(BaseModel):
    profile: dict[str, Any]
    top_k: int = Field(default=0, ge=0)


def execute_match(raw_profile: dict[str, Any], top_k: int = 0, **match_kwargs) -> dict[str, Any]:
    """匹配层实现：校验画像后过滤+排序。HTTP 与对话共用。"""
    t0 = time.perf_counter()
    profile = parse_profile(raw_profile)
    parse_ms = (time.perf_counter() - t0) * 1000
    result = match_profile(profile, **match_kwargs)
    candidates = result.candidates
    slice_ms = 0.0
    if top_k > 0:
        t1 = time.perf_counter()
        candidates = candidates[:top_k]
        slice_ms = (time.perf_counter() - t1) * 1000
    timings = dict(result.timings or {})
    timings["parse_profile_ms"] = round(parse_ms, 1)
    if top_k > 0:
        timings["top_k_slice_ms"] = round(slice_ms, 1)
    return {
        "ok": True,
        "skipped": result.skipped,
        "match_level": result.match_level,
        "filtered_count": result.filtered_count,
        "bottlenecks": result.bottlenecks,
        "candidates": candidates,
        "timings": timings,
        "prefer_hits": list(result.prefer_hits or []),
    }


@router.post("/api/match")
async def match_donors(body: MatchRequest, _user_id: int = Depends(get_current_user_id)):
    """提交完整 PreferenceProfile，内部完成过滤与排序。"""
    try:
        return execute_match(body.profile, top_k=body.top_k, log=True)
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except V2RankerUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


async def invoke_match_endpoint(
    app,
    authorization: str,
    profile: dict[str, Any],
    top_k: int = 0,
) -> tuple[int, dict[str, Any]]:
    """调用 POST /api/match。默认走本进程 ASGI；MATCH_API_URL 指向外部服务时改打 HTTP。"""
    import config

    body = {"profile": profile, "top_k": top_k}
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
