from jzk.db.donor_fields import DONOR_DB_COLUMNS, map_excel_columns
from jzk.db.donor_import import dataframe_to_donor_payloads
import pandas as pd


REMOVED = {
    "availability",
    "semen_test",
    "blood_test",
    "chromosome_test",
    "microbio_test",
    "remark",
}


def test_donor_db_columns_no_longer_include_removed_ops_fields():
    assert "specimen_count" in DONOR_DB_COLUMNS
    assert "status" in DONOR_DB_COLUMNS
    for name in REMOVED:
        assert name not in DONOR_DB_COLUMNS


def test_import_defaults_specimen_count_to_ten_without_availability():
    df = pd.DataFrame([{"代号": "T001", "学历": "硕士", "身高": 175}])
    payloads = dataframe_to_donor_payloads(df)
    assert len(payloads) == 1
    assert payloads[0]["code"] == "T001"
    assert payloads[0]["specimen_count"] == 10
    assert payloads[0]["status"] == "active"
    for name in REMOVED:
        assert name not in payloads[0]


def test_excel_headers_for_removed_fields_are_ignored():
    mapping = map_excel_columns(["代号", "是否可用", "精液检测", "备注", "标本数量"])
    assert mapping["代号"] == "code"
    assert mapping["标本数量"] == "specimen_count"
    assert "是否可用" not in mapping
    assert "精液检测" not in mapping
    assert "备注" not in mapping
