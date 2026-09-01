from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from core.preference.result_types import MatchResultMeta, RankedCandidateRef
from db import match_runs_repo


def _meta(total=2):
    return MatchResultMeta(
        result_set_id=str(uuid4()),
        owner_user_id=7,
        total=total,
        profile={"schema_version": "1.0", "attributes": {}},
        profile_hash="",
        model_version="v2",
        dataset_version="donors:2",
        prefer_hits=[],
    )


def test_snapshot_rejects_invalid_rank_and_non_finite_score():
    meta = _meta()
    with pytest.raises(match_runs_repo.MatchRunValidationError, match="rank"):
        match_runs_repo._validate(
            meta,
            [RankedCandidateRef(1, 1, 0.9), RankedCandidateRef(2, 3, 0.8)],
        )
    with pytest.raises(match_runs_repo.MatchRunValidationError, match="有限"):
        match_runs_repo._validate(
            meta,
            [RankedCandidateRef(1, 1, 0.9), RankedCandidateRef(2, 2, float("nan"))],
        )


def test_create_snapshot_quantizes_scores_and_is_user_bound(monkeypatch):
    calls = []
    created = datetime.now(timezone.utc)

    @contextmanager
    def fake_session():
        yield object()

    def fake_fetchone(_conn, sql, params):
        calls.append((sql, params))
        return {"created_at": created}

    monkeypatch.setattr(match_runs_repo, "db_session", fake_session)
    monkeypatch.setattr(match_runs_repo, "fetchone", fake_fetchone)
    meta = _meta()
    result = match_runs_repo.create_match_run(
        meta,
        [RankedCandidateRef(91, 1, 0.12345678), RankedCandidateRef(92, 2, 0.9)],
    )

    params = calls[0][1]
    assert params[1] == 7
    assert params[7] == [91, 92]
    assert params[8] == [0.123457, 0.9]
    assert len(result.profile_hash) == 64
    assert result.created_at == created


def test_page_uses_postgres_array_slice_and_preserves_rank(monkeypatch):
    @contextmanager
    def fake_session():
        yield object()

    def fake_fetchone(_conn, _sql, params):
        assert params[:4] == (21, 40, 21, 40)
        return {
            "id": uuid4(), "user_id": 4, "profile_json": {}, "profile_hash": "h",
            "model_version": "v2", "dataset_version": "d", "total": 100,
            "prefer_hits": [], "created_at": datetime.now(timezone.utc),
            "page_ids": [31, 32], "page_scores": [0.8, 0.7],
        }

    monkeypatch.setattr(match_runs_repo, "db_session", fake_session)
    monkeypatch.setattr(match_runs_repo, "fetchone", fake_fetchone)
    _meta_value, refs = match_runs_repo.get_match_run_page(
        str(uuid4()), 4, offset=20, limit=20
    )
    assert [(ref.donor_id, ref.rank) for ref in refs] == [(31, 21), (32, 22)]


def test_profile_digest_is_stable_for_key_order():
    assert match_runs_repo.profile_digest({"b": 2, "a": 1}) == match_runs_repo.profile_digest(
        {"a": 1, "b": 2}
    )
