"""前台用户的收藏、浏览历史与筛选偏好。"""

from __future__ import annotations

import json
from typing import Any

from db.pg import db_session, fetchall, fetchone


def list_favorites(user_id: int) -> list[dict[str, Any]]:
    with db_session() as conn:
        return fetchall(
            conn,
            """
            SELECT donor_code, created_at FROM app.favorites
            WHERE user_id = %s ORDER BY created_at DESC
            """,
            (user_id,),
        )


def add_favorite(user_id: int, donor_code: str) -> None:
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app.favorites (user_id, donor_code)
            VALUES (%s, %s)
            ON CONFLICT (user_id, donor_code) DO NOTHING
            """,
            (user_id, donor_code),
        )


def remove_favorite(user_id: int, donor_code: str) -> None:
    with db_session() as conn:
        conn.execute(
            "DELETE FROM app.favorites WHERE user_id = %s AND donor_code = %s",
            (user_id, donor_code),
        )


def has_favorite(user_id: int, donor_code: str) -> bool:
    with db_session() as conn:
        row = fetchone(
            conn,
            "SELECT id FROM app.favorites WHERE user_id = %s AND donor_code = %s",
            (user_id, donor_code),
        )
    return bool(row)


def list_history(user_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    with db_session() as conn:
        if kind:
            return fetchall(
                conn,
                """
                SELECT * FROM app.history
                WHERE user_id = %s AND kind = %s
                ORDER BY created_at DESC LIMIT 100
                """,
                (user_id, kind),
            )
        return fetchall(
            conn,
            """
            SELECT * FROM app.history
            WHERE user_id = %s
            ORDER BY created_at DESC LIMIT 100
            """,
            (user_id,),
        )


def add_history(
    user_id: int,
    *,
    kind: str,
    donor_code: str | None,
    payload: dict | None,
) -> None:
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app.history (user_id, kind, donor_code, payload)
            VALUES (%s, %s, %s, %s)
            """,
            (
                user_id,
                kind,
                donor_code,
                json.dumps(payload, ensure_ascii=False) if payload else None,
            ),
        )


def get_preferences(user_id: int) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            "SELECT * FROM app.preferences WHERE user_id = %s",
            (user_id,),
        )


def save_preferences(user_id: int, *, filters: dict, priority: list) -> None:
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
                json.dumps(filters, ensure_ascii=False),
                json.dumps(priority, ensure_ascii=False),
            ),
        )
