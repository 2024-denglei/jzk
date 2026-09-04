"""守住分层：依赖只能单向流动。

core 曾直连 db，dialogue 曾为了调用 execute_match 去 import api.match，db.pg 曾为了
哈希引导密码去 import api.auth_utils。三次都靠函数内 lazy import 把环藏起来，问题
原样保留。这里检查的是源码文本，lazy import 也算违规。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _production_py(*relative: str) -> list[Path]:
    base = ROOT.joinpath(*relative)
    if base.is_file():
        return [base]
    return [
        path
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def _offenders(paths: list[Path], forbidden: set[str]) -> list[str]:
    found: list[str] = []
    for path in paths:
        hit = _imported_modules(path) & forbidden
        if hit:
            found.append(f"{path.relative_to(ROOT)} → {sorted(hit)}")
    return found


def test_core_does_not_import_db_or_api() -> None:
    """docs/adr/0002：core 是纯领域层。db 可以依赖它的类型，反过来不行。"""
    offenders = _offenders(_production_py("core"), {"db", "api", "dialogue", "matching"})
    assert not offenders, "core 不得依赖外层：\n" + "\n".join(offenders)


def test_db_does_not_import_api_or_dialogue() -> None:
    offenders = _offenders(_production_py("db"), {"api", "dialogue", "matching"})
    assert not offenders, "db 不得依赖应用层：\n" + "\n".join(offenders)


def test_dialogue_does_not_import_api() -> None:
    """对话生成与 HTTP 曾互相 import，环靠 lazy import 绕过。编排层就是为拆这个环。"""
    offenders = _offenders(_production_py("dialogue"), {"api"})
    assert not offenders, "dialogue 不得 import api：\n" + "\n".join(offenders)


def test_matching_does_not_import_api_or_dialogue() -> None:
    offenders = _offenders(_production_py("matching"), {"api", "dialogue"})
    assert not offenders, "编排层不得回头依赖 api/dialogue：\n" + "\n".join(offenders)


def test_execute_match_lives_in_the_orchestration_layer() -> None:
    source = (ROOT / "matching" / "execute.py").read_text(encoding="utf-8")
    assert "def execute_match(" in source

    api_match = (ROOT / "api" / "match.py").read_text(encoding="utf-8")
    assert "def execute_match(" not in api_match
    assert "from matching.execute import execute_match" in api_match

    dialogue = (ROOT / "dialogue" / "generation_processor.py").read_text(
        encoding="utf-8"
    )
    assert "from matching.execute import execute_match" in dialogue
    assert "from api.match import execute_match" not in dialogue


def test_hard_filter_sql_is_not_generated_in_core() -> None:
    assert not (ROOT / "core" / "preference" / "sql_filter.py").exists()
    sql_filter = (ROOT / "db" / "hard_filter.py").read_text(encoding="utf-8")
    assert "def build_hard_filter_sql(" in sql_filter

    pipeline = (ROOT / "core" / "preference" / "pipeline.py").read_text(
        encoding="utf-8"
    )
    assert "build_hard_filter_sql" not in pipeline
    assert "SELECT *" not in pipeline


def test_auth_handlers_do_not_embed_sql() -> None:
    """handler 里出现 SQL 字符串，等于仓储层被绕开。"""
    for relative in ("api/auth.py", "api/user.py", "api/admin_auth.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "SELECT " not in source, f"{relative} 仍含查询 SQL"
        assert "INSERT " not in source, f"{relative} 仍含写入 SQL"
        assert "UPDATE " not in source, f"{relative} 仍含更新 SQL"
        assert "DELETE " not in source, f"{relative} 仍含删除 SQL"
