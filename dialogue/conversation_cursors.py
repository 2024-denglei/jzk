"""绑定用户和资源的签名会话游标。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any
from uuid import UUID

import config


class InvalidConversationCursor(ValueError):
    pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _encode(payload: dict[str, Any], *, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else int(now)
    body_data = {
        "v": 1,
        "exp": issued + config.CHAT_CURSOR_TTL_SECONDS,
        **payload,
    }
    raw = json.dumps(body_data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64encode(raw)
    signature = hmac.new(
        config.JWT_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{body}.{_b64encode(signature)}"


def _decode(token: str, *, now: int | None = None) -> dict[str, Any]:
    try:
        body, encoded_signature = token.split(".", 1)
        signature = _b64decode(encoded_signature)
        expected = hmac.new(
            config.JWT_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidConversationCursor("分页游标签名无效")
        data = json.loads(_b64decode(body))
        current = int(time.time()) if now is None else int(now)
        if data.get("v") != 1 or int(data.get("exp") or 0) < current:
            raise InvalidConversationCursor("分页游标已过期或版本无效")
        return data
    except InvalidConversationCursor:
        raise
    except Exception as exc:
        raise InvalidConversationCursor("分页游标格式无效") from exc


def encode_chat_list_cursor(
    user_id: int,
    updated_at: datetime,
    chat_id: int,
    *,
    now: int | None = None,
) -> str:
    return _encode(
        {
            "kind": "chat_list",
            "uid": int(user_id),
            "updated_at": updated_at.isoformat(),
            "chat_id": int(chat_id),
        },
        now=now,
    )


def decode_chat_list_cursor(
    token: str,
    user_id: int,
    *,
    now: int | None = None,
) -> tuple[datetime, int]:
    data = _decode(token, now=now)
    if data.get("kind") != "chat_list" or int(data.get("uid", -1)) != int(user_id):
        raise InvalidConversationCursor("会话列表游标与当前用户不匹配")
    try:
        return datetime.fromisoformat(str(data["updated_at"])), int(data["chat_id"])
    except Exception as exc:
        raise InvalidConversationCursor("会话列表游标内容无效") from exc


def encode_message_cursor(
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    before_message_id: UUID,
    *,
    now: int | None = None,
) -> str:
    return _encode(
        {
            "kind": "message_path",
            "uid": int(user_id),
            "chat_id": int(chat_id),
            "branch_id": str(branch_id),
            "before": str(before_message_id),
        },
        now=now,
    )


def decode_message_cursor(
    token: str,
    user_id: int,
    chat_id: int,
    branch_id: UUID,
    *,
    now: int | None = None,
) -> UUID:
    data = _decode(token, now=now)
    if (
        data.get("kind") != "message_path"
        or int(data.get("uid", -1)) != int(user_id)
        or int(data.get("chat_id", -1)) != int(chat_id)
        or str(data.get("branch_id")) != str(branch_id)
    ):
        raise InvalidConversationCursor("消息游标与当前用户、会话或分支不匹配")
    try:
        return UUID(str(data["before"]))
    except Exception as exc:
        raise InvalidConversationCursor("消息游标内容无效") from exc
