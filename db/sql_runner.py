"""执行含 DO $$ 块的 SQL 脚本。"""

from __future__ import annotations

from pathlib import Path

import psycopg


def split_sql_statements(script: str) -> list[str]:
    """按分号拆分，感知单引号与 $tag$ 美元引号。"""
    stmts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    in_single = False
    dollar_tag: str | None = None

    while i < n:
        ch = script[i]
        if dollar_tag is not None:
            if script.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'" and i + 1 < n and script[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == "$":
            j = i + 1
            while j < n and (script[j].isalnum() or script[j] == "_"):
                j += 1
            if j < n and script[j] == "$":
                dollar_tag = script[i : j + 1]
                buf.append(dollar_tag)
                i = j + 1
                continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def run_sql_file(conn: psycopg.Connection, path: Path) -> None:
    script = path.read_text(encoding="utf-8")
    for stmt in split_sql_statements(script):
        # 跳过纯注释块
        body = "\n".join(
            line for line in stmt.splitlines() if not line.strip().startswith("--")
        ).strip()
        if not body:
            continue
        conn.execute(stmt)
