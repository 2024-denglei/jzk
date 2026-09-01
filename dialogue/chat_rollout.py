"""分支化对话写流量的稳定用户灰度。"""

from __future__ import annotations

import hashlib

import config


def rollout_bucket(user_id: int, *, salt: str | None = None) -> int:
    """返回稳定的 0..9999 桶；同一 salt 下发布重启不会换组。"""
    material = f"{salt or config.CHAT_STORAGE_V2_ROLLOUT_SALT}:{int(user_id)}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 10_000


def user_can_write_v2(user_id: int) -> bool:
    if not config.CHAT_STORAGE_V2_WRITE_ENABLED:
        return False
    if int(user_id) in config.CHAT_STORAGE_V2_WRITE_USER_IDS:
        return True
    percent = int(config.CHAT_STORAGE_V2_WRITE_PERCENT)
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return rollout_bucket(user_id) < percent * 100
