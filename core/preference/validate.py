from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from core.preference.schema import (
    BLOCKED_FIELDS,
    FIELD_REGISTRY,
    EnumAttr,
    KeywordAttr,
    PreferenceProfile,
    RangeAttr,
)

__all__ = ["ProfileValidationError", "parse_profile", "PreferenceProfile"]


class ProfileValidationError(ValueError):
    pass


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
                raise ProfileValidationError(f"unknown or blocked field: {name}")
            if not isinstance(payload, dict):
                raise ProfileValidationError(f"{name} must be an object")
            spec = FIELD_REGISTRY[name]
            if spec.kind == "range":
                attr = RangeAttr.model_validate(payload)
            elif spec.kind == "enum":
                attr = EnumAttr.model_validate(payload)
                attr.check_enums(spec.enums)
            else:
                attr = KeywordAttr.model_validate(payload)
            parsed[name] = attr
        profile = PreferenceProfile(schema_version="1.0", attributes=parsed)
    except (ValidationError, ValueError) as e:
        if isinstance(e, ProfileValidationError):
            raise
        raise ProfileValidationError(str(e)) from e
    if profile.attributes:
        if all(a.weight == 0 for a in profile.attributes.values()):
            raise ProfileValidationError("all weights are 0")
    return profile
