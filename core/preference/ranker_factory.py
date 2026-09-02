from __future__ import annotations

import threading

from core.preference.scorer import Ranker
from core.preference.scoring_client import HttpScoringRanker
from core.preference.scoring_contract import RankerUnavailable


_LOCK = threading.Lock()
_RANKER: Ranker | None = None
_CONFIG_KEY: tuple | None = None


def _settings_key(config) -> tuple:
    backend = str(getattr(config, "MATCH_SCORING_BACKEND", "http")).strip().lower()
    if backend == "local_v2":
        return (backend, getattr(config, "V2_CHECKPOINT_PATH", ""))
    return (
        backend,
        getattr(config, "MATCH_SCORER_URL", ""),
        getattr(config, "MATCH_SCORER_TOKEN", ""),
        getattr(config, "MATCH_SCORER_CONTRACT_VERSION", "1"),
        getattr(config, "MATCH_SCORER_TIMEOUT_SECONDS", 15.0),
        getattr(config, "MATCH_SCORER_MAX_CANDIDATES", 20000),
    )


def get_default_ranker() -> Ranker:
    import config

    global _RANKER, _CONFIG_KEY
    key = _settings_key(config)
    if _RANKER is not None and _CONFIG_KEY == key:
        return _RANKER
    with _LOCK:
        if _RANKER is not None and _CONFIG_KEY == key:
            return _RANKER
        backend = key[0]
        if backend == "local_v2":
            from core.preference.v2_ranker import (
                V2RankerUnavailable,
                get_default_ranker as get_v2_ranker,
            )

            try:
                ranker = get_v2_ranker()
            except V2RankerUnavailable as exc:
                raise RankerUnavailable(str(exc)) from exc
        elif backend == "http":
            ranker = HttpScoringRanker(
                base_url=config.MATCH_SCORER_URL,
                token=config.MATCH_SCORER_TOKEN,
                contract_version=config.MATCH_SCORER_CONTRACT_VERSION,
                timeout_seconds=config.MATCH_SCORER_TIMEOUT_SECONDS,
                max_candidates=config.MATCH_SCORER_MAX_CANDIDATES,
            )
        else:
            raise RankerUnavailable(f"未知匹配评分后端：{backend}")
        _RANKER = ranker
        _CONFIG_KEY = key
        return ranker


def reset_ranker_cache() -> None:
    global _RANKER, _CONFIG_KEY
    with _LOCK:
        _RANKER = None
        _CONFIG_KEY = None


def get_scoring_readiness() -> dict:
    """返回不含凭据的评分后端状态，失败时由调用方映射为 readiness 503。"""
    import config

    ranker = get_default_ranker()
    if config.MATCH_SCORING_BACKEND == "local_v2":
        return {"ok": True, "backend": "local_v2", "model": "v2"}
    model_info = getattr(ranker, "model_info", None)
    if not callable(model_info):  # pragma: no cover - factory guarantees HTTP type
        raise RankerUnavailable("评分后端不支持 readiness 探测")
    model = model_info()
    return {
        "ok": True,
        "backend": "http",
        "contract_version": config.MATCH_SCORER_CONTRACT_VERSION,
        "model": model.model_dump(),
    }
