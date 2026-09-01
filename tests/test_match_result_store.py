from datetime import datetime, timezone
from uuid import uuid4

from api.match_result_store import MatchResultStore
from core.preference.result_types import MatchResultMeta, RankedCandidateRef


class _Pipeline:
    def __init__(self, redis):
        self.redis = redis
        self.calls = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return queue

    def execute(self):
        return [getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.calls]


class _FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.zsets = {}

    def pipeline(self, transaction=True):
        return _Pipeline(self)

    def delete(self, *keys):
        for key in keys:
            self.hashes.pop(key, None)
            self.zsets.pop(key, None)
        return 1

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hmget(self, key, members):
        data = self.hashes.get(key, {})
        return [data.get(member) for member in members]

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update({str(k): float(v) for k, v in mapping.items()})
        return len(mapping)

    def zrange(self, key, start, stop, withscores=False):
        pairs = sorted(self.zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]))
        selected = pairs[start:] if stop == -1 else pairs[start:stop + 1]
        return selected if withscores else [member for member, _score in selected]

    def zscore(self, key, member):
        return self.zsets.get(key, {}).get(str(member))

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def zrem(self, key, member):
        return int(self.zsets.setdefault(key, {}).pop(str(member), None) is not None)

    def zremrangebyscore(self, key, minimum, maximum):
        low = float("-inf") if minimum == "-inf" else float(minimum)
        remove = [m for m, s in self.zsets.get(key, {}).items() if low <= s <= float(maximum)]
        for member in remove:
            self.zsets[key].pop(member)
        return len(remove)

    def expire(self, _key, _seconds):
        return True


def _meta(owner=5, total=3):
    return MatchResultMeta(
        result_set_id=str(uuid4()), owner_user_id=owner, total=total,
        profile={"attributes": {}}, profile_hash="abc", model_version="v2",
        dataset_version="d1", created_at=datetime.now(timezone.utc),
    )


def test_compact_result_round_trip_preserves_explicit_rank_for_equal_scores():
    fake = _FakeRedis()
    store = MatchResultStore(fake)
    meta = _meta()
    refs = [
        RankedCandidateRef(101, 1, 0.9),
        RankedCandidateRef(99, 2, 0.9),
        RankedCandidateRef(100, 3, 0.8),
    ]
    store.create(meta, refs)
    loaded_meta, page = store.page(5, meta.result_set_id, offset=0, limit=2)
    assert loaded_meta.total == 3
    assert [(x.donor_id, x.rank, x.score) for x in page] == [
        (101, 1, 0.9), (99, 2, 0.9)
    ]


def test_owner_isolation_and_membership_after_first_page():
    store = MatchResultStore(_FakeRedis())
    meta = _meta(owner=8)
    refs = [RankedCandidateRef(i, rank, 1 - rank / 100) for rank, i in enumerate((11, 12, 13), 1)]
    store.create(meta, refs)
    assert store.page(9, meta.result_set_id, offset=0, limit=20) is None
    assert store.contains(8, meta.result_set_id, 13) is True
    assert store.contains(9, meta.result_set_id, 13) is False


def test_user_active_result_limit_removes_oldest(monkeypatch):
    fake = _FakeRedis()
    store = MatchResultStore(fake)
    monkeypatch.setattr("config.MATCH_RESULT_MAX_ACTIVE_PER_USER", 1)
    first = _meta(owner=3, total=0)
    second = _meta(owner=3, total=0)
    store.create(first, [])
    store.create(second, [])
    assert store.get_meta(3, first.result_set_id) is None
    assert store.get_meta(3, second.result_set_id) is not None

