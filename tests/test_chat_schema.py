from contextlib import contextmanager
from pathlib import Path

from db import pg
from db import sql_runner


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_11 = ROOT / "db" / "postgres" / "11_add_branching_chat_storage.sql"
MIGRATION_12 = ROOT / "db" / "postgres" / "12_add_match_run_items.sql"


def test_branching_chat_migration_declares_core_tables_and_constraints():
    sql = MIGRATION_11.read_text(encoding="utf-8")
    for table in (
        "app.chat_branches",
        "app.chat_messages",
        "app.ai_generation_runs",
        "app.ai_generation_steps",
        "app.chat_deletion_audit",
        "app.outbox_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "uq_ai_generation_active_branch" in sql
    assert "uq_chat_messages_request" in sql
    assert "idx_chats_user_updated_id" in sql


def test_match_item_migration_keeps_legacy_arrays_and_adds_versioned_items():
    sql = MIGRATION_12.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS app.match_run_items" in sql
    assert "snapshot_schema_version" in sql
    assert "snapshot_source" in sql
    assert "legacy_backfill" in sql
    assert "DROP COLUMN" not in sql


def test_ensure_schema_runs_v2_migrations_after_match_runs(monkeypatch):
    class Conn:
        def execute(self, _sql, _params=()):
            return _Result({"ok": True})

    class _Result:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    @contextmanager
    def fake_session(admin=False):
        assert admin is True
        yield Conn()

    called = []
    monkeypatch.setattr(pg, "db_session", fake_session)
    monkeypatch.setattr(sql_runner, "run_sql_file", lambda _conn, path: called.append(path.name))

    pg.ensure_schema()

    assert called[-3:] == [
        "10_add_match_runs.sql",
        "11_add_branching_chat_storage.sql",
        "12_add_match_run_items.sql",
    ]
