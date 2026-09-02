"""测量「对话 + 匹配」链路各阶段耗时。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from time import perf_counter
from uuid import uuid4

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.match import execute_match
from core.preference.pipeline import match_profile
from core.preference.validate import parse_profile

# 「研究生学历，身高175以上」对应的结构化画像（与顾问工具一致）
TEST_PROFILE = {
    "schema_version": "1.0",
    "attributes": {
        "education": {
            "constraint": "must",
            "weight": 1.0,
            "values": ["硕士", "博士"],
        },
        "height_cm": {
            "constraint": "must",
            "weight": 1.0,
            "range": {"min": 175, "max": None},
        },
    },
}


def bench_match_layers(user_id: int) -> dict:
    profile = parse_profile(TEST_PROFILE)
    out: dict = {}

    t0 = perf_counter()
    result = match_profile(profile, build_snapshot=False)
    out["match_profile_ms"] = round((perf_counter() - t0) * 1000, 1)
    out["filtered_count"] = result.filtered_count
    out["ranked_count"] = result.ranked_count or len(result.ranked_refs or [])
    out["pipeline_timings"] = dict(result.timings or {})

    t1 = perf_counter()
    full = execute_match(
        TEST_PROFILE,
        owner_user_id=user_id,
        page_size=20,
    )
    out["execute_match_ms"] = round((perf_counter() - t1) * 1000, 1)
    out["execute_match_timings"] = dict(full.get("timings") or {})
    out["snapshot_total"] = full.get("total")
    return out


def bench_scorer_http(base_url: str, token: str) -> dict:
    import config
    from core.preference.scoring_client import HttpScoringRanker

    ranker = HttpScoringRanker(
        base_url=base_url.rstrip("/"),
        token=token,
        contract_version=config.MATCH_SCORER_CONTRACT_VERSION,
        timeout_seconds=config.MATCH_SCORER_TIMEOUT_SECONDS,
        max_candidates=config.MATCH_SCORER_MAX_CANDIDATES,
    )
    profile = parse_profile(TEST_PROFILE)

    from db.pg import db_session, fetchall
    from core.preference.pipeline import build_hard_filter_sql

    sql, params = build_hard_filter_sql(profile)
    with db_session() as conn:
        rows = fetchall(conn, sql, params)

    out = {"eligible_rows": len(rows)}
    t0 = perf_counter()
    ranked = ranker.rank(profile, rows)
    out["scorer_http_rank_ms"] = round((perf_counter() - t0) * 1000, 1)
    out["ranked_count"] = len(ranked)
    out["scorer_timings"] = dict(getattr(ranker, "last_timings", {}) or {})
    model = ranker.model_info()
    out["candidate_pool"] = model.candidate_pool
    return out


def bench_chat_e2e(base_url: str, message: str) -> dict:
    """通过 HTTP 走完整对话：注册 → 发消息 → 等 generation 完成。"""
    base = base_url.rstrip("/")
    email = f"bench-{uuid4().hex[:10]}@example.test"
    password = "BenchTest@12345"
    out: dict = {"message": message}

    with httpx.Client(base_url=base, timeout=180.0) as client:
        t0 = perf_counter()
        reg = client.post("/api/auth/register", json={
            "email": email,
            "password": password,
            "nickname": "bench",
        })
        out["register_ms"] = round((perf_counter() - t0) * 1000, 1)
        if reg.status_code not in {200, 201}:
            out["register_error"] = reg.text
            return out
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        t1 = perf_counter()
        turn = client.post(
            "/api/chats/turns",
            json={"content": message, "client_request_id": str(uuid4())},
            headers=headers,
        )
        out["turn_ms"] = round((perf_counter() - t1) * 1000, 1)
        if turn.status_code != 202:
            out["turn_error"] = turn.text
            return out
        body = turn.json()
        generation_id = body["generation_id"]
        out["generation_id"] = generation_id

        t2 = perf_counter()
        deadline = time.time() + 170
        last_event = None
        events: list[dict] = []
        with client.stream(
            "GET",
            f"/api/generations/{generation_id}/events",
            headers=headers,
            timeout=180.0,
        ) as stream:
            for line in stream.iter_lines():
                if time.time() > deadline:
                    out["sse_timeout"] = True
                    break
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                events.append({"event": last_event, "payload_keys": list(payload.keys())})
                if last_event == "completed" or payload.get("status") == "completed":
                    out["generation_status"] = payload.get("status", "completed")
                    break
                if payload.get("status") in {"failed", "stopped"}:
                    out["generation_status"] = payload["status"]
                    break
            # parse SSE event names from raw - iter_lines doesn't give event type easily
        # Re-fetch with simpler polling
        while time.time() < deadline:
            # Poll generation status via messages isn't ideal; use event stream properly
            break

        out["sse_wait_ms"] = round((perf_counter() - t2) * 1000, 1)

    return out


def bench_chat_e2e_poll(base_url: str, message: str) -> dict:
    base = base_url.rstrip("/")
    email = f"bench-{uuid4().hex[:10]}@example.test"
    password = "BenchTest@12345"
    out: dict = {"message": message, "phases": {}}
    phases = out["phases"]

    with httpx.Client(base_url=base, timeout=180.0) as client:
        started = perf_counter()
        reg = client.post("/api/auth/register", json={
            "email": email,
            "password": password,
            "nickname": "bench",
        })
        phases["register_ms"] = round((perf_counter() - started) * 1000, 1)
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        t_turn = perf_counter()
        turn = client.post(
            "/api/chats/turns",
            json={"content": message, "client_request_id": str(uuid4())},
            headers=headers,
        )
        phases["create_turn_ms"] = round((perf_counter() - t_turn) * 1000, 1)
        turn_body = turn.json()
        generation_id = turn_body["generation_id"]
        chat_id = turn_body["chat_id"]
        branch_id = turn_body["branch_id"]
        assistant_message_id = turn_body.get("assistant_message_id")
        out["generation_id"] = generation_id

        t_sse = perf_counter()
        status = None
        with httpx.Client(base_url=base, timeout=180.0) as sse_client:
            with sse_client.stream(
                "GET",
                f"/api/generations/{generation_id}/events",
                headers=headers,
            ) as resp:
                event_name = None
                for raw in resp.iter_lines():
                    if raw.startswith("event:"):
                        event_name = raw.split(":", 1)[1].strip()
                    elif raw.startswith("data:"):
                        data = json.loads(raw.split(":", 1)[1].strip())
                        if event_name in {"completed", "failed", "stopped"}:
                            status = event_name
                            out["final_event"] = data
                            break
                        if event_name == "agent_stage":
                            stage = data.get("stage")
                            key = f"stage_{stage}_ms"
                            if key not in phases:
                                phases[key] = round((perf_counter() - t_sse) * 1000, 1)
        phases["generation_total_ms"] = round((perf_counter() - t_sse) * 1000, 1)
        out["generation_status"] = status

        # 读取 generation timings（若 worker 已写入）
        from db.pg import db_session, fetchone

        with db_session() as conn:
            row = fetchone(
                conn,
                """
                SELECT status, timings_json, model_name
                FROM app.ai_generation_runs
                WHERE id = %s
                """,
                (generation_id,),
            )
        if row:
            out["db_generation_status"] = row["status"]
            out["generation_timings"] = row.get("timings_json") or {}
            out["model_name"] = row.get("model_name")

        t_msg = perf_counter()
        msgs = client.get(
            f"/api/chats/{chat_id}/branches/{branch_id}/messages",
            headers=headers,
        )
        phases["load_messages_ms"] = round((perf_counter() - t_msg) * 1000, 1)
        if msgs.status_code == 200:
            items = msgs.json().get("items") or []
            assistant = next(
                (m for m in items if m.get("id") == assistant_message_id),
                None,
            )
            if assistant:
                out["assistant_preview"] = (assistant.get("content") or "")[:120]
                out["match_run_total"] = (assistant.get("match_run") or {}).get("total")

    phases["overall_ms"] = round((perf_counter() - started) * 1000, 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--message", default="研究生学历，身高175以上")
    parser.add_argument("--skip-e2e", action="store_true")
    args = parser.parse_args()

    import config
    from db.pg import db_session, fetchone

    with db_session() as conn:
        user_id = int(
            fetchone(
                conn,
                """
                INSERT INTO app.users (email, password_hash, nickname)
                VALUES (%s, 'benchmark-only', 'latency-bench')
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (f"latency-bench-{uuid4().hex}@example.test",),
            )["id"]
        )

    report = {
        "profile": TEST_PROFILE,
        "config": {
            "candidate_pool_env": os.getenv("SCORER_CANDIDATE_POOL"),
            "scorer_timeout": config.MATCH_SCORER_TIMEOUT_SECONDS,
            "llm_model": config.LLM_MODEL,
        },
        "match_layers": bench_match_layers(user_id),
        "scorer_http": bench_scorer_http(
            config.MATCH_SCORER_URL,
            config.MATCH_SCORER_TOKEN,
        ),
    }
    if not args.skip_e2e:
        report["chat_e2e"] = bench_chat_e2e_poll(args.base_url, args.message)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
