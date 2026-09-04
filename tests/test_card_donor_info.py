from jzk.domain.data_loader import to_card_donor_info

CARD_KEYS = {
    "id",
    "code",
    "education",
    "height",
    "blood_type",
    "age",
    "ethnicity",
    "hometown",
    "figure",
    "personality",
    "occupation",
    "specimen_count",
    "status",
}

REMOVED_KEYS = (
    "availability",
    "semen_test",
    "blood_test",
    "chromosome_test",
    "microbio_test",
    "remark",
    "genetic_history",
    "std_history",
    "personal_disease",
    "rh_blood",
    "weight",
    "hobby_sports",
)


def test_to_card_donor_info_keeps_only_card_keys():
    full = {
        "id": "D01",
        "code": "D01",
        "education": "硕士",
        "height": 178,
        "blood_type": "O",
        "age": 28,
        "ethnicity": "汉族",
        "hometown": "四川",
        "figure": "一般",
        "personality": "开朗",
        "occupation": "工程师",
        "specimen_count": 12,
        "status": "active",
        "availability": "可用",
        "semen_test": "正常",
        "genetic_history": "无",
        "std_history": "无",
        "personal_disease": "无",
        "rh_blood": "阳性",
        "weight": 70,
        "hobby_sports": "有",
    }
    card = to_card_donor_info(full)
    assert set(card.keys()) == CARD_KEYS
    assert card["code"] == "D01"
    assert card["education"] == "硕士"
    assert card["specimen_count"] == 12
    assert card["status"] == "active"
    for key in REMOVED_KEYS:
        assert key not in card


def test_card_selectable_uses_status_not_availability():
    """卡片可选状态由 status 决定：active=可选择，disabled=已停用。"""
    active = to_card_donor_info({"code": "A", "status": "active", "specimen_count": 10})
    disabled = to_card_donor_info({"code": "B", "status": "disabled", "specimen_count": 10})
    assert active["status"] == "active"
    assert disabled["status"] == "disabled"
