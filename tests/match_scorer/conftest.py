from pathlib import Path

import pytest

from jzk.scorer.engine import MatchScoringEngine
from jzk.scorer.settings import ScorerSettings


@pytest.fixture(scope="session")
def scorer_settings() -> ScorerSettings:
    return ScorerSettings(
        model_path=(
            Path(__file__).resolve().parents[2]
            / "backend"
            / "checkpoints"
            / "best_mae_model_v4.pt"
        ),
        model_version="test-v32-v4-best-mae",
        force_cpu=True,
        candidate_pool=300,
        max_candidates=20000,
        max_request_bytes=25_000_000,
        token="test-match-scorer-token",
    )


@pytest.fixture(scope="session")
def scoring_engine(scorer_settings: ScorerSettings) -> MatchScoringEngine:
    return MatchScoringEngine(scorer_settings)
