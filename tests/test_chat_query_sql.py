from uuid import uuid4

from db import chat_queries_repo


class _Result:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, result):
        self.result = result
        self.sql = ""
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        return self.result


def test_message_page_stops_recursive_walk_at_requested_window():
    conn = _Conn(_Result(rows=[]))
    chat_queries_repo.get_message_path(conn, 9, uuid4(), limit=51)
    assert "child.hop < %s" in conn.sql
    assert conn.params[-2:] == (51, 51)


def test_cursor_membership_walk_stops_at_target_depth():
    conn = _Conn(_Result(row={"present": False}))
    chat_queries_repo.message_is_on_path(conn, 9, uuid4(), uuid4())
    assert "target.depth" in conn.sql
    assert "child.id <> target.id" in conn.sql


def test_path_source_avoids_summary_joins_and_legacy_json_columns():
    conn = _Conn(_Result(row=None))
    chat_queries_repo.get_chat_path_source(conn, 7, 9)
    assert "JOIN app.chat_messages" not in conn.sql
    assert "messages_json" not in conn.sql
    assert "state_json" not in conn.sql
