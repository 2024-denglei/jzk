"""不可篡改的匹配结果分页游标。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import config


class InvalidMatchCursor(ValueError):
    pass


@dataclass(frozen=True)
class MatchCursor:
    result_set_id: str
    offset: int


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def encode_match_cursor(result_set_id: str, offset: int, *, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else int(now)
    payload = json.dumps(
        {"v": 1, "rid": result_set_id, "offset": max(0, int(offset)),
         "exp": issued + config.MATCH_CURSOR_TTL_SECONDS},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    body = _b64encode(payload)
    signature = hmac.new(config.JWT_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + _b64encode(signature)


def decode_match_cursor(token: str, result_set_id: str, *, now: int | None = None) -> MatchCursor:
    try:
        body, encoded_signature = token.split(".", 1)
        signature = _b64decode(encoded_signature)
        expected = hmac.new(
            config.JWT_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidMatchCursor("分页游标签名无效")
        data = json.loads(_b64decode(body))
        current = int(time.time()) if now is None else int(now)
        if data.get("v") != 1 or data.get("rid") != result_set_id:
            raise InvalidMatchCursor("分页游标与结果集不匹配")
        if int(data.get("exp") or 0) < current:
            raise InvalidMatchCursor("分页游标已过期")
        offset = int(data.get("offset"))
        if offset < 0:
            raise InvalidMatchCursor("分页游标偏移无效")
        return MatchCursor(result_set_id=result_set_id, offset=offset)
    except InvalidMatchCursor:
        raise
    except Exception as exc:
        raise InvalidMatchCursor("分页游标格式无效") from exc

