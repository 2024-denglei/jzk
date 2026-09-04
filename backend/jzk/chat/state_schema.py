"""长期消息状态快照的版本校验与升级入口。"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import ValidationError

from jzk.db.chat_contracts import DialogueStateSnapshotV1, STATE_SCHEMA_VERSION


class StateSchemaError(ValueError):
    pass


class StateNotRecoverable(StateSchemaError):
    pass


def empty_state() -> dict[str, Any]:
    return DialogueStateSnapshotV1().model_dump(mode="json")


def load_state(
    value: Mapping[str, Any] | None,
    *,
    schema_version: int | None = None,
    recoverable: bool = True,
) -> DialogueStateSnapshotV1:
    if not recoverable:
        raise StateNotRecoverable("该历史节点没有可靠状态，不能从此处继续")
    payload = dict(value or {})
    version = int(schema_version or payload.get("state_schema_version") or STATE_SCHEMA_VERSION)
    payload.setdefault("state_schema_version", version)
    if version != STATE_SCHEMA_VERSION:
        raise StateSchemaError(f"暂不支持状态版本 {version}")
    try:
        return DialogueStateSnapshotV1.model_validate(payload)
    except ValidationError as exc:
        raise StateSchemaError("对话状态快照格式无效") from exc


def dump_state(value: DialogueStateSnapshotV1 | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, DialogueStateSnapshotV1):
        return value.model_dump(mode="json")
    return load_state(value).model_dump(mode="json")
