from scripts import manage_match_snapshots


def test_snapshot_stats_normalizes_database_values(monkeypatch):
    class Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(manage_match_snapshots, "db_session", Session)
    monkeypatch.setattr(
        manage_match_snapshots,
        "fetchone",
        lambda _conn, _sql, params: {
            "total": 12, "expired": 3, "table_bytes": 4096, "index_bytes": 1024,
            "retention": params[0],
        },
    )
    assert manage_match_snapshots.snapshot_stats(180) == {
        "total": 12, "expired": 3, "table_bytes": 4096, "index_bytes": 1024,
    }

