"""基于 Redis 的手机验证码存取服务。"""

from __future__ import annotations

import secrets
import hashlib
import hmac

import redis
from redis.exceptions import RedisError

from jzk import config
from jzk.redis_client import get_redis_client


class VerificationCodeError(RuntimeError):
    """验证码服务不可用或请求过于频繁。"""


class VerificationCodeRateLimitError(VerificationCodeError):
    """验证码仍处于发送冷却期。"""


class VerificationCodeStore:
    _ISSUE_SCRIPT = """
        if redis.call('EXISTS', KEYS[1]) == 1 then
            local ttl = redis.call('TTL', KEYS[1])
            if ttl < 1 then ttl = tonumber(ARGV[2]) end
            return {0, ttl}
        end
        redis.call('SET', KEYS[1], '1', 'EX', ARGV[2])
        redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
        redis.call('DEL', KEYS[3])
        return {1, tonumber(ARGV[3])}
    """

    _VERIFY_SCRIPT = """
        local stored = redis.call('GET', KEYS[1])
        if not stored then
            return -1
        end
        if stored ~= ARGV[1] then
            local attempts = redis.call('INCR', KEYS[2])
            if attempts == 1 then
                redis.call('EXPIRE', KEYS[2], ARGV[3])
            end
            if attempts >= tonumber(ARGV[2]) then
                redis.call('DEL', KEYS[1])
                redis.call('DEL', KEYS[2])
                return -2
            end
            return 0
        end
        redis.call('DEL', KEYS[1])
        redis.call('DEL', KEYS[2])
        return 1
    """

    def __init__(self, client: redis.Redis | None = None):
        self.client = client or get_redis_client()

    @staticmethod
    def _phone_key(phone: str) -> str:
        return hmac.new(
            config.RATE_LIMIT_PEPPER.encode("utf-8"),
            phone.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @classmethod
    def _code_key(cls, purpose: str, phone: str) -> str:
        return f"jzk:auth:code:{purpose}:{cls._phone_key(phone)}"

    @classmethod
    def _cooldown_key(cls, purpose: str, phone: str) -> str:
        return f"jzk:auth:cooldown:{purpose}:{cls._phone_key(phone)}"

    @classmethod
    def _attempts_key(cls, purpose: str, phone: str) -> str:
        return f"jzk:auth:attempts:{purpose}:{cls._phone_key(phone)}"

    def issue(self, purpose: str, phone: str) -> tuple[str, int]:
        """生成并保存验证码，返回验证码和有效秒数。"""
        cooldown_key = self._cooldown_key(purpose, phone)
        code_key = self._code_key(purpose, phone)
        attempts_key = self._attempts_key(purpose, phone)
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            acquired, retry_after = self.client.eval(
                self._ISSUE_SCRIPT,
                3,
                cooldown_key,
                code_key,
                attempts_key,
                code,
                config.VERIFICATION_CODE_COOLDOWN_SECONDS,
                config.VERIFICATION_CODE_TTL_SECONDS,
            )
            if int(acquired) != 1:
                raise VerificationCodeRateLimitError(
                    f"请求过于频繁，请在 {max(int(retry_after), 1)} 秒后重试"
                )
        except VerificationCodeError:
            raise
        except RedisError as exc:
            raise VerificationCodeError("验证码服务暂时不可用") from exc
        return code, config.VERIFICATION_CODE_TTL_SECONDS

    def verify_and_consume(self, purpose: str, phone: str, code: str) -> bool:
        """校验验证码；成功后立即删除，保证验证码只能使用一次。"""
        key = self._code_key(purpose, phone)
        attempts_key = self._attempts_key(purpose, phone)
        try:
            result = int(
                self.client.eval(
                    self._VERIFY_SCRIPT,
                    2,
                    key,
                    attempts_key,
                    code,
                    config.VERIFICATION_CODE_MAX_ATTEMPTS,
                    config.VERIFICATION_CODE_TTL_SECONDS,
                )
            )
            if result == -2:
                raise VerificationCodeRateLimitError("验证码错误次数过多，请重新获取")
            return result == 1
        except VerificationCodeError:
            raise
        except RedisError as exc:
            raise VerificationCodeError("验证码服务暂时不可用") from exc


verification_codes = VerificationCodeStore()
