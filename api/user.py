"""用户收藏 / 历史 / 偏好 / 对话 API。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
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


class ChatSaveBody(BaseModel):
    session_id: str | None = None
    title: str = "对话"
    messages: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    state: dict = Field(default_factory=dict)


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


@router.get("/chats")
async def list_chats(user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, title, updated_at FROM app.chats
            WHERE user_id = %s ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "title": r["title"],
                "updated_at": _ts(r["updated_at"]),
            }
            for r in rows
        ]
    }


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: int, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM app.chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="对话不存在")
    state = json.loads(row["state_json"] or "{}")
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "messages": json.loads(row["messages_json"] or "[]"),
        "candidates": json.loads(row["candidates_json"] or "[]"),
        "state": state,
        "updated_at": _ts(row["updated_at"]),
    }


@router.post("/chats")
async def save_chat(body: ChatSaveBody, user_id: int = Depends(get_current_user_id)):
    import uuid
    from api.chat_persist import upsert_user_chat

    session_id = (body.session_id or "").strip() or str(uuid.uuid4())
    chat_id = upsert_user_chat(
        user_id=user_id,
        session_id=session_id,
        messages=body.messages,
        candidates=body.candidates,
        state=body.state,
        title=body.title,
    )
    return {"ok": True, "id": chat_id, "session_id": session_id}


@router.post("/chats/{chat_id}/resume")
async def resume_chat(
    chat_id: int,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    """恢复历史对话到内存会话，便于继续聊。"""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM app.chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="对话不存在")

    state = json.loads(row["state_json"] or "{}")
    messages = json.loads(row["messages_json"] or "[]")
    candidates = json.loads(row["candidates_json"] or "[]")
    session_id = row["session_id"]

    if not state.get("history"):
        state["history"] = [
            {
                "role": "user" if m.get("role") == "user" else "assistant",
                "content": m.get("content") or "",
            }
            for m in messages
            if m.get("role") in ("user", "bot", "assistant") and m.get("content")
        ]

    sm = getattr(request.app.state, "session_manager", None)
    if sm is None:
        raise HTTPException(status_code=503, detail="会话服务未就绪")
    session = sm.restore_session(user_id, session_id, state=state, candidates=candidates)

    return {
        "ok": True,
        "id": row["id"],
        "session_id": session.session_id,
        "title": row["title"],
        "messages": messages,
        "candidates": candidates,
        "state": {
            "parsed_features": session.parsed_features,
            "constraints": session.constraints,
            "dialogue_state": session.state.value,
            "pending_relaxations": session.pending_relaxations,
        },
        "updated_at": _ts(row["updated_at"]),
    }


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: int, user_id: int = Depends(get_current_user_id)):
    with db_session() as conn:
        cur = conn.execute(
            "DELETE FROM app.chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="对话不存在")
    return {"ok": True}
