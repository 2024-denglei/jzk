import json
from contextlib import contextmanager

import pytest

from api import chat_persist


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self):
        self.update_params = None

    def execute(self, sql, params):
        if "SELECT id, state_json" in sql:
            return _Result({
                "id": 9,
                "state_json": json.dumps({
                    "match_result_id": "11111111-1111-1111-1111-111111111111",
                    "match_total": 4303,
                }),
            })
        if "UPDATE app.chats" in sql:
            self.update_params = params
            return _Result()
        raise AssertionError(sql)


def test_empty_browser_state_does_not_erase_server_match_reference(monkeypatch):
    conn = _Conn()

    @contextmanager
    def session():
        yield conn

    monkeypatch.setattr(chat_persist, "db_session", session)
    chat_persist.upsert_user_chat(
        user_id=1,
        session_id="s1",
        messages=[{"role": "bot", "content": "结果"}],
        candidates=[],
        state={},
    )
    saved_state = json.loads(conn.update_params[3])
    assert saved_state["match_total"] == 4303
    assert saved_state["match_result_id"].startswith("1111")


def test_legacy_writer_refuses_to_overwrite_v2_chat(monkeypatch):
    class V2Conn(_Conn):
        def execute(self, sql, params):
            if "SELECT id, state_json" in sql:
                return _Result({"id": 9, "state_json": "{}", "storage_version": 2})
            return super().execute(sql, params)

    @contextmanager
    def session():
        yield V2Conn()

    monkeypatch.setattr(chat_persist, "db_session", session)
    with pytest.raises(chat_persist.LegacyChatWriteBlocked):
        chat_persist.upsert_user_chat(
            user_id=1,
            session_id="v2-session",
            messages=[{"role": "user", "content": "不得覆盖"}],
        )
