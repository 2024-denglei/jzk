from __future__ import annotations

from core.preference.schema import FIELD_REGISTRY, EnumAttr, KeywordAttr, PreferenceProfile, RangeAttr


def escape_like(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _age_sql() -> str:
    return "(EXTRACT(YEAR FROM AGE(CURRENT_DATE, birth_date)))"


def build_hard_filter_sql(profile: PreferenceProfile) -> tuple[str, tuple]:
    clauses = ["status = %s"]
    params: list = ["active"]
    for field, attr in profile.attributes.items():
        if attr.constraint != "must":
            continue
        spec = FIELD_REGISTRY[field]
        if isinstance(attr, RangeAttr):
            col = _age_sql() if field == "age" else spec.db_column
            if attr.range.min is not None:
                clauses.append(f"{col} >= %s")
                params.append(attr.range.min)
            if attr.range.max is not None:
                clauses.append(f"{col} <= %s")
                params.append(attr.range.max)
        elif isinstance(attr, EnumAttr):
            if field == "rh_blood":
                col = (
                    "CASE WHEN rh_blood IN ('+', '阳性') THEN '阳性' "
                    "WHEN rh_blood IN ('-', '阴性') THEN '阴性' ELSE rh_blood END"
                )
            else:
                col = spec.db_column
            placeholders = ", ".join(["%s"] * len(attr.values))
            clauses.append(f"{col} IN ({placeholders})")
            params.extend(attr.values)
        elif isinstance(attr, KeywordAttr):
            likes = []
            for kw in attr.keywords:
                likes.append(f"{spec.db_column} ILIKE %s ESCAPE '\\'")
                params.append("%" + escape_like(kw) + "%")
            joiner = " AND " if attr.match == "all" else " OR "
            clauses.append("(" + joiner.join(likes) + ")")
    sql = "SELECT * FROM donor.donors WHERE " + " AND ".join(clauses)
    return sql, tuple(params)


def diagnose_bottlenecks(profile: PreferenceProfile, count_fn) -> list[dict]:
    must_fields = [f for f, a in profile.attributes.items() if a.constraint == "must"]
    results = []
    for field in must_fields:
        clone = profile.model_copy(deep=True)
        clone.attributes[field].constraint = "prefer"
        sql, params = build_hard_filter_sql(clone)
        recovered = int(count_fn(sql, params))
        results.append({"field": field, "recovered": recovered})
    results.sort(key=lambda x: x["recovered"], reverse=True)
    return results
