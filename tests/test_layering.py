"""守住分层：依赖只能单向流动。

domain 曾直连 db，dialogue 曾为了调用 execute_match 去 import api，db.pg 曾为了
哈希引导密码去 import api.auth_utils。三次都靠函数内 lazy import 把环藏起来，问题
原样保留。这里检查的是源码文本，lazy import 也算违规。

导入统一为 `from jzk.X...` 之后，守卫看的是 `jzk.` 的第二段（db / api / chat 等），
而不是第一段——第一段全是 `jzk`，看了等于没看。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "backend" / "jzk"


def _production_py(*relative: str) -> list[Path]:
    base = PKG.joinpath(*relative)
    if base.is_file():
        return [base]
    return [
        path
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _imported_jzk_subpackages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            parts = module.split(".")
            if parts[0] == "jzk" and len(parts) > 1:
                names.add(parts[1])
    return names


def _offenders(paths: list[Path], forbidden: set[str]) -> list[str]:
    found: list[str] = []
    for path in paths:
        hit = _imported_jzk_subpackages(path) & forbidden
        if hit:
            found.append(f"{path.relative_to(ROOT)} → {sorted(hit)}")
    return found


def test_domain_does_not_import_outer_layers() -> None:
    """docs/adr/0002：domain 是纯领域层。db 可以依赖它的类型，反过来不行。"""
    offenders = _offenders(
        _production_py("domain"),
        {"db", "api", "chat", "advisor", "matching"},
    )
    assert not offenders, "domain 不得依赖外层：\n" + "\n".join(offenders)


def test_db_does_not_import_application_layers() -> None:
    offenders = _offenders(
        _production_py("db"),
        {"api", "chat", "advisor", "matching"},
    )
    assert not offenders, "db 不得依赖应用层：\n" + "\n".join(offenders)


def test_chat_does_not_import_api_or_advisor() -> None:
    """对话存储不得回头依赖 HTTP 或顾问生成。advisor → chat 单向。"""
    offenders = _offenders(_production_py("chat"), {"api", "advisor"})
    assert not offenders, "chat 不得 import api/advisor：\n" + "\n".join(offenders)


def test_advisor_does_not_import_api() -> None:
    """顾问与 HTTP 曾互相 import，环靠 lazy import 绕过。编排层就是为拆这个环。"""
    offenders = _offenders(_production_py("advisor"), {"api"})
    assert not offenders, "advisor 不得 import api：\n" + "\n".join(offenders)


def test_matching_does_not_import_api_chat_or_advisor() -> None:
    offenders = _offenders(
        _production_py("matching"),
        {"api", "chat", "advisor"},
    )
    assert not offenders, "编排层不得回头依赖 api/chat/advisor：\n" + "\n".join(
        offenders
    )


def test_execute_match_lives_in_the_orchestration_layer() -> None:
    source = (PKG / "matching" / "execute.py").read_text(encoding="utf-8")
    assert "def execute_match(" in source

    api_match = (PKG / "api" / "match.py").read_text(encoding="utf-8")
    assert "def execute_match(" not in api_match
    assert "from jzk.matching.execute import execute_match" in api_match

    advisor = (PKG / "advisor" / "generation_processor.py").read_text(
        encoding="utf-8"
    )
    assert "from jzk.matching.execute import execute_match" in advisor
    assert "from jzk.api.match import execute_match" not in advisor


def test_hard_filter_sql_is_not_generated_in_domain() -> None:
    assert not (PKG / "domain" / "preference" / "sql_filter.py").exists()
    sql_filter = (PKG / "db" / "hard_filter.py").read_text(encoding="utf-8")
    assert "def build_hard_filter_sql(" in sql_filter

    pipeline = (PKG / "domain" / "preference" / "pipeline.py").read_text(
        encoding="utf-8"
    )
    assert "build_hard_filter_sql" not in pipeline
    assert "SELECT *" not in pipeline


def test_auth_handlers_do_not_embed_sql() -> None:
    """handler 里出现 SQL 字符串，等于仓储层被绕开。"""
    for relative in ("api/auth.py", "api/user.py", "api/admin_auth.py"):
        source = (PKG / relative).read_text(encoding="utf-8")
        assert "SELECT " not in source, f"{relative} 仍含查询 SQL"
        assert "INSERT " not in source, f"{relative} 仍含写入 SQL"
        assert "UPDATE " not in source, f"{relative} 仍含更新 SQL"
        assert "DELETE " not in source, f"{relative} 仍含删除 SQL"


def test_old_top_level_layout_is_gone() -> None:
    """平铺在仓库根的包名不得再出现，否则 pythonpath 时代的导入会悄悄复活。"""
    for name in (
        "api",
        "core",
        "db",
        "dialogue",
        "matching",
        "models",
        "services",
        "voice",
        "web",
        "scripts",
        "main.py",
        "config.py",
    ):
        assert not (ROOT / name).exists(), f"仓库根仍残留 {name}"
