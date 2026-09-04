"""守住 ADR 0005：管理端源码不得打进客户端，契约生成物必须在 shared。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_frontend_is_three_npm_workspaces() -> None:
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert set(pkg["workspaces"]) == {"shared", "client", "admin"}
    assert (FRONTEND / "shared" / "package.json").is_file()
    assert (FRONTEND / "client" / "package.json").is_file()
    assert (FRONTEND / "admin" / "package.json").is_file()


def test_client_source_does_not_contain_admin_modules() -> None:
    """懒加载解决不了管理端源码下发；拆成两个应用后客户端目录里不该再有它。"""
    client_src = FRONTEND / "client" / "src"
    assert not (client_src / "pages" / "AdminPage.tsx").exists()
    assert not (client_src / "pages" / "admin").exists()

    offenders = [
        path.relative_to(ROOT)
        for path in client_src.rglob("*")
        if path.suffix in {".ts", ".tsx", ".mjs"}
        and "AdminPage" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"客户端仍引用管理端入口：{offenders}"


def test_admin_source_does_not_import_client_modules() -> None:
    """管理端不得再从客户端 features/ 取运行时代码。共享只走 @jzk/shared。"""
    admin_src = FRONTEND / "admin" / "src"
    forbidden = (
        "features/chat",
        "context/AuthContext",
        "lib/api",
        "@jzk/client",
    )
    offenders = []
    for path in admin_src.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".mjs"}:
            continue
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        if hits:
            offenders.append(f"{path.relative_to(ROOT)} → {hits}")
    assert not offenders, "管理端跨包导入了客户端模块：\n" + "\n".join(offenders)


def test_generated_contract_lives_in_shared() -> None:
    shared = FRONTEND / "shared"
    assert (shared / "openapi.json").is_file()
    assert (shared / "openapi.d.ts").is_file()
    index = (shared / "index.ts").read_text(encoding="utf-8")
    assert "openapi" in index
    assert "ChatSummary" in index or "ChatV2Summary" in index
    extra = {
        path.name
        for path in shared.iterdir()
        if path.name not in {
            "package.json",
            "index.ts",
            "openapi.json",
            "openapi.d.ts",
            "node_modules",
        }
    }
    assert not extra, f"shared 只应放生成契约，多出来的文件：{extra}"


def test_backend_mounts_two_spa_entrypoints() -> None:
    source = (ROOT / "backend" / "jzk" / "main.py").read_text(encoding="utf-8")
    assert '"/admin"' in source
    assert "frontend" in source and "client" in source and "admin" in source
    assert "admin-assets" in source
    assert "client-assets" in source
