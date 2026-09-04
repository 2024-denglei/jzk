import asyncio
from types import SimpleNamespace

import numpy as np
import pandas as pd

from jzk.api import admin as admin_mod
from jzk.domain.screening import hard_filter, match_with_relaxation
from jzk.domain.runtime_cache import update_donor_status_cache


ADMIN = {"id": 9, "username": "admin", "display_name": "张管理员"}


def test_status_endpoint_uses_incremental_cache_update(monkeypatch):
    calls = []
    monkeypatch.setattr(
        admin_mod,
        "set_donor_status",
        lambda code, status, operator_id: {
            "id": 1,
            "code": code,
            "status": status,
            "specimen_count": 10,
        },
    )
    monkeypatch.setattr(
        admin_mod,
        "update_donor_status_cache",
        lambda app, code, status: calls.append((app, code, status)) or True,
    )
    monkeypatch.setattr(admin_mod, "refresh_donor_cache", lambda _app: (_ for _ in ()).throw(AssertionError("不应重建完整缓存")))
    app = SimpleNamespace()
    request = SimpleNamespace(app=app)

    result = asyncio.run(
        admin_mod.admin_set_status(
            "A2620000",
            admin_mod.StatusBody(status="disabled"),
            request,
            ADMIN,
        )
    )

    assert result["status"] == "disabled"
    assert calls == [(app, "A2620000", "disabled")]


def test_incremental_status_cache_keeps_encoder_and_updates_dataframe():
    encoder = SimpleNamespace(feature_matrix=np.zeros((2, 3)))
    original = pd.DataFrame({"代号": ["A1", "A2"], "状态": ["active", "active"]})
    state = SimpleNamespace(donor_df=original, encoder=encoder)
    app = SimpleNamespace(state=state)

    assert update_donor_status_cache(app, "A2", "disabled") is True
    assert app.state.encoder is encoder
    assert encoder.df is app.state.donor_df
    assert app.state.donor_df.loc[1, "状态"] == "disabled"
    assert original.loc[1, "状态"] == "active"


def test_disabled_donor_is_never_returned_when_preferences_relax():
    donors = pd.DataFrame({
        "状态": ["disabled", "active"],
        "学历": ["博士", "本科"],
        "ABO血型": ["A", "O"],
        "身高": [185, 175],
    })
    scores = np.array([0.99, 0.1])

    mask = hard_filter(donors, {}, {})
    candidates, _level, _relaxed = match_with_relaxation(donors, {}, scores, top_k=10, threshold=1.1)

    assert mask.tolist() == [False, True]
    assert [index for index, _score in candidates] == [1]


def test_audit_api_preserves_operator_name(monkeypatch):
    monkeypatch.setattr(
        admin_mod,
        "list_audit",
        lambda **_kwargs: ([{
            "id": 1,
            "donor_code": "A1",
            "action": "disable",
            "operator_id": 9,
            "operator_name": "张管理员",
            "created_at": "2026-08-31T12:00:00+00:00",
        }], 1),
    )

    result = asyncio.run(admin_mod.admin_audit(admin=ADMIN))

    assert result["items"][0]["operator_name"] == "张管理员"
