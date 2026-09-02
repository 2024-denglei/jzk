from contextlib import contextmanager
from pathlib import Path

from db import pg
from db import sql_runner


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_11 = ROOT / "db" / "postgres" / "11_add_branching_chat_storage.sql"
MIGRATION_12 = ROOT / "db" / "postgres" / "12_add_match_run_items.sql"
MIGRATION_13 = ROOT / "db" / "postgres" / "13_harden_branching_chat_storage.sql"
MIGRATION_14 = ROOT / "db" / "postgres" / "14_enforce_chat_match_snapshot.sql"
MIGRATION_15 = ROOT / "db" / "postgres" / "15_harden_generation_runs.sql"
MIGRATION_16 = ROOT / "db" / "postgres" / "16_drop_legacy_chat_storage.sql"
MIGRATION_17 = ROOT / "db" / "postgres" / "17_allow_current_line_message_edits.sql"
MIGRATION_18 = ROOT / "db" / "postgres" / "18_normalize_branch_names.sql"
MIGRATION_19 = ROOT / "db" / "postgres" / "19_add_chat_message_feedback.sql"


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


def test_match_item_migration_adds_versioned_items_before_final_cleanup():
    sql = MIGRATION_12.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS app.match_run_items" in sql
    assert "snapshot_schema_version" in sql
    assert "snapshot_source" in sql
    assert "legacy_backfill" in sql
    assert "DROP COLUMN" not in sql


def test_final_cleanup_drops_legacy_chat_json_and_match_arrays_with_guards():
    sql = MIGRATION_16.read_text(encoding="utf-8")
    for column in ("session_id", "messages_json", "candidates_json", "state_json"):
        assert f"DROP COLUMN IF EXISTS {column}" in sql
    for column in ("donor_ids", "scores"):
        assert f"DROP COLUMN IF EXISTS {column}" in sql
    assert "storage_version <> 2" in sql
    assert "ready snapshots are incomplete" in sql


def test_hardening_migration_allows_first_message_edit_and_protects_messages():
    sql = MIGRATION_13.read_text(encoding="utf-8")
    assert "fork_reason = 'edit_resend'" in sql
    assert "protect_chat_message_immutability" in sql
    assert "terminal chat messages are immutable" in sql
    assert "chat messages can only be deleted with their chat" in sql


def test_match_snapshot_association_requires_ready_same_owner_snapshot():
    sql = MIGRATION_14.read_text(encoding="utf-8")
    assert "validate_chat_message_match_snapshot" in sql
    assert "snapshot_owner <> chat_owner" in sql
    assert "snapshot_status <> 'ready'" in sql


def test_generation_hardening_migration_prevents_reopening_terminal_runs():
    sql = MIGRATION_15.read_text(encoding="utf-8")
    assert "protect_generation_run_state" in sql
    assert "terminal generation runs are immutable" in sql
    assert "OLD.status = 'queued'" in sql
    assert "OLD.status = 'running'" in sql
    assert "'queued', 'completed', 'stopped', 'failed'" in sql


def test_current_line_edit_migration_keeps_terminal_content_immutable_but_allows_pruning():
    sql = MIGRATION_17.read_text(encoding="utf-8")
    assert "app.allow_message_prune" in sql
    assert "current branch edit" in sql
    assert "terminal chat messages are immutable" in sql


def test_branch_name_migration_uses_short_sequential_labels():
    sql = MIGRATION_18.read_text(encoding="utf-8")
    assert "THEN '主线'" in sql
    assert "ELSE '分支' || row_number()" in sql
    assert "ORDER BY created_at, id" in sql


def test_message_feedback_migration_links_completed_assistant_messages():
    sql = MIGRATION_19.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS app.chat_message_feedback" in sql
    assert "PRIMARY KEY" in sql
    assert "rating IN ('like', 'dislike')" in sql
    assert "message.role = 'assistant'" in sql
    assert "message.status = 'completed'" in sql
    assert "WITH RECURSIVE path" in sql
    assert "ON DELETE CASCADE" in sql


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

    assert called[-10:] == [
        "10_add_match_runs.sql",
        "11_add_branching_chat_storage.sql",
        "12_add_match_run_items.sql",
        "13_harden_branching_chat_storage.sql",
        "14_enforce_chat_match_snapshot.sql",
        "15_harden_generation_runs.sql",
        "16_drop_legacy_chat_storage.sql",
        "17_allow_current_line_message_edits.sql",
        "18_normalize_branch_names.sql",
        "19_add_chat_message_feedback.sql",
    ]
