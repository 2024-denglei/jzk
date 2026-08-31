import pytest

import config


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    monkeypatch.setattr(config, "JWT_SECRET", "a" * 64)
    monkeypatch.setattr(config, "EXPOSE_TEST_VERIFICATION_CODE", False)
    monkeypatch.setattr(config, "ADMIN_BOOTSTRAP_USERNAME", "bootstrap-owner")
    monkeypatch.setattr(config, "ADMIN_BOOTSTRAP_PASSWORD", "a-secure-bootstrap-password")
    monkeypatch.setattr(config, "REDIS_URL", "rediss://jzk:secret@redis.internal:6379/0")


def test_development_allows_local_defaults(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "development")
    config.validate_security_config()


def test_production_accepts_explicit_secure_values(production):
    config.validate_security_config()


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("JWT_SECRET", "change-me-in-production", "JWT_SECRET"),
        ("JWT_SECRET", "too-short", "JWT_SECRET"),
        ("EXPOSE_TEST_VERIFICATION_CODE", True, "EXPOSE_TEST_VERIFICATION_CODE"),
        ("ADMIN_BOOTSTRAP_USERNAME", "admin", "管理员用户名"),
        ("ADMIN_BOOTSTRAP_PASSWORD", "Admin@ChangeMe1", "管理员引导密码"),
        ("REDIS_URL", "redis://redis.internal:6379/0", "Redis"),
    ],
)
def test_production_rejects_insecure_values(production, monkeypatch, attribute, value, message):
    monkeypatch.setattr(config, attribute, value)
    with pytest.raises(config.SecurityConfigError, match=message):
        config.validate_security_config()


def test_unknown_environment_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "prod")
    with pytest.raises(config.SecurityConfigError, match="ENVIRONMENT"):
        config.validate_security_config()
