from datetime import datetime, timezone
from uuid import uuid4

import pytest

from api import match
from matching.cursor import InvalidMatchCursor, decode_match_cursor, encode_match_cursor
from matching.execute import execute_match
from core.preference.result_types import MatchResultMeta, MatchSnapshotItem, RankedCandidateRef
from core.preference.pipeline import MatchResult


def _meta(result_set_id, total=3):
    return MatchResultMeta(
        result_set_id=result_set_id, owner_user_id=4, total=total,
        profile={
            "schema_version": "1.0",
            "attributes": {"height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}}},
        },
        profile_hash="h", model_version="v2", dataset_version="d",
        created_at=datetime.now(timezone.utc),
    )


def _snap(ref: RankedCandidateRef) -> MatchSnapshotItem:
    return MatchSnapshotItem(
        donor_id=ref.donor_id,
        rank=ref.rank,
        score=ref.score,
        donor_code_snapshot=f"D{ref.donor_id}",
        donor_snapshot={"code": f"D{ref.donor_id}", "status": "active"},
        match_explanation={"reason": "测试", "field_scores": []},
    )


def test_cursor_rejects_tampering_cross_result_and_expiry(monkeypatch):
    monkeypatch.setattr("config.MATCH_CURSOR_TTL_SECONDS", 10)
    token = encode_match_cursor("result-a", 20, now=100)
    assert decode_match_cursor(token, "result-a", now=105).offset == 20
    with pytest.raises(InvalidMatchCursor):
        decode_match_cursor(token + "x", "result-a", now=105)
    with pytest.raises(InvalidMatchCursor, match="不匹配"):
        decode_match_cursor(token, "result-b", now=105)
    with pytest.raises(InvalidMatchCursor, match="过期"):
        decode_match_cursor(token, "result-a", now=111)


def test_page_number_resolves_direct_offset_without_cursor_chain():
    assert match._resolve_result_offset(
        "result-a", cursor=None, page=100, limit=20
    ) == 1980


def test_page_number_and_cursor_are_mutually_exclusive():
    with pytest.raises(match.HTTPException) as exc:
        match._resolve_result_offset(
            "result-a", cursor="signed", page=2, limit=20
        )
    assert exc.value.status_code == 400


def test_page_skips_disabled_candidate_and_advances_scan_cursor(monkeypatch):
    result_set_id = str(uuid4())
    meta = _meta(result_set_id)
    refs = [
        RankedCandidateRef(1, 1, 0.9),
        RankedCandidateRef(2, 2, 0.8),
        RankedCandidateRef(3, 3, 0.7),
    ]

    def load(_owner, _result, *, offset, limit):
        return meta, [_snap(ref) for ref in refs[offset:offset + limit]]

    monkeypatch.setattr(match, "_load_snapshot_page", load)
    monkeypatch.setattr(
        match, "get_donor_statuses_by_ids",
        lambda ids: {donor_id: "active" for donor_id in ids if donor_id != 2},
    )
    data = match._page_payload(4, result_set_id, offset=0, limit=2)
    assert [item["donor_info"]["code"] for item in data["items"]] == ["D1", "D3"]
    assert data["returned_count"] == 2
    assert data["has_more"] is False


def test_direct_page_rank_window_does_not_spill_into_next_page(monkeypatch):
    result_set_id = str(uuid4())
    meta = _meta(result_set_id, total=4)
    refs = [RankedCandidateRef(i, i, 1 - i / 10) for i in range(1, 5)]
    monkeypatch.setattr(
        match, "_load_snapshot_page",
        lambda _owner, _result, *, offset, limit: (
            meta, [_snap(ref) for ref in refs[offset:offset + limit]]
        ),
    )
    monkeypatch.setattr(
        match,
        "get_donor_statuses_by_ids",
        lambda ids: {donor_id: "active" for donor_id in ids if donor_id != 1},
    )
    data = match._page_payload(
        4, result_set_id, offset=0, limit=2, scan_end_offset=2
    )
    assert [item["rank"] for item in data["items"]] == [2]
    assert all(item["rank"] <= 2 for item in data["items"])


def test_page_cursor_does_not_skip_prefetched_active_candidates(monkeypatch):
    result_set_id = str(uuid4())
    meta = _meta(result_set_id, total=12)
    refs = [RankedCandidateRef(i, i, 1 - i / 100) for i in range(1, 13)]
    monkeypatch.setattr(
        match, "_load_snapshot_page",
        lambda _owner, _result, *, offset, limit: (
            meta, [_snap(ref) for ref in refs[offset:offset + limit]]
        ),
    )
    monkeypatch.setattr(
        match, "get_donor_statuses_by_ids",
        lambda ids: {donor_id: "active" for donor_id in ids},
    )
    data = match._page_payload(4, result_set_id, offset=0, limit=2)
    assert [item["rank"] for item in data["items"]] == [1, 2]
    assert decode_match_cursor(data["next_cursor"], result_set_id).offset == 2


def test_cross_user_snapshot_is_reported_as_not_found(monkeypatch):
    monkeypatch.setattr(match, "get_match_run_items_page", lambda *_args, **_kwargs: None)
    assert match._load_snapshot_page(99, str(uuid4()), offset=0, limit=20) is None


def test_create_match_writes_complete_postgres_snapshot_and_returns_first_page(monkeypatch):
    events = []
    refs = [RankedCandidateRef(1, 1, 0.9), RankedCandidateRef(2, 2, 0.8)]
    candidates = [
        {"rank": 1, "score": 0.9, "donor_info": {"code": "D1"}},
        {"rank": 2, "score": 0.8, "donor_info": {"code": "D2"}},
    ]
    snapshot_items = [
        MatchSnapshotItem(
            donor_id=ref.donor_id,
            rank=ref.rank,
            score=ref.score,
            donor_code_snapshot=f"D{ref.donor_id}",
            donor_snapshot={"code": f"D{ref.donor_id}"},
            match_explanation={"reason": "测试"},
        )
        for ref in refs
    ]
    monkeypatch.setattr(
        "matching.execute.match_profile",
        lambda _profile, **_kwargs: MatchResult(
            candidates=candidates, match_level="full", bottlenecks=[], skipped=False,
            filtered_count=2, ranked_refs=refs, snapshot_items=snapshot_items,
        ),
    )
    monkeypatch.setattr("matching.execute.get_donor_dataset_version", lambda: "d1")

    def save_snapshot(meta, saved_refs, saved_items):
        assert list(saved_items) == snapshot_items
        events.append(("postgres", meta.result_set_id, list(saved_refs)))
        return meta

    monkeypatch.setattr("matching.execute.create_match_run", save_snapshot)
    data = execute_match(
        {"schema_version": "1.0", "attributes": {
            "height_cm": {"constraint": "prefer", "weight": 1, "range": {"min": 175}},
        }},
        owner_user_id=4,
        page_size=1,
    )
    assert [event[0] for event in events] == ["postgres"]
    assert events[0][1] == data["result_set_id"]
    assert data["total"] == 2
    assert data["returned_count"] == 1
    assert decode_match_cursor(data["next_cursor"], data["result_set_id"]).offset == 1


def test_create_match_distinguishes_must_hits_from_model_ranked_pool(monkeypatch):
    refs = [RankedCandidateRef(i, i, 1 - i / 1000) for i in range(1, 301)]
    snapshot_items = [_snap(ref) for ref in refs]
    monkeypatch.setattr(
        "matching.execute.match_profile",
        lambda _profile, **_kwargs: MatchResult(
            candidates=[
                {
                    "rank": ref.rank,
                    "score": ref.score,
                    "donor_info": {"code": f"D{ref.donor_id}"},
                }
                for ref in refs[:20]
            ],
            match_level="full",
            bottlenecks=[],
            skipped=False,
            filtered_count=4303,
            ranked_count=300,
            model_version="v32-v4-best-mae",
            checkpoint_sha256="a" * 64,
            ranked_refs=refs,
            snapshot_items=snapshot_items,
        ),
    )
    monkeypatch.setattr("matching.execute.get_donor_dataset_version", lambda: "d2")

    saved = {}

    def save_snapshot(meta, saved_refs, saved_items):
        saved["meta"] = meta
        assert len(saved_refs) == len(saved_items) == 300
        return meta

    monkeypatch.setattr("matching.execute.create_match_run", save_snapshot)
    data = execute_match(
        {
            "schema_version": "1.0",
            "attributes": {
                "height_cm": {
                    "constraint": "prefer",
                    "weight": 1,
                    "range": {"min": 175},
                }
            },
        },
        owner_user_id=4,
        page_size=20,
    )

    assert data["filtered_count"] == 4303
    assert data["ranked_count"] == data["total"] == 300
    assert data["returned_count"] == 20
    assert saved["meta"].total == 300
    assert saved["meta"].model_version == "v32-v4-best-mae"
    assert saved["meta"].model_checkpoint_sha256 == "a" * 64
