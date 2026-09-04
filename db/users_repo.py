"""前台用户账号。"""

from __future__ import annotations

from typing import Any, Literal

from db.pg import db_session, fetchone

LoginField = Literal["email", "phone"]


def get_id_by_phone(phone: str) -> int | None:
    with db_session() as conn:
        row = fetchone(conn, "SELECT id FROM app.users WHERE phone = %s", (phone,))
    return int(row["id"]) if row else None


def find_email_or_phone(email: str, phone: str) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            "SELECT email, phone FROM app.users WHERE email = %s OR phone = %s",
            (email, phone),
        )


def create_user(
    *,
    email: str,
    phone: str,
    password_hash: str,
    nickname: str,
) -> dict[str, Any]:
    with db_session() as conn:
        row = fetchone(
            conn,
            """
            INSERT INTO app.users (email, phone, password_hash, nickname)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (email, phone, password_hash, nickname),
        )
    if row is None:  # pragma: no cover - INSERT RETURNING always yields a row
        raise RuntimeError("创建用户失败")
    return row


def get_by_login_field(field: LoginField, identifier: str) -> dict[str, Any] | None:
    if field not in {"email", "phone"}:
        raise ValueError("登录字段只能是 email 或 phone")
    with db_session() as conn:
        return fetchone(
            conn,
            f"SELECT * FROM app.users WHERE {field} = %s",
            (identifier,),
        )


def get_by_phone(phone: str) -> dict[str, Any] | None:
    return get_by_login_field("phone", phone)


def get_by_id(user_id: int) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(conn, "SELECT * FROM app.users WHERE id = %s", (user_id,))


def get_auth_state(user_id: int) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            "SELECT status, token_version FROM app.users WHERE id = %s",
            (user_id,),
        )


def record_login(user_id: int) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            """
            UPDATE app.users
            SET last_login_at = now(), updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (user_id,),
        )


def update_password(user_id: int, password_hash: str) -> None:
    with db_session() as conn:
        conn.execute(
            """
            UPDATE app.users
            SET password_hash = %s, token_version = token_version + 1, updated_at = now()
            WHERE id = %s
            """,
            (password_hash, user_id),
        )


def bump_token_version(user_id: int) -> None:
    with db_session() as conn:
        conn.execute(
            """
            UPDATE app.users
            SET token_version = token_version + 1, updated_at = now()
            WHERE id = %s
            """,
            (user_id,),
        )


def update_nickname(user_id: int, nickname: str) -> dict[str, Any] | None:
    with db_session() as conn:
        return fetchone(
            conn,
            """
            UPDATE app.users
            SET nickname = %s, updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (nickname, user_id),
        )
