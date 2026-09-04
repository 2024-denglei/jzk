from jzk.domain.preference.validate import parse_profile
from jzk.db.hard_filter import build_hard_filter_sql, escape_like


def test_prefer_height_not_in_where():
    p = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {"constraint": "prefer", "weight": 0.9, "range": {"min": 175}},
            "abo_blood": {"constraint": "must", "weight": 1.0, "values": ["O"]},
        },
    })
    sql, params = build_hard_filter_sql(p)
    assert "height_cm" not in sql
    assert "abo_blood" in sql
    assert "status" in sql
    assert "active" in params
    assert "O" in params


def test_must_height_in_where():
    p = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "height_cm": {"constraint": "must", "weight": 1.0, "range": {"min": 175}},
        },
    })
    sql, params = build_hard_filter_sql(p)
    assert "height_cm >=" in sql.replace("  ", " ")
    assert 175 in params


def test_keyword_percent_escaped():
    assert "%" in escape_like("100%")
    p = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "occupation": {
                "constraint": "must",
                "weight": 1.0,
                "keywords": ["100%"],
                "match": "any",
            },
        },
    })
    sql, params = build_hard_filter_sql(p)
    assert "ILIKE" in sql.upper()
    assert "ESCAPE" in sql.upper()
    assert "%" + escape_like("100%") + "%" in params


def test_no_must_only_active():
    p = parse_profile({"schema_version": "1.0", "attributes": {
        "education": {"constraint": "prefer", "weight": 0.5, "values": ["硕士"]},
    }})
    sql, params = build_hard_filter_sql(p)
    assert "education" not in sql
    assert params == ("active",)


def test_bottleneck_orders_by_recovered_count():
    from jzk.domain.preference.pipeline import diagnose_bottlenecks

    profile = parse_profile({
        "schema_version": "1.0",
        "attributes": {
            "abo_blood": {"constraint": "must", "weight": 1, "values": ["O"]},
            "rh_blood": {"constraint": "must", "weight": 1, "values": ["阴性"]},
        },
    })

    def fake_count(clone):
        must_values = []
        for attr in clone.attributes.values():
            if attr.constraint == "must":
                must_values.extend(getattr(attr, "values", None) or [])
        if "阴性" in must_values:
            return 0
        if "O" in must_values:
            return 10
        return 100

    out = diagnose_bottlenecks(profile, fake_count)
    assert out[0]["field"] == "rh_blood"
    assert out[0]["recovered"] == 10
    assert out[1]["field"] == "abo_blood"
