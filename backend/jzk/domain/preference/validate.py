from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jzk.domain.preference.schema import (
    BLOCKED_FIELDS,
    FIELD_REGISTRY,
    EnumAttr,
    KeywordAttr,
    PreferenceProfile,
    RangeAttr,
)

__all__ = ["ProfileValidationError", "parse_profile", "PreferenceProfile"]


class ProfileValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        allowed_values: list[str] | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.allowed_values = list(allowed_values) if allowed_values else None


def _format_pydantic_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc") or [])
            msg = err.get("msg") or str(err)
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "；".join(parts) if parts else str(exc)
    return str(exc)


def parse_profile(raw: dict[str, Any]) -> PreferenceProfile:
    if not isinstance(raw, dict):
        raise ProfileValidationError("profile must be an object")
    try:
        version = raw.get("schema_version")
        attrs_in = raw.get("attributes")
        if version != "1.0":
            raise ProfileValidationError("schema_version must be 1.0")
        if not isinstance(attrs_in, dict):
            raise ProfileValidationError("attributes must be an object")
        parsed: dict[str, RangeAttr | EnumAttr | KeywordAttr] = {}
        for name, payload in attrs_in.items():
            if name in BLOCKED_FIELDS or name not in FIELD_REGISTRY:
                raise ProfileValidationError(
                    f"未知或禁止字段: {name}。"
                    f"允许字段: {', '.join(sorted(FIELD_REGISTRY))}。"
                    f"禁止: {', '.join(sorted(BLOCKED_FIELDS))}",
                    field=name,
                )
            if not isinstance(payload, dict):
                raise ProfileValidationError(
                    f"{name} must be an object",
                    field=name,
                )
            spec = FIELD_REGISTRY[name]
            if spec.kind == "range":
                attr = RangeAttr.model_validate(payload)
            elif spec.kind == "enum":
                attr = EnumAttr.model_validate(payload)
                try:
                    attr.check_enums(spec.enums)
                except ValueError:
                    raise ProfileValidationError(
                        f"{name}: 取值非法 {payload.get('values')}。"
                        f"该字段是枚举，允许值：{list(spec.enums)}",
                        field=name,
                        allowed_values=list(spec.enums),
                    )
            else:
                attr = KeywordAttr.model_validate(payload)
            parsed[name] = attr
        profile = PreferenceProfile(schema_version="1.0", attributes=parsed)
    except (ValidationError, ValueError) as e:
        if isinstance(e, ProfileValidationError):
            raise
        raise ProfileValidationError(_format_pydantic_error(e)) from e
    if profile.attributes:
        if all(a.weight == 0 for a in profile.attributes.values()):
            raise ProfileValidationError("all weights are 0")
    return profile
