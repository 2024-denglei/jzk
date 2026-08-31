"""基于 Redis 的手机验证码存取服务。"""

from __future__ import annotations

import secrets
from hmac import compare_digest

import redis
from redis.exceptions import RedisError

import config


class VerificationCodeError(RuntimeError):
    """验证码服务不可用或请求过于频繁。"""


class VerificationCodeRateLimitError(VerificationCodeError):
    """验证码仍处于发送冷却期。"""


class VerificationCodeStore:
    _VERIFY_SCRIPT = """
        local stored = redis.call('GET', KEYS[1])
        if not stored or stored ~= ARGV[1] then
            return 0
        end
        redis.call('DEL', KEYS[1])
        return 1
    """

    def __init__(self, client: redis.Redis | None = None):
        self.client = client or redis.Redis.from_url(
            config.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    @staticmethod
    def _code_key(purpose: str, phone: str) -> str:
        return f"jzk:auth:code:{purpose}:{phone}"

    @staticmethod
    def _cooldown_key(purpose: str, phone: str) -> str:
        return f"jzk:auth:cooldown:{purpose}:{phone}"

    def issue(self, purpose: str, phone: str) -> tuple[str, int]:
        """生成并保存验证码，返回验证码和有效秒数。"""
        cooldown_key = self._cooldown_key(purpose, phone)
        code_key = self._code_key(purpose, phone)
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            acquired = self.client.set(
                cooldown_key,
                "1",
                ex=config.VERIFICATION_CODE_COOLDOWN_SECONDS,
                nx=True,
            )
            if not acquired:
                retry_after = max(int(self.client.ttl(cooldown_key)), 1)
                raise VerificationCodeRateLimitError(f"请求过于频繁，请在 {retry_after} 秒后重试")
            self.client.set(code_key, code, ex=config.VERIFICATION_CODE_TTL_SECONDS)
        except VerificationCodeError:
            raise
        except RedisError as exc:
            raise VerificationCodeError("验证码服务暂时不可用") from exc
        return code, config.VERIFICATION_CODE_TTL_SECONDS

    def verify_and_consume(self, purpose: str, phone: str, code: str) -> bool:
        """校验验证码；成功后立即删除，保证验证码只能使用一次。"""
        key = self._code_key(purpose, phone)
        try:
            # Lua 在 Redis 内原子完成比较和删除，避免并发请求重复使用验证码。
            result = self.client.eval(self._VERIFY_SCRIPT, 1, key, code)
            return compare_digest(str(result), "1")
        except RedisError as exc:
            raise VerificationCodeError("验证码服务暂时不可用") from exc


verification_codes = VerificationCodeStore()
