from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jzk import config

_FORBIDDEN = ("status", "serial_no", "code")


def _log_dir() -> Path:
    env = os.getenv("MATCH_LOG_DIR")
    if env:
        return Path(env)
    default = getattr(config, "MATCH_LOG_DIR", None)
    if default:
        return Path(default)
    return Path(__file__).resolve().parents[2] / "data" / "match_logs"


def _strip_forbidden(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_forbidden(v) for k, v in obj.items() if k not in _FORBIDDEN}
    if isinstance(obj, list):
        return [_strip_forbidden(x) for x in obj]
    return obj


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def _append(filename: str, payload: dict[str, Any]) -> None:
    directory = _log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **_strip_forbidden(payload)}
    path = directory / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")


def append_match_turn(payload: dict[str, Any]) -> None:
    _append("turns.jsonl", payload)


def append_feedback_event(payload: dict[str, Any]) -> None:
    _append("events.jsonl", payload)
