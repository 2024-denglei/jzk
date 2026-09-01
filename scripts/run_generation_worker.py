"""运行独立持久 AI 生成 Worker。"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.pg import close_pools, ensure_schema, initialize_pools
from dialogue.generation_processor import AgentGenerationProcessor, FallbackGenerationProcessor
from dialogue.generation_worker import GenerationWorker
from dialogue.nlu import create_async_llm_client
from redis_client import close_redis_pool


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", default="")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker_id = args.worker_id.strip() or f"{socket.gethostname()}-{os.getpid()}-{str(uuid4())[:8]}"
    config.validate_chat_v2_config()
    initialize_pools()
    ensure_schema()
    processor = (
        AgentGenerationProcessor(create_async_llm_client())
        if config.LLM_API_KEY
        else FallbackGenerationProcessor()
    )
    worker = GenerationWorker(worker_id, processor)
    try:
        if args.once:
            await worker.run_once()
        else:
            await worker.run_forever()
    finally:
        close_pools()
        close_redis_pool()


if __name__ == "__main__":
    asyncio.run(main())
