import asyncio

import pytest
from fastapi import HTTPException, Response
from redis.exceptions import RedisError

from jzk.api import admin as admin_api
from jzk.api.rate_limit import RateLimitError, RateLimitUnavailable, RateLimiter


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def eval(self, _script, _num_keys, key, window):
        self.values[key] = self.values.get(key, 0) + 1
        self.ttls.setdefault(key, int(window))
        return [self.values[key], self.ttls[key]]

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)


class _BrokenRedis:
    def eval(self, *_args):
        raise RedisError("down")

    def delete(self, *_args):
        raise RedisError("down")


def test_rate_limit_is_hashed_and_enforced_atomically():
    fake = _FakeRedis()
    limiter = RateLimiter(fake, pepper="p" * 32)

    assert limiter.check("login:account", "user@example.com", 2, 600).count == 1
    assert limiter.check("login:account", "user@example.com", 2, 600).count == 2
    with pytest.raises(RateLimitError) as exc:
        limiter.check("login:account", "user@example.com", 2, 600)
    assert exc.value.retry_after == 600
    assert all("user@example.com" not in key for key in fake.values)


def test_success_reset_clears_account_bucket():
    fake = _FakeRedis()
    limiter = RateLimiter(fake, pepper="p" * 32)
    limiter.check("login:account", "member", 1, 60)
    limiter.reset("login:account", "member")
    assert limiter.check("login:account", "member", 1, 60).count == 1


def test_rate_limit_fails_closed_when_redis_is_unavailable():
    limiter = RateLimiter(_BrokenRedis(), pepper="p" * 32)
    with pytest.raises(RateLimitUnavailable):
        limiter.check("login:ip", "127.0.0.1", 5, 600)
    with pytest.raises(RateLimitUnavailable):
        limiter.reset("login:account", "member")


def test_admin_login_endpoint_blocks_repeated_failures(monkeypatch):
    limiter = RateLimiter(_FakeRedis(), pepper="p" * 32)
    monkeypatch.setattr(admin_api, "rate_limiter", limiter)
    monkeypatch.setattr(admin_api, "authenticate_admin", lambda *_args: None)
    monkeypatch.setattr(admin_api.config, "ADMIN_LOGIN_LIMIT", 2)
    body = admin_api.AdminLoginBody(username="operator", password="wrong-password")

    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_api.admin_login(body, Response(), "127.0.0.1"))
        assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_api.admin_login(body, Response(), "127.0.0.1"))
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == str(admin_api.config.ADMIN_LOGIN_WINDOW_SECONDS)
