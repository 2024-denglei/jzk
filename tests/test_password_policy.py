import pytest
from pydantic import ValidationError

from api.admin import AdminPasswordBody
from api.admin_admins import AdminCreateBody
from api.auth import RegisterRequest, ResetPasswordRequest


def test_user_password_rejects_common_password():
    with pytest.raises(ValidationError, match="密码过于常见"):
        RegisterRequest(
            email="user@example.com",
            phone="13800138000",
            password="password123",
            code="123456",
        )


def test_user_password_accepts_long_passphrase():
    body = ResetPasswordRequest(
        phone="13800138000",
        code="123456",
        new_password="long-password-2026",
    )
    assert body.new_password == "long-password-2026"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AdminPasswordBody(old_password="old", new_password="onlylowercase"),
        lambda: AdminCreateBody(
            username="operator",
            password="123456789012",
            display_name="运营管理员",
        ),
    ],
)
def test_admin_password_requires_stronger_secret(factory):
    with pytest.raises(ValidationError):
        factory()
