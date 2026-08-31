"""应用级共享 Redis 连接池。"""

from __future__ import annotations

from threading import Lock

import redis

import config

_pool: redis.ConnectionPool | None = None
_pool_lock = Lock()


def get_redis_client() -> redis.Redis:
    """返回使用同一受限连接池的轻量客户端。"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = redis.ConnectionPool.from_url(
                    config.REDIS_URL,
                    decode_responses=True,
                    max_connections=config.REDIS_MAX_CONNECTIONS,
                    socket_connect_timeout=config.REDIS_CONNECT_TIMEOUT_SECONDS,
                    socket_timeout=config.REDIS_SOCKET_TIMEOUT_SECONDS,
                    health_check_interval=config.REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
                )
    return redis.Redis(connection_pool=_pool)


def close_redis_pool() -> None:
    global _pool
    with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        pool.disconnect()
