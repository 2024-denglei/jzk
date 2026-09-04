import importlib.util
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "backend" / "scripts"


def _load_script(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manage_match_snapshots = _load_script("manage_match_snapshots")


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
