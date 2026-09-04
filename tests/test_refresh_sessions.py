import pytest

from jzk.api.refresh_sessions import (
    InvalidRefreshToken,
    RefreshSessionStore,
    RefreshTokenReplay,
)


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def eval(self, _script, num_keys, *args):
        if num_keys == 3:
            session_key, subject_key, family_key, raw, _ttl = args
            self.values[session_key] = raw
            self.sets.setdefault(subject_key, set()).add(session_key)
            self.sets.setdefault(family_key, set()).add(session_key)
            return 1
        if num_keys == 5:
            old_key, spent_key, new_key, subject_key, family_key, family_id, raw, _ttl = args
            if old_key not in self.values:
                return 0
            self.values.pop(old_key, None)
            self.sets.setdefault(subject_key, set()).discard(old_key)
            self.sets.setdefault(family_key, set()).discard(old_key)
            self.values[spent_key] = family_id
            self.values[new_key] = raw
            self.sets[subject_key].add(new_key)
            self.sets[family_key].add(new_key)
            return 1
        if num_keys == 1:
            (index_key,) = args
            members = self.sets.pop(index_key, set())
            for key in members:
                self.values.pop(key, None)
            return len(members)
        raise AssertionError(f"unexpected eval call: {num_keys}")

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def srem(self, key, member):
        self.sets.setdefault(key, set()).discard(member)


def test_refresh_tokens_are_hashed_and_rotate_once():
    fake = _FakeRedis()
    store = RefreshSessionStore(fake)
    token = store.create(42, "user", 3, 3600)

    assert token not in str(fake.values)
    session = store.inspect(token)
    assert session.subject_id == 42
    assert session.kind == "user"
    assert session.token_version == 3

    rotated = store.rotate(token, session, 3600)
    assert rotated != token
    assert store.inspect(rotated) == session


def test_replayed_refresh_token_revokes_whole_family():
    fake = _FakeRedis()
    store = RefreshSessionStore(fake)
    token = store.create(42, "user", 0, 3600)
    session = store.inspect(token)
    rotated = store.rotate(token, session, 3600)

    with pytest.raises(RefreshTokenReplay):
        store.inspect(token)
    with pytest.raises(InvalidRefreshToken):
        store.inspect(rotated)


def test_revoke_all_removes_every_session_for_subject():
    fake = _FakeRedis()
    store = RefreshSessionStore(fake)
    first = store.create(42, "user", 0, 3600)
    second = store.create(42, "user", 0, 3600)
    other = store.create(7, "user", 0, 3600)

    assert store.revoke_all("user", 42) == 2
    with pytest.raises(InvalidRefreshToken):
        store.inspect(first)
    with pytest.raises(InvalidRefreshToken):
        store.inspect(second)
    assert store.inspect(other).subject_id == 7


def test_revoke_current_session_only():
    fake = _FakeRedis()
    store = RefreshSessionStore(fake)
    first = store.create(42, "admin", 1, 3600)
    second = store.create(42, "admin", 1, 3600)

    store.revoke(first)
    with pytest.raises(InvalidRefreshToken):
        store.inspect(first)
    assert store.inspect(second).kind == "admin"
