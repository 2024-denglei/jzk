"""临时对话会话存储：测试用内存实现与生产 Redis 实现。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Protocol

import redis
from redis.exceptions import RedisError

import config
from redis_client import get_redis_client

if TYPE_CHECKING:
    from dialogue.session import SessionContext


class SessionStoreError(RuntimeError):
    pass


class SessionStoreUnavailable(SessionStoreError):
    pass


class SessionConflict(SessionStoreError):
    pass


class SessionLimitExceeded(SessionStoreError):
    pass


class SessionTooLarge(SessionStoreError):
    pass


class SessionStore(Protocol):
    def load(self, user_id: int, session_id: str) -> SessionContext | None: ...

    def save(self, session: SessionContext) -> None: ...

    def delete(self, user_id: int, session_id: str) -> None: ...

    def cleanup_expired(self) -> None: ...


class InMemorySessionStore:
    def __init__(self):
        self.sessions: dict[tuple[int, str], SessionContext] = {}

    @staticmethod
    def _key(user_id: int, session_id: str) -> tuple[int, str]:
        return user_id, session_id

    def load(self, user_id: int, session_id: str) -> SessionContext | None:
        return self.sessions.get(self._key(user_id, session_id))

    def save(self, session: SessionContext) -> None:
        self.sessions[self._key(session.owner_user_id, session.session_id)] = session

    def delete(self, user_id: int, session_id: str) -> None:
        self.sessions.pop(self._key(user_id, session_id), None)

    def cleanup_expired(self) -> None:
        expired = [key for key, session in self.sessions.items() if session.is_expired()]
        for key in expired:
            self.sessions.pop(key, None)


class RedisSessionStore:
    _SAVE_SCRIPT = """
        local current = redis.call('GET', KEYS[1])
        local version = 0
        if current then
            local decoded = cjson.decode(current)
            version = tonumber(decoded['storage_version'] or 0)
        end
        if version ~= tonumber(ARGV[1]) then return 0 end
        redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[5])
        if not current and redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then
            return -1
        end
        redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
        redis.call('ZADD', KEYS[2], tonumber(ARGV[5]) + tonumber(ARGV[3]), KEYS[1])
        redis.call('EXPIRE', KEYS[2], ARGV[3])
        return 1
    """

    def __init__(self, client: redis.Redis | None = None):
        self.client = client or get_redis_client()
        self.ttl_seconds = config.SESSION_TIMEOUT_MINUTES * 60

    @staticmethod
    def _key(user_id: int, session_id: str) -> str:
        return f"jzk:chat-session:{user_id}:{session_id}"

    @staticmethod
    def _index_key(user_id: int) -> str:
        return f"jzk:chat-session-index:{user_id}"

    def load(self, user_id: int, session_id: str) -> SessionContext | None:
        from dialogue.session import SessionContext

        try:
            raw = self.client.get(self._key(user_id, session_id))
        except RedisError as exc:
            raise SessionStoreUnavailable("临时会话服务暂时不可用") from exc
        if not raw:
            return None
        try:
            session = SessionContext.from_storage_dict(json.loads(raw))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SessionStoreUnavailable("临时会话数据损坏") from exc
        if session.owner_user_id != user_id or session.session_id != session_id:
            raise SessionStoreUnavailable("临时会话所有权数据不一致")
        return session

    def save(self, session: SessionContext) -> None:
        expected_version = session.storage_version
        next_version = expected_version + 1
        payload = session.to_storage_dict()
        payload["storage_version"] = next_version
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > config.SESSION_MAX_BYTES:
            raise SessionTooLarge("临时会话数据超过允许大小")
        try:
            saved = self.client.eval(
                self._SAVE_SCRIPT,
                2,
                self._key(session.owner_user_id, session.session_id),
                self._index_key(session.owner_user_id),
                expected_version,
                raw,
                self.ttl_seconds,
                config.SESSION_MAX_ACTIVE_PER_USER,
                int(time.time()),
            )
        except RedisError as exc:
            raise SessionStoreUnavailable("临时会话服务暂时不可用") from exc
        if int(saved) == -1:
            raise SessionLimitExceeded("活跃临时会话数量已达上限")
        if int(saved) != 1:
            raise SessionConflict("会话已被另一请求更新，请重试")
        session.storage_version = next_version

    def delete(self, user_id: int, session_id: str) -> None:
        try:
            key = self._key(user_id, session_id)
            self.client.delete(key)
            self.client.zrem(self._index_key(user_id), key)
        except RedisError as exc:
            raise SessionStoreUnavailable("临时会话服务暂时不可用") from exc

    def cleanup_expired(self) -> None:
        # Redis TTL 自动清理，避免在线请求执行全库扫描。
        return None


def create_session_store() -> SessionStore:
    if config.CHAT_SESSION_STORE == "redis":
        return RedisSessionStore()
    if config.CHAT_SESSION_STORE == "memory":
        return InMemorySessionStore()
    raise ValueError("CHAT_SESSION_STORE 仅支持 redis 或 memory")
