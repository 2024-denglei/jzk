from __future__ import annotations

from typing import Any

from core.data_loader import _calc_age
from core.preference.schema import EnumAttr, KeywordAttr, PreferenceProfile, RangeAttr
from core.preference.scorer import normalize_rh


def profile_to_v2_spec(profile: PreferenceProfile) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for name, attr in profile.attributes.items():
        if isinstance(attr, RangeAttr):
            attributes[name] = {
                "type": "range",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "range": {"min": attr.range.min, "max": attr.range.max},
            }
        elif isinstance(attr, EnumAttr):
            attributes[name] = {
                "type": "enum",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "values": list(attr.values),
            }
        elif isinstance(attr, KeywordAttr):
            attributes[name] = {
                "type": "keyword",
                "constraint": attr.constraint,
                "weight": float(attr.weight),
                "keywords": list(attr.keywords),
                "match_mode": attr.match,
            }
        else:
            raise TypeError(f"unsupported attr for {name}")
    return {"schema_version": profile.schema_version, "attributes": attributes}


def donor_row_to_v2(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    age = _calc_age(row.get("birth_date") or row.get("age"))
    out["age"] = age if age else row.get("age")
    if "rh_blood" in out:
        out["rh_blood"] = normalize_rh(out.get("rh_blood"))
    return out
