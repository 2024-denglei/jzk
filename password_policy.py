"""用户与管理员密码强度规则。"""

from __future__ import annotations

import re

_COMMON_PASSWORDS = {
    "1234567890",
    "123456789012",
    "admin123456",
    "admin12345678",
    "letmein123",
    "password123",
    "password1234",
    "qwerty1234",
    "qwertyuiop",
}


def validate_password_strength(password: str, *, admin: bool = False) -> str:
    """拒绝常见、重复和复杂度不足的密码，返回原值供 Pydantic 使用。"""
    normalized = password.strip().lower()
    if normalized in _COMMON_PASSWORDS:
        raise ValueError("密码过于常见，请使用更难猜测的密码")
    if len(set(normalized)) <= 3:
        raise ValueError("密码包含过多重复字符")

    categories = sum(
        bool(re.search(pattern, password))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
    required = 3 if admin else 2
    if categories < required:
        raise ValueError(f"密码至少需要包含 {required} 类字符：大小写字母、数字或符号")
    return password
