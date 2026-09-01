"""Redis 在线匹配结果集；PostgreSQL 快照仍是排名权威来源。"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable

import redis
from redis.exceptions import RedisError

import config
from core.preference.result_types import MatchResultMeta, RankedCandidateRef
from redis_client import get_redis_client


class MatchResultStoreUnavailable(RuntimeError):
    pass


class MatchResultTooLarge(ValueError):
    pass


class MatchResultStore:
    def __init__(self, client: redis.Redis | None = None):
        self.client = client or get_redis_client()

    @staticmethod
    def _keys(result_set_id: str) -> tuple[str, str, str]:
        tag = "{" + result_set_id + "}"
        base = f"jzk:match-result:{tag}"
        return f"{base}:meta", f"{base}:items", f"{base}:members"

    @staticmethod
    def _index_key(owner_user_id: int) -> str:
        return f"jzk:match-result-subject:{owner_user_id}"

    def create(self, meta: MatchResultMeta, refs: Iterable[RankedCandidateRef]) -> MatchResultMeta:
        items = list(refs)
        if len(items) != meta.total:
            raise ValueError("total 与排名引用数量不一致")
        if len(items) > config.MATCH_RESULT_MAX_CANDIDATES:
            raise MatchResultTooLarge("匹配候选数量超过允许上限")
        now = time.time()
        created_at = meta.created_at.timestamp() if meta.created_at else now
        expires = min(
            now + config.MATCH_RESULT_TTL_SECONDS,
            created_at + config.MATCH_RESULT_MAX_LIFETIME_SECONDS,
        )
        ttl_seconds = max(0, int(expires - now))
        if ttl_seconds <= 0:
            # 严格快照仍可直接分页，但不再把超过绝对寿命的结果放回 Redis。
            return replace(meta, expires_at=datetime.fromtimestamp(int(expires), timezone.utc))
        meta_key, items_key, members_key = self._keys(meta.result_set_id)
        index_key = self._index_key(meta.owner_user_id)
        meta_values = {
            "layout_version": "2",
            "owner_user_id": str(meta.owner_user_id),
            "total": str(meta.total),
            "profile_json": json.dumps(meta.profile, ensure_ascii=False, separators=(",", ":")),
            "profile_hash": meta.profile_hash,
            "model_version": meta.model_version,
            "dataset_version": meta.dataset_version,
            "prefer_hits": json.dumps(meta.prefer_hits, ensure_ascii=False, separators=(",", ":")),
            "created_at": str(int(now)),
            "expires_at": str(int(expires)),
        }
        packed_items = [f"{item.donor_id}:{float(item.score):.6f}" for item in items]
        member_ids = [str(item.donor_id) for item in items]
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.delete(meta_key, items_key, members_key)
            pipe.hset(meta_key, mapping=meta_values)
            if packed_items:
                # LIST 的物理顺序就是严格 rank；SET 只负责 O(1) 成员校验。
                pipe.rpush(items_key, *packed_items)
                pipe.sadd(members_key, *member_ids)
            pipe.expire(meta_key, ttl_seconds)
            pipe.expire(items_key, ttl_seconds)
            pipe.expire(members_key, ttl_seconds)
            pipe.zremrangebyscore(index_key, "-inf", now)
            pipe.zadd(index_key, {meta.result_set_id: expires})
            pipe.expire(index_key, config.MATCH_RESULT_MAX_LIFETIME_SECONDS)
            pipe.execute()
            self._trim_oldest(meta.owner_user_id)
        except RedisError as exc:
            raise MatchResultStoreUnavailable("匹配结果缓存暂时不可用") from exc
        return replace(
            meta,
            created_at=meta.created_at or datetime.fromtimestamp(now, timezone.utc),
            expires_at=datetime.fromtimestamp(expires, timezone.utc),
        )

    def _trim_oldest(self, owner_user_id: int) -> None:
        index_key = self._index_key(owner_user_id)
        count = int(self.client.zcard(index_key))
        overflow = count - config.MATCH_RESULT_MAX_ACTIVE_PER_USER
        if overflow <= 0:
            return
        oldest = self.client.zrange(index_key, 0, overflow - 1)
        for result_set_id in oldest:
            self.delete(owner_user_id, str(result_set_id))

    def get_meta(self, owner_user_id: int, result_set_id: str) -> MatchResultMeta | None:
        meta_key, _rank_key, _scores_key = self._keys(result_set_id)
        try:
            data = self.client.hgetall(meta_key)
        except RedisError as exc:
            raise MatchResultStoreUnavailable("匹配结果缓存暂时不可用") from exc
        if (
            not data
            or data.get("layout_version") != "2"
            or int(data.get("owner_user_id", -1)) != owner_user_id
        ):
            return None
        created = datetime.fromtimestamp(int(data["created_at"]), timezone.utc)
        expires = datetime.fromtimestamp(int(data["expires_at"]), timezone.utc)
        return MatchResultMeta(
            result_set_id=result_set_id,
            owner_user_id=owner_user_id,
            total=int(data["total"]),
            profile=json.loads(data.get("profile_json") or "{}"),
            profile_hash=data.get("profile_hash", ""),
            model_version=data.get("model_version", ""),
            dataset_version=data.get("dataset_version", ""),
            prefer_hits=json.loads(data.get("prefer_hits") or "[]"),
            created_at=created,
            expires_at=expires,
        )

    def page(
        self, owner_user_id: int, result_set_id: str, *, offset: int, limit: int
    ) -> tuple[MatchResultMeta, list[RankedCandidateRef]] | None:
        meta = self.get_meta(owner_user_id, result_set_id)
        if meta is None:
            return None
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), config.MATCH_RESULT_PAGE_SIZE_MAX))
        _meta_key, items_key, _members_key = self._keys(result_set_id)
        try:
            packed = self.client.lrange(items_key, offset, offset + limit - 1)
        except RedisError as exc:
            raise MatchResultStoreUnavailable("匹配结果缓存暂时不可用") from exc
        refs = []
        for index, item in enumerate(packed):
            donor_id, score = str(item).split(":", 1)
            refs.append(
                RankedCandidateRef(int(donor_id), offset + index + 1, round(float(score), 6))
            )
        return meta, refs

    def contains(self, owner_user_id: int, result_set_id: str, donor_id: int) -> bool:
        if self.get_meta(owner_user_id, result_set_id) is None:
            return False
        _meta_key, _items_key, members_key = self._keys(result_set_id)
        try:
            return bool(self.client.sismember(members_key, str(donor_id)))
        except RedisError as exc:
            raise MatchResultStoreUnavailable("匹配结果缓存暂时不可用") from exc

    def delete(self, owner_user_id: int, result_set_id: str) -> bool:
        meta = self.get_meta(owner_user_id, result_set_id)
        if meta is None:
            return False
        meta_key, items_key, members_key = self._keys(result_set_id)
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.delete(meta_key, items_key, members_key)
            pipe.zrem(self._index_key(owner_user_id), result_set_id)
            pipe.execute()
        except RedisError as exc:
            raise MatchResultStoreUnavailable("匹配结果缓存暂时不可用") from exc
        return True
