"""用户收藏 / 历史 / 偏好 / 对话 API。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_utils import get_current_user_id
from db import user_records_repo

router = APIRouter(prefix="/api/user", tags=["user"])


def _ts(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


class FavoriteBody(BaseModel):
    donor_code: str


class HistoryBody(BaseModel):
    kind: str = Field(description="browse | search | match")
    donor_code: str | None = None
    payload: dict | None = None


class PreferencesBody(BaseModel):
    filters: dict = Field(default_factory=dict)
    priority: list[str] = Field(default_factory=list)


@router.get("/favorites")
async def list_favorites(user_id: int = Depends(get_current_user_id)):
    rows = user_records_repo.list_favorites(user_id)
    return {
        "items": [
            {"donor_code": r["donor_code"], "created_at": _ts(r["created_at"])}
            for r in rows
        ]
    }


@router.post("/favorites")
async def add_favorite(body: FavoriteBody, user_id: int = Depends(get_current_user_id)):
    code = body.donor_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少代号")
    user_records_repo.add_favorite(user_id, code)
    try:
        from core.preference.match_log import append_feedback_event

        append_feedback_event({
            "session_id": "",
            "user_id": user_id,
            "donor_code": code,
            "event": "favorite",
        })
    except Exception:
        pass
    return {"ok": True, "donor_code": code}


@router.delete("/favorites/{donor_code}")
async def remove_favorite(donor_code: str, user_id: int = Depends(get_current_user_id)):
    user_records_repo.remove_favorite(user_id, donor_code)
    return {"ok": True}

@router.get("/favorites/{donor_code}")
async def is_favorite(donor_code: str, user_id: int = Depends(get_current_user_id)):
    return {"favorited": user_records_repo.has_favorite(user_id, donor_code)}


@router.get("/history")
async def list_history(kind: str | None = None, user_id: int = Depends(get_current_user_id)):
    rows = user_records_repo.list_history(user_id, kind)
    items = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload) if payload else None
        items.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "donor_code": r["donor_code"],
                "payload": payload,
                "created_at": _ts(r["created_at"]),
            }
        )
    return {"items": items}


@router.post("/history")
async def add_history(body: HistoryBody, user_id: int = Depends(get_current_user_id)):
    user_records_repo.add_history(
        user_id,
        kind=body.kind,
        donor_code=body.donor_code,
        payload=body.payload,
    )
    return {"ok": True}


@router.get("/preferences")
async def get_preferences(user_id: int = Depends(get_current_user_id)):
    row = user_records_repo.get_preferences(user_id)
    if not row:
        return {"filters": {}, "priority": []}
    filters = row["filters_json"] or "{}"
    priority = row["priority_json"] or "[]"
    if isinstance(filters, str):
        filters = json.loads(filters)
    if isinstance(priority, str):
        priority = json.loads(priority)
    return {"filters": filters, "priority": priority}


@router.post("/preferences")
async def save_preferences(body: PreferencesBody, user_id: int = Depends(get_current_user_id)):
    user_records_repo.save_preferences(
        user_id, filters=body.filters, priority=body.priority
    )
    return {"ok": True}
