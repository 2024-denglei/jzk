from contextlib import contextmanager

from jzk.db import pg


class _Connection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Pool:
    def __init__(self):
        self.conn = _Connection()
        self.timeouts = []

    @contextmanager
    def connection(self, timeout):
        self.timeouts.append(timeout)
        yield self.conn


def test_db_session_borrows_and_returns_pooled_connection(monkeypatch):
    pool = _Pool()
    monkeypatch.setattr(pg, "initialize_pools", lambda: None)
    monkeypatch.setattr(pg, "_app_pool", pool)

    with pg.db_session() as conn:
        assert conn is pool.conn

    assert pool.conn.commits == 1
    assert pool.conn.rollbacks == 0
    assert pool.timeouts == [pg.config.PG_POOL_TIMEOUT_SECONDS]


def test_db_session_rolls_back_before_returning_connection(monkeypatch):
    pool = _Pool()
    monkeypatch.setattr(pg, "initialize_pools", lambda: None)
    monkeypatch.setattr(pg, "_admin_pool", pool)

    try:
        with pg.db_session(admin=True):
            raise ValueError("boom")
    except ValueError:
        pass

    assert pool.conn.commits == 0
    assert pool.conn.rollbacks == 1
