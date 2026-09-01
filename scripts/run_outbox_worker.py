#!/usr/bin/env python3
"""运行 Chat Outbox Worker。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.pg import close_pools, ensure_schema, initialize_pools
from dialogue.outbox_worker import OutboxWorker
from redis_client import close_redis_pool


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()
    if args.max_events < 0:
        raise SystemExit("--max-events 不能为负数")
    if not config.CHAT_OUTBOX_WORKER_ENABLED:
        raise SystemExit("CHAT_OUTBOX_WORKER_ENABLED 未启用，Outbox Worker 拒绝启动")
    config.validate_chat_v2_config()
    initialize_pools()
    ensure_schema()
    worker = OutboxWorker(
        args.worker_id.strip() or f"{socket.gethostname()}-{os.getpid()}-outbox"
    )
    try:
        if args.once or args.max_events > 0:
            maximum = 1 if args.once else args.max_events
            processed = 0
            while processed < maximum and worker.run_once():
                processed += 1
            print(json.dumps({"processed": processed}, ensure_ascii=False))
        else:
            await worker.run_forever()
    finally:
        close_pools()
        close_redis_pool()


if __name__ == "__main__":
    asyncio.run(main())
