"""Redis Refresh Session：哈希存储、轮换、撤销和重放检测。"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import asdict, dataclass

import redis
from redis.exceptions import RedisError

import config
from redis_client import get_redis_client


class RefreshSessionError(RuntimeError):
    pass


class RefreshSessionUnavailable(RefreshSessionError):
    pass


class InvalidRefreshToken(RefreshSessionError):
    pass


class RefreshTokenReplay(InvalidRefreshToken):
    pass


@dataclass(frozen=True)
class RefreshSession:
    subject_id: int
    kind: str
    token_version: int
    family_id: str


class RefreshSessionStore:
    _CREATE_SCRIPT = """
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        redis.call('SADD', KEYS[2], KEYS[1])
        redis.call('EXPIRE', KEYS[2], ARGV[2])
        redis.call('SADD', KEYS[3], KEYS[1])
        redis.call('EXPIRE', KEYS[3], ARGV[2])
        return 1
    """

    _ROTATE_SCRIPT = """
        if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
        redis.call('DEL', KEYS[1])
        redis.call('SREM', KEYS[4], KEYS[1])
        redis.call('SREM', KEYS[5], KEYS[1])
        redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
        redis.call('SET', KEYS[3], ARGV[2], 'EX', ARGV[3])
        redis.call('SADD', KEYS[4], KEYS[3])
        redis.call('EXPIRE', KEYS[4], ARGV[3])
        redis.call('SADD', KEYS[5], KEYS[3])
        redis.call('EXPIRE', KEYS[5], ARGV[3])
        return 1
    """

    _REVOKE_ALL_SCRIPT = """
        local members = redis.call('SMEMBERS', KEYS[1])
        for _, key in ipairs(members) do redis.call('DEL', key) end
        redis.call('DEL', KEYS[1])
        return #members
    """

    def __init__(self, client: redis.Redis | None = None):
        self.client = client or get_redis_client()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def _session_key(cls, token: str) -> str:
        return f"jzk:refresh:session:{cls._hash(token)}"

    @classmethod
    def _spent_key(cls, token: str) -> str:
        return f"jzk:refresh:spent:{cls._hash(token)}"

    @staticmethod
    def _subject_key(kind: str, subject_id: int) -> str:
        return f"jzk:refresh:subject:{kind}:{subject_id}"

    @staticmethod
    def _family_key(family_id: str) -> str:
        return f"jzk:refresh:family:{family_id}"

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def _loads(raw: str) -> RefreshSession:
        data = json.loads(raw)
        return RefreshSession(
            subject_id=int(data["subject_id"]),
            kind=str(data["kind"]),
            token_version=int(data["token_version"]),
            family_id=str(data["family_id"]),
        )

    def create(self, subject_id: int, kind: str, token_version: int, ttl_seconds: int) -> str:
        token = self._new_token()
        session = RefreshSession(
            subject_id=subject_id,
            kind=kind,
            token_version=token_version,
            family_id=str(uuid.uuid4()),
        )
        raw = json.dumps(asdict(session), separators=(",", ":"))
        try:
            self.client.eval(
                self._CREATE_SCRIPT,
                3,
                self._session_key(token),
                self._subject_key(kind, subject_id),
                self._family_key(session.family_id),
                raw,
                int(ttl_seconds),
            )
        except RedisError as exc:
            raise RefreshSessionUnavailable("登录会话服务暂时不可用") from exc
        return token

    def inspect(self, token: str) -> RefreshSession:
        try:
            raw = self.client.get(self._session_key(token))
            if raw:
                return self._loads(raw)
            replayed_family = self.client.get(self._spent_key(token))
            if replayed_family:
                self.revoke_family(str(replayed_family))
                raise RefreshTokenReplay("检测到刷新凭证重复使用，相关会话已撤销")
        except RefreshSessionError:
            raise
        except (RedisError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RefreshSessionUnavailable("登录会话服务暂时不可用") from exc
        raise InvalidRefreshToken("刷新凭证无效或已过期")

    def rotate(self, token: str, session: RefreshSession, ttl_seconds: int) -> str:
        new_token = self._new_token()
        raw = json.dumps(asdict(session), separators=(",", ":"))
        try:
            result = self.client.eval(
                self._ROTATE_SCRIPT,
                5,
                self._session_key(token),
                self._spent_key(token),
                self._session_key(new_token),
                self._subject_key(session.kind, session.subject_id),
                self._family_key(session.family_id),
                session.family_id,
                raw,
                int(ttl_seconds),
            )
            if int(result) != 1:
                self.revoke_family(session.family_id)
                raise RefreshTokenReplay("检测到刷新凭证并发或重复使用，相关会话已撤销")
        except RefreshSessionError:
            raise
        except RedisError as exc:
            raise RefreshSessionUnavailable("登录会话服务暂时不可用") from exc
        return new_token

    def revoke(self, token: str) -> None:
        try:
            raw = self.client.get(self._session_key(token))
            if not raw:
                return
            session = self._loads(raw)
            key = self._session_key(token)
            self.client.delete(key)
            self.client.srem(self._subject_key(session.kind, session.subject_id), key)
            self.client.srem(self._family_key(session.family_id), key)
        except (RedisError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RefreshSessionUnavailable("登录会话服务暂时不可用") from exc

    def revoke_all(self, kind: str, subject_id: int) -> int:
        try:
            return int(
                self.client.eval(
                    self._REVOKE_ALL_SCRIPT,
                    1,
                    self._subject_key(kind, subject_id),
                )
            )
        except RedisError as exc:
            raise RefreshSessionUnavailable("登录会话服务暂时不可用") from exc

    def revoke_family(self, family_id: str) -> int:
        try:
            return int(
                self.client.eval(
                    self._REVOKE_ALL_SCRIPT,
                    1,
                    self._family_key(family_id),
                )
            )
        except RedisError as exc:
            raise RefreshSessionUnavailable("登录会话服务暂时不可用") from exc


refresh_sessions = RefreshSessionStore()
