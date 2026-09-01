"""对话持久化辅助。"""

from __future__ import annotations

import json
from typing import Any

from db.database import db_session


class LegacyChatWriteBlocked(RuntimeError):
    """兼容发布识别到 V2 会话后，禁止旧 JSON 写路径覆盖它。"""


def upsert_user_chat(
    user_id: int,
    session_id: str,
    messages: list[dict[str, Any]],
    candidates: list[dict] | None = None,
    state: dict | None = None,
    title: str | None = None,
) -> int:
    """按 user_id + session_id upsert 对话，返回 chat id。"""
    if not title:
        title = "对话"
        first_user = next((m for m in messages if m.get("role") == "user"), None)
        if first_user and first_user.get("content"):
            title = str(first_user["content"])[:40]

    slim_messages = []
    for m in messages[-40:]:
        item = {
            "role": m.get("role"),
            "content": m.get("content") or "",
        }
        cands = m.get("candidates")
        if isinstance(cands, list) and cands:
            item["candidates"] = cands[:20]
        for key in (
            "candidates_total", "prefer_hits", "match_result_id", "match_next_cursor"
        ):
            if m.get(key) is not None:
                item[key] = m.get(key)
        slim_messages.append(item)

    msgs = json.dumps(slim_messages, ensure_ascii=False)
    cands_json = json.dumps(list(candidates or [])[:20], ensure_ascii=False)
    state_json = json.dumps(state or {}, ensure_ascii=False)

    with db_session() as conn:
        existing = conn.execute(
            """
            SELECT id, state_json, storage_version FROM app.chats
            WHERE user_id = %s AND session_id = %s
            """,
            (user_id, session_id),
        ).fetchone()
        if existing:
            if int(existing.get("storage_version") or 1) == 2:
                raise LegacyChatWriteBlocked("该会话已升级为分支存储，旧接口禁止覆盖")
            if not state:
                state_json = existing.get("state_json") or "{}"
            conn.execute(
                """
                UPDATE app.chats
                SET title = %s, messages_json = %s, candidates_json = %s,
                    state_json = %s, updated_at = now()
                WHERE id = %s
                """,
                (title, msgs, cands_json, state_json, existing["id"]),
            )
            return int(existing["id"])
        row = conn.execute(
            """
            INSERT INTO app.chats
                (user_id, session_id, title, messages_json, candidates_json, state_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, session_id, title, msgs, cands_json, state_json),
        ).fetchone()
        return int(row["id"])
