"""守住前后端契约：提交的 OpenAPI 必须等于当前应用实际暴露的那份。

少了这一步，openapi-typescript 生成的类型会跟着一份过期的 JSON 走，后端改了
响应形状既不报错也没有堆栈，只表现为前端按旧字段读到 undefined。
"""

from __future__ import annotations

import json
from pathlib import Path

from jzk.main import app

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "frontend" / "shared" / "openapi.json"


def test_committed_openapi_matches_the_live_app() -> None:
    live = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert COMMITTED.is_file(), "缺少 frontend/shared/openapi.json，请运行 backend/scripts/export_openapi.py"
    committed = COMMITTED.read_text(encoding="utf-8")
    assert committed == live, (
        "提交的 OpenAPI 与当前应用不一致。请运行 "
        "`uv run --locked --directory backend python scripts/export_openapi.py` "
        "后重新生成 frontend/shared/openapi.d.ts"
    )


def test_chat_contract_models_are_in_the_openapi_schema() -> None:
    """对话查询已经有 Pydantic 视图；不挂到路由上，生成的 TS 就看不到它们。"""
    schemas = app.openapi()["components"]["schemas"]
    for name in (
        "ChatSummary",
        "BranchSummary",
        "ChatMessageView",
        "ConversationTreeView",
        "ChatListPage",
        "MessagePathPage",
        "TurnCommand",
        "TurnCreationResult",
        "GenerationRunView",
        "MessageFeedbackView",
    ):
        assert name in schemas, f"OpenAPI 缺少 {name}，对话契约无法生成到 frontend/shared"


def test_spa_shell_is_not_part_of_the_http_contract() -> None:
    """HTML 回退随 dist 是否存在而注册不同路由；写进 OpenAPI 会让 CI 与本地对不上。"""
    paths = app.openapi()["paths"]
    for path in ("/", "/{full_path}", "/admin", "/admin/{full_path}"):
        assert path not in paths, f"SPA 入口 {path} 不应出现在 OpenAPI 契约里"
