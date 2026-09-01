"""V2 对话灰度发布的只读运行指标。"""

from __future__ import annotations

from typing import Any

import config
from db.pg import db_session, fetchone


def get_chat_v2_rollout_metrics() -> dict[str, int]:
    with db_session(admin=True) as conn:
        row = fetchone(
            conn,
            """
            SELECT
              (SELECT COUNT(*) FROM app.chats WHERE storage_version = 1) AS chats_v1,
              (SELECT COUNT(*) FROM app.chats WHERE storage_version = 2) AS chats_v2,
              (SELECT COUNT(*) FROM app.ai_generation_runs WHERE status = 'queued') AS queued,
              (SELECT COUNT(*) FROM app.ai_generation_runs WHERE status = 'running') AS running,
              (SELECT COUNT(*) FROM app.ai_generation_runs WHERE status = 'failed') AS failed,
              (SELECT COUNT(*) FROM app.ai_generation_runs
               WHERE status = 'queued' AND attempt_count > 0) AS retrying,
              (SELECT COUNT(*) FROM app.ai_generation_runs
               WHERE status = 'running' AND lease_expires_at < now()) AS expired_leases,
              COALESCE((SELECT EXTRACT(EPOCH FROM now() - MIN(queued_at))::bigint
                        FROM app.ai_generation_runs WHERE status = 'queued'), 0)
                AS oldest_queued_seconds,
              (SELECT COUNT(*) FROM app.ai_generation_runs
               WHERE status IN ('queued', 'running') AND attempt_count >= %s) AS exhausted_active,
              (SELECT COUNT(*) FROM app.chat_messages message
               WHERE message.status = 'generating'
                 AND NOT EXISTS (
                   SELECT 1 FROM app.ai_generation_runs generation
                   WHERE generation.assistant_message_id = message.id
                     AND generation.status IN ('queued', 'running')
                 )) AS orphan_generating_messages,
              (SELECT COUNT(*) FROM app.match_runs
               WHERE status = 'building' AND created_at < now() - interval '10 minutes')
                AS stale_building_snapshots,
              (SELECT COUNT(*) FROM app.match_runs run
               WHERE run.status = 'ready'
                 AND (SELECT COUNT(*) FROM app.match_run_items item
                      WHERE item.match_run_id = run.id) <> run.total)
                AS incomplete_ready_snapshots,
              (SELECT COUNT(*) FROM app.outbox_events
               WHERE status IN ('pending', 'processing', 'failed')) AS outbox_backlog,
              (SELECT COUNT(*) FROM app.outbox_events
               WHERE status <> 'completed' AND attempts >= %s) AS outbox_exhausted,
              COALESCE((SELECT EXTRACT(EPOCH FROM now() - MIN(created_at))::bigint
                        FROM app.outbox_events
                        WHERE status IN ('pending', 'processing', 'failed')), 0)
                AS oldest_outbox_seconds
            """,
            (config.CHAT_GENERATION_MAX_ATTEMPTS, config.CHAT_OUTBOX_MAX_ATTEMPTS),
        )
    return {key: int(value or 0) for key, value in (row or {}).items()}


def rollout_config_view() -> dict[str, Any]:
    """不暴露 rollout salt，只输出可用于发布核对的非敏感配置。"""
    return {
        "read_enabled": config.CHAT_STORAGE_V2_READ_ENABLED,
        "write_enabled": config.CHAT_STORAGE_V2_WRITE_ENABLED,
        "write_percent": config.CHAT_STORAGE_V2_WRITE_PERCENT,
        "write_allowlist_size": len(config.CHAT_STORAGE_V2_WRITE_USER_IDS),
        "worker_enabled": config.CHAT_GENERATION_WORKER_ENABLED,
        "worker_user_scope_size": len(config.CHAT_GENERATION_WORKER_USER_IDS),
        "outbox_worker_enabled": config.CHAT_OUTBOX_WORKER_ENABLED,
    }
