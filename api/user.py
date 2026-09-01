"""用户收藏 / 历史 / 偏好 / 对话 API。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_utils import get_current_user_id
from db.database import db_session

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
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT donor_code, created_at FROM app.favorites
            WHERE user_id = %s ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
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
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app.favorites (user_id, donor_code)
            VALUES (%s, %s)
            ON CONFLICT (user_id, donor_code) DO NOTHING
            """,
            (user_id, code),
        )
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
    with db_session() as conn:
        conn.execute(
            "DELETE FROM app.favorites WHERE user_id = %s AND donor_code = %s",
            (user_id, donor_code),
        )
    return {"ok": True}

@router.get("/favorites/{donor_code}")
async def is_favorite(donor_code: str, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM app.favorites WHERE user_id = %s AND donor_code = %s",
            (user_id, donor_code),
        ).fetchone()
    return {"favorited": bool(row)}


@router.get("/history")
async def list_history(kind: str | None = None, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        if kind:
            rows = conn.execute(
                """
                SELECT * FROM app.history
                WHERE user_id = %s AND kind = %s
                ORDER BY created_at DESC LIMIT 100
                """,
                (user_id, kind),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM app.history
                WHERE user_id = %s
                ORDER BY created_at DESC LIMIT 100
                """,
                (user_id,),
            ).fetchall()
    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "donor_code": r["donor_code"],
                "payload": json.loads(r["payload"]) if r["payload"] else None,
                "created_at": _ts(r["created_at"]),
            }
        )
    return {"items": items}


@router.post("/history")
async def add_history(body: HistoryBody, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app.history (user_id, kind, donor_code, payload)
            VALUES (%s, %s, %s, %s)
            """,
            (
                user_id,
                body.kind,
                body.donor_code,
                json.dumps(body.payload, ensure_ascii=False) if body.payload else None,
            ),
        )
    return {"ok": True}


@router.get("/preferences")
async def get_preferences(user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM app.preferences WHERE user_id = %s", (user_id,)
        ).fetchone()
    if not row:
        return {"filters": {}, "priority": []}
    return {
        "filters": json.loads(row["filters_json"] or "{}"),
        "priority": json.loads(row["priority_json"] or "[]"),
    }


@router.post("/preferences")
async def save_preferences(body: PreferencesBody, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app.preferences (user_id, filters_json, priority_json, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (user_id) DO UPDATE SET
                filters_json = EXCLUDED.filters_json,
                priority_json = EXCLUDED.priority_json,
                updated_at = now()
            """,
            (
                user_id,
                json.dumps(body.filters, ensure_ascii=False),
                json.dumps(body.priority, ensure_ascii=False),
            ),
        )
    return {"ok": True}
