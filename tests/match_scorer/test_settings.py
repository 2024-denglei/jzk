from pathlib import Path

import pytest

from services.match_scorer.settings import ScorerSettings


def _settings(**overrides) -> ScorerSettings:
    values = {
        "model_path": Path("model.pt"),
        "model_version": "v4",
        "force_cpu": True,
        "candidate_pool": 300,
        "max_candidates": 20000,
        "max_request_bytes": 25_000_000,
        "token": "test-token",
    }
    values.update(overrides)
    return ScorerSettings(**values)


def test_rejects_invalid_checkpoint_hash_and_rank_source():
    with pytest.raises(ValueError, match="64位十六进制"):
        _settings(expected_checkpoint_sha256="z" * 64).validate()
    with pytest.raises(ValueError, match="ranking_score"):
        _settings(rank_source="match_score").validate()


def test_production_environment_requires_strong_service_token(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SCORER_TOKEN", "short")
    with pytest.raises(ValueError, match="至少32字节"):
        ScorerSettings.from_environment()
