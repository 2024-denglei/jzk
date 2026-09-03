#!/usr/bin/env python3
"""测量顾问 Agent 固定上下文的 prompt_tokens（需配置 LLM_API_KEY）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from dialogue.agent_tools import (
    AGENT_SYSTEM_PROMPT,
    SUBMIT_PROFILE_EXTENDED_TOOL,
    SUBMIT_PROFILE_TOOL,
    build_preference_snapshot_message,
)


def _usage_prompt_tokens(client, *, messages, tools=None) -> int:
    kwargs = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "max_tokens": 1,
        "temperature": 0,
    }
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    response = client.chat.completions.create(**kwargs)
    return int(response.usage.prompt_tokens)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user",
        default="必须 O 型",
        help="用于测量的短用户句",
    )
    args = parser.parse_args()
    if not config.LLM_API_KEY:
        print("LLM_API_KEY 未配置，跳过真实 token 测量", file=sys.stderr)
        return 2

    from openai import OpenAI

    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    snapshot = build_preference_snapshot_message(None)
    rows = [
        ("system_only", [{"role": "system", "content": AGENT_SYSTEM_PROMPT}], None),
        (
            "typical_core_path",
            [
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                snapshot,
                {"role": "user", "content": args.user},
            ],
            [SUBMIT_PROFILE_TOOL],
        ),
        (
            "extended_path",
            [
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                snapshot,
                {"role": "user", "content": "不要抽烟的"},
            ],
            [SUBMIT_PROFILE_EXTENDED_TOOL],
        ),
    ]
    results = {}
    for name, messages, tools in rows:
        results[name] = _usage_prompt_tokens(client, messages=messages, tools=tools)
        print(f"{name}: {results[name]}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    # 常见路径（仅核心工具）应明显低于改前 ~11864 基线
    if results.get("typical_core_path", 0) >= 10000:
        print("警告: typical_core_path 未明显下降", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
