from dataclasses import replace

import pytest

from jzk.domain.preference.match_snapshot import (
    MatchSnapshotValidationError,
    SNAPSHOT_DONOR_KEYS,
    build_match_snapshot_item,
    validate_match_snapshot_item,
)
from jzk.domain.preference.scorer import FieldScore


def test_snapshot_freezes_only_public_card_fields_and_explanation():
    row = {
        "id": 91,
        "code": "D091",
        "education": "硕士",
        "height_cm": 178,
        "abo_blood": "O",
        "status": "active",
        "personal_disease": "不得进入快照",
        "genetic_history": "不得进入快照",
    }
    parts = [
        FieldScore(
            field="height_cm",
            s=1.0,
            weight=1.0,
            constraint="prefer",
            actual=178,
            target={"min": 175},
        )
    ]
    item = build_match_snapshot_item(
        row,
        donor_id=91,
        rank=1,
        score=0.92345678,
        parts=parts,
    )

    assert set(item.donor_snapshot) == SNAPSHOT_DONOR_KEYS
    assert item.donor_snapshot["code"] == "D091"
    assert "personal_disease" not in item.donor_snapshot
    assert item.match_explanation["field_match"]["height_cm"]["actual"] == 178
    assert item.score == 0.923457


def test_snapshot_validator_rejects_private_or_unknown_donor_fields():
    item = build_match_snapshot_item(
        {"id": 1, "code": "D1", "status": "active"},
        donor_id=1,
        rank=1,
        score=1.0,
        parts=[],
    )
    unsafe = replace(item, donor_snapshot={**item.donor_snapshot, "std_history": "secret"})
    with pytest.raises(MatchSnapshotValidationError, match="未授权字段"):
        validate_match_snapshot_item(unsafe)
