import json

import pytest

from dialogue.session import SessionManager
from dialogue.session_store import (
    RedisSessionStore,
    SessionConflict,
    SessionLimitExceeded,
    SessionTooLarge,
)


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.indexes: dict[str, set[str]] = {}

    def get(self, key):
        return self.values.get(key)

    def eval(self, _script, _num_keys, key, index_key, expected_version, raw, _ttl, max_active, _now):
        current = self.values.get(key)
        current_version = int(json.loads(current).get("storage_version", 0)) if current else 0
        if current_version != int(expected_version):
            return 0
        index = self.indexes.setdefault(index_key, set())
        if current is None and len(index) >= int(max_active):
            return -1
        self.values[key] = raw
        index.add(key)
        return 1

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def zrem(self, key, member):
        self.indexes.setdefault(key, set()).discard(member)


def test_two_managers_share_redis_session_without_cross_user_leakage():
    redis = _FakeRedis()
    first_manager = SessionManager(RedisSessionStore(redis))
    second_manager = SessionManager(RedisSessionStore(redis))

    first = first_manager.create_session(1)
    first.add_message("user", "跨实例消息")
    first_manager.put_session(first)

    loaded = second_manager.get_session(1, first.session_id)
    assert loaded is not None
    assert loaded.history[-1]["content"] == "跨实例消息"
    assert second_manager.get_session(2, first.session_id) is None


def test_redis_session_uses_optimistic_version_to_prevent_lost_updates():
    redis = _FakeRedis()
    store = RedisSessionStore(redis)
    manager = SessionManager(store)
    created = manager.create_session(1)

    first_copy = store.load(1, created.session_id)
    second_copy = store.load(1, created.session_id)
    assert first_copy is not None and second_copy is not None

    first_copy.add_message("user", "first")
    store.save(first_copy)
    second_copy.add_message("user", "second")
    with pytest.raises(SessionConflict):
        store.save(second_copy)


def test_redis_payload_contains_owner_and_not_a_bare_session_id_key():
    redis = _FakeRedis()
    store = RedisSessionStore(redis)
    manager = SessionManager(store)
    session = manager.create_session(9)

    key = next(iter(redis.values))
    payload = json.loads(redis.values[key])
    assert key.startswith("jzk:chat-session:9:")
    assert payload["owner_user_id"] == 9
    assert payload["session_id"] == session.session_id


def test_active_session_count_is_limited_per_user(monkeypatch):
    redis = _FakeRedis()
    manager = SessionManager(RedisSessionStore(redis))
    monkeypatch.setattr("config.SESSION_MAX_ACTIVE_PER_USER", 1)

    manager.create_session(1)
    with pytest.raises(SessionLimitExceeded):
        manager.create_session(1)
    assert manager.create_session(2).owner_user_id == 2


def test_oversized_session_is_rejected(monkeypatch):
    redis = _FakeRedis()
    manager = SessionManager(RedisSessionStore(redis))
    session = manager.create_session(1)
    session.add_message("user", "x" * 100)
    monkeypatch.setattr("config.SESSION_MAX_BYTES", 20)

    with pytest.raises(SessionTooLarge):
        manager.put_session(session)
