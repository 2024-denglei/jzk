"""守住 ADR 0006：当前结构写在 Markdown 里，不再用 HTTP 端点发布手画图。"""

from __future__ import annotations

from pathlib import Path

from jzk.main import app

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_architecture_endpoint_is_gone() -> None:
    source = (ROOT / "backend" / "jzk" / "main.py").read_text(encoding="utf-8")
    assert "/architecture" not in source
    assert "docs-static" not in source
    assert "/architecture" not in app.openapi()["paths"]


def test_hand_drawn_architecture_diagrams_are_gone() -> None:
    for name in (
        "architecture.html",
        "architecture_agent.svg",
        "architecture_v2.svg",
        "research_architecture.html",
        "research_architecture.svg",
        "chat-v2-architecture.html",
        "chat-v2-architecture.md",
    ):
        assert not (DOCS / name).exists(), f"过期架构图仍在 docs/：{name}"


def test_live_architecture_doc_names_current_packages() -> None:
    text = (DOCS / "architecture.md").read_text(encoding="utf-8")
    for token in (
        "jzk.domain",
        "jzk.matching",
        "jzk.scorer",
        "frontend/client",
        "frontend/admin",
        "frontend/shared",
    ):
        assert token in text, f"docs/architecture.md 未提到当前结构：{token}"
    assert (DOCS / "conversation.md").is_file()


def test_historical_plans_live_in_archive() -> None:
    assert not (DOCS / "superpowers").exists()
    assert not (DOCS / "结构收敛计划.md").exists()
    archive = DOCS / "archive"
    assert (archive / "README.md").is_file()
    assert (archive / "结构收敛计划.md").is_file()
    assert any((archive / "plans").glob("*.md"))
    assert any((archive / "specs").glob("*.md"))
