#!/usr/bin/env python3
"""把当前 FastAPI 应用的 OpenAPI 契约写到 frontend/shared/openapi.json。"""

from __future__ import annotations

import json
from pathlib import Path

from jzk.main import app

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "frontend" / "shared" / "openapi.json"


def dump_openapi() -> dict:
    return app.openapi()


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(dump_openapi(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
