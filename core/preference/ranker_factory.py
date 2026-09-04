"""构造访问打分能力的唯一入口。

按 docs/adr/0001，`services/match_scorer/` 是唯一的打分权威，因此这里只有一种
后端。打分服务不可用时抛 `RankerUnavailable`，由调用方映射成 503——不存在退回
进程内推理的降级路径，那会让线上悄悄用另一套权重出结果。
"""

from __future__ import annotations

import threading

from core.preference.scoring_client import HttpScoringRanker


_LOCK = threading.Lock()
_RANKER: HttpScoringRanker | None = None
_CONFIG_KEY: tuple | None = None


def _settings_key(config) -> tuple:
    return (
        getattr(config, "MATCH_SCORER_URL", ""),
        getattr(config, "SCORER_TOKEN", ""),
        getattr(config, "MATCH_SCORER_CONTRACT_VERSION", "1"),
        getattr(config, "MATCH_SCORER_TIMEOUT_SECONDS", 15.0),
        getattr(config, "MATCH_SCORER_MAX_CANDIDATES", 20000),
    )


def get_default_ranker() -> HttpScoringRanker:
    import config

    global _RANKER, _CONFIG_KEY
    key = _settings_key(config)
    if _RANKER is not None and _CONFIG_KEY == key:
        return _RANKER
    with _LOCK:
        if _RANKER is not None and _CONFIG_KEY == key:
            return _RANKER
        _RANKER = HttpScoringRanker(
            base_url=config.MATCH_SCORER_URL,
            token=config.SCORER_TOKEN,
            contract_version=config.MATCH_SCORER_CONTRACT_VERSION,
            timeout_seconds=config.MATCH_SCORER_TIMEOUT_SECONDS,
            max_candidates=config.MATCH_SCORER_MAX_CANDIDATES,
        )
        _CONFIG_KEY = key
        return _RANKER


def reset_ranker_cache() -> None:
    global _RANKER, _CONFIG_KEY
    with _LOCK:
        _RANKER = None
        _CONFIG_KEY = None


def get_scoring_readiness() -> dict:
    """返回不含凭据的评分后端状态，失败时由调用方映射为 readiness 503。"""
    import config

    ranker = get_default_ranker()
    return {
        "ok": True,
        "backend": "http",
        "contract_version": config.MATCH_SCORER_CONTRACT_VERSION,
        "model": ranker.model_info().model_dump(),
    }
