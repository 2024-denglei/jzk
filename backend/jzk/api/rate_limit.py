"""基于 Redis 的隐私友好型原子限流。"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import redis
from fastapi import Request
from redis.exceptions import RedisError

from jzk import config
from jzk.redis_client import get_redis_client


class RateLimitError(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__(f"请求过于频繁，请在 {retry_after} 秒后重试")
        self.retry_after = retry_after


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitResult:
    count: int
    retry_after: int


class RateLimiter:
    _HIT_SCRIPT = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
        end
        local ttl = redis.call('TTL', KEYS[1])
        if ttl < 1 then ttl = tonumber(ARGV[1]) end
        return {count, ttl}
    """

    def __init__(self, client: redis.Redis | None = None, pepper: str | None = None):
        self.client = client or get_redis_client()
        self.pepper = (pepper or config.RATE_LIMIT_PEPPER).encode("utf-8")

    def _key(self, bucket: str, subject: str) -> str:
        digest = hmac.new(self.pepper, subject.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"jzk:rate:{bucket}:{digest}"

    def check(self, bucket: str, subject: str, limit: int, window_seconds: int) -> RateLimitResult:
        try:
            count, ttl = self.client.eval(
                self._HIT_SCRIPT,
                1,
                self._key(bucket, subject),
                int(window_seconds),
            )
        except RedisError as exc:
            raise RateLimitUnavailable("安全限流服务暂时不可用") from exc

        result = RateLimitResult(count=int(count), retry_after=max(int(ttl), 1))
        if result.count > limit:
            raise RateLimitError(result.retry_after)
        return result

    def reset(self, bucket: str, subject: str) -> None:
        try:
            self.client.delete(self._key(bucket, subject))
        except RedisError as exc:
            raise RateLimitUnavailable("安全限流服务暂时不可用") from exc


def get_client_ip(request: Request) -> str:
    """只使用 ASGI 已解析的对端地址，避免直接信任伪造的转发头。"""
    return request.client.host if request.client else "unknown"


rate_limiter = RateLimiter()
