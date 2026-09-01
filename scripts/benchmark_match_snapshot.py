"""测量完整匹配快照在当前 PostgreSQL 上的写入和分页成本。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.preference.result_types import MatchResultMeta, MatchSnapshotItem, RankedCandidateRef
from db.match_runs_repo import create_match_run, get_match_run_items_page
from db.pg import close_pools, db_session, fetchone


def run(count: int) -> dict[str, float | int]:
    email = f"snapshot-benchmark-{uuid4()}@example.test"
    with db_session() as conn:
        user_id = int(
            fetchone(
                conn,
                """
                INSERT INTO app.users (email, password_hash, nickname)
                VALUES (%s, 'benchmark-only', 'snapshot-benchmark') RETURNING id
                """,
                (email,),
            )["id"]
        )
        before_bytes = int(
            fetchone(
                conn,
                "SELECT pg_total_relation_size('app.match_run_items') AS bytes",
            )["bytes"]
        )

    result_id = str(uuid4())
    refs = [
        RankedCandidateRef(donor_id=index, rank=index, score=round(1 - index / (count + 1), 6))
        for index in range(1, count + 1)
    ]
    snapshots = [
        MatchSnapshotItem(
            donor_id=ref.donor_id,
            rank=ref.rank,
            score=ref.score,
            donor_code_snapshot=f"B{ref.donor_id:06d}",
            donor_snapshot={
                "id": ref.donor_id,
                "code": f"B{ref.donor_id:06d}",
                "education": "硕士",
                "height": "178",
                "blood_type": "O",
                "status": "active",
            },
            match_explanation={
                "reason": "匹配：height_cm、education",
                "match_pct": round(ref.score * 100, 2),
                "field_match": {
                    "height_cm": {"match": True, "actual": 178, "target": {"min": 175}}
                },
            },
        )
        for ref in refs
    ]

    started = perf_counter()
    create_match_run(
        MatchResultMeta(
            result_set_id=result_id,
            owner_user_id=user_id,
            total=count,
            profile={"schema_version": "1.0", "attributes": {}},
            profile_hash="",
            model_version="benchmark",
            dataset_version="benchmark",
        ),
        refs,
        snapshots,
    )
    write_ms = (perf_counter() - started) * 1000

    page_started = perf_counter()
    page = get_match_run_items_page(result_id, user_id, offset=max(0, count - 20), limit=20)
    page_ms = (perf_counter() - page_started) * 1000
    assert page is not None and len(page[1]) == min(20, count)

    with db_session() as conn:
        after_bytes = int(
            fetchone(
                conn,
                "SELECT pg_total_relation_size('app.match_run_items') AS bytes",
            )["bytes"]
        )
        conn.execute("DELETE FROM app.users WHERE id = %s", (user_id,))
    close_pools()
    return {
        "items": count,
        "write_ms": round(write_ms, 2),
        "last_page_ms": round(page_ms, 2),
        "relation_growth_bytes": max(0, after_bytes - before_bytes),
        "bytes_per_item_estimate": round(max(0, after_bytes - before_bytes) / max(1, count), 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=True, choices=(4303, 20000))
    args = parser.parse_args()
    print(json.dumps(run(args.count), ensure_ascii=False))
