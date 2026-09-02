from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from core.preference.result_types import MatchResultMeta, MatchSnapshotItem, RankedCandidateRef
from db import match_runs_repo


def _meta(total=2):
    return MatchResultMeta(
        result_set_id=str(uuid4()), owner_user_id=7, total=total,
        profile={"schema_version": "1.0", "attributes": {}}, profile_hash="",
        model_version="v32-v4-best-mae", dataset_version="donors:2", prefer_hits=[],
        model_checkpoint_sha256="a" * 64,
    )


def _snapshot(donor_id: int, rank: int, score: float) -> MatchSnapshotItem:
    return MatchSnapshotItem(
        donor_id=donor_id, rank=rank, score=score,
        donor_code_snapshot=f"D{donor_id}", donor_snapshot={"code": f"D{donor_id}"},
        match_explanation={},
    )


def test_snapshot_rejects_invalid_rank_non_finite_score_and_missing_items():
    meta = _meta()
    with pytest.raises(match_runs_repo.MatchRunValidationError, match="rank"):
        match_runs_repo._validate(
            meta, [RankedCandidateRef(1, 1, 0.9), RankedCandidateRef(2, 3, 0.8)]
        )
    with pytest.raises(match_runs_repo.MatchRunValidationError, match="有限"):
        match_runs_repo._validate(
            meta, [RankedCandidateRef(1, 1, 0.9), RankedCandidateRef(2, 2, float("nan"))]
        )
    with pytest.raises(match_runs_repo.MatchRunValidationError, match="完整候选快照"):
        match_runs_repo._validate_snapshot_items(
            [RankedCandidateRef(1, 1, 0.9), RankedCandidateRef(2, 2, 0.8)], None
        )


def test_create_snapshot_writes_only_versioned_items(monkeypatch):
    created = datetime.now(timezone.utc)
    ready_at = datetime.now(timezone.utc)
    fetched = iter([
        {"created_at": created},
        {"count": 2, "min_rank": 1, "max_rank": 2},
        {"created_at": created, "ready_at": ready_at},
    ])
    executed_many = []
    sql_calls = []
    params_calls = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def executemany(self, sql, values):
            executed_many.extend(values)
            sql_calls.append(sql)

    class Conn:
        def cursor(self): return Cursor()

    @contextmanager
    def fake_session():
        yield Conn()

    def fake_fetchone(_conn, sql, _params):
        sql_calls.append(sql)
        params_calls.append(_params)
        return next(fetched)

    monkeypatch.setattr(match_runs_repo, "db_session", fake_session)
    monkeypatch.setattr(match_runs_repo, "fetchone", fake_fetchone)
    meta = _meta()
    refs = [RankedCandidateRef(91, 1, 0.12345678), RankedCandidateRef(92, 2, 0.9)]
    result = match_runs_repo.create_match_run(
        meta, refs, [_snapshot(91, 1, 0.12345678), _snapshot(92, 2, 0.9)]
    )

    assert "donor_ids" not in sql_calls[0] and "scores" not in sql_calls[0]
    assert "model_checkpoint_sha256" in sql_calls[0]
    assert params_calls[0][5] == "a" * 64
    assert [row[1:4] for row in executed_many] == [(1, 91, 0.123457), (2, 92, 0.9)]
    assert result.status == "ready" and result.ready_at == ready_at


def test_page_reads_ranked_items_instead_of_array_slices(monkeypatch):
    now = datetime.now(timezone.utc)

    @contextmanager
    def fake_session():
        yield object()

    meta_row = {
        "id": uuid4(), "user_id": 4, "profile_json": {}, "profile_hash": "h",
        "model_version": "v2", "dataset_version": "d", "total": 100,
        "prefer_hits": [], "status": "ready", "snapshot_schema_version": 1,
        "snapshot_source": "native", "created_at": now, "ready_at": now,
    }
    captured = {}

    def fake_fetchall(_conn, sql, params):
        captured.update(sql=sql, params=params)
        return [
            {"rank": 21, "donor_id": 31, "score": 0.8},
            {"rank": 22, "donor_id": 32, "score": 0.7},
        ]

    monkeypatch.setattr(match_runs_repo, "db_session", fake_session)
    monkeypatch.setattr(match_runs_repo, "fetchone", lambda *_args: meta_row)
    monkeypatch.setattr(match_runs_repo, "fetchall", fake_fetchall)
    _meta_value, refs = match_runs_repo.get_match_run_page(
        str(meta_row["id"]), 4, offset=20, limit=20
    )

    assert "app.match_run_items" in captured["sql"]
    assert captured["params"][1:] == (20, 20)
    assert [(ref.donor_id, ref.rank) for ref in refs] == [(31, 21), (32, 22)]


def test_profile_digest_is_stable_for_key_order():
    assert match_runs_repo.profile_digest({"b": 2, "a": 1}) == match_runs_repo.profile_digest(
        {"a": 1, "b": 2}
    )
