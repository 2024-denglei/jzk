import pytest

import config


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    monkeypatch.setattr(config, "JWT_SECRET", "a" * 64)
    monkeypatch.setattr(config, "RATE_LIMIT_PEPPER", "b" * 64)
    monkeypatch.setattr(config, "EXPOSE_TEST_VERIFICATION_CODE", False)
    monkeypatch.setattr(config, "ADMIN_BOOTSTRAP_USERNAME", "bootstrap-owner")
    monkeypatch.setattr(config, "ADMIN_BOOTSTRAP_PASSWORD", "a-secure-bootstrap-password")
    monkeypatch.setattr(config, "REDIS_URL", "rediss://jzk:secret@redis.internal:6379/0")
    monkeypatch.setattr(config, "MATCH_SCORER_TOKEN", "c" * 64)


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
        ("CORS_ORIGINS", ["*"], "CORS_ORIGINS"),
        ("PG_POOL_MIN_SIZE", 0, "PostgreSQL"),
        ("REDIS_MAX_CONNECTIONS", 0, "Redis 连接池"),
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


def test_chat_v2_config_accepts_safe_defaults():
    config.validate_chat_v2_config()


def test_chat_v2_config_rejects_heartbeat_not_shorter_than_lease(monkeypatch):
    monkeypatch.setattr(config, "CHAT_GENERATION_LEASE_SECONDS", 30)
    monkeypatch.setattr(config, "CHAT_GENERATION_HEARTBEAT_SECONDS", 30)
    with pytest.raises(config.SecurityConfigError, match="HEARTBEAT_SECONDS"):
        config.validate_chat_v2_config()


def test_chat_v2_config_rejects_default_page_above_max(monkeypatch):
    monkeypatch.setattr(config, "CHAT_MESSAGE_PAGE_SIZE_DEFAULT", 101)
    monkeypatch.setattr(config, "CHAT_MESSAGE_PAGE_SIZE_MAX", 100)
    with pytest.raises(config.SecurityConfigError, match="CHAT_MESSAGE_PAGE_SIZE_DEFAULT"):
        config.validate_chat_v2_config()


def test_chat_v2_config_rejects_invalid_rollout(monkeypatch):
    monkeypatch.setattr(config, "CHAT_STORAGE_V2_WRITE_PERCENT", 101)
    with pytest.raises(config.SecurityConfigError, match="WRITE_PERCENT"):
        config.validate_chat_v2_config()


def test_match_scoring_config_rejects_invalid_backend(monkeypatch):
    monkeypatch.setattr(config, "MATCH_SCORING_BACKEND", "magic")
    with pytest.raises(config.SecurityConfigError, match="MATCH_SCORING_BACKEND"):
        config.validate_match_scoring_config()


def test_production_rejects_default_match_scorer_token(production, monkeypatch):
    monkeypatch.setattr(
        config, "MATCH_SCORER_TOKEN", "dev-match-scorer-token-change-me"
    )
    with pytest.raises(config.SecurityConfigError, match="MATCH_SCORER_TOKEN"):
        config.validate_security_config()
