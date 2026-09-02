import config

from core.preference import ranker_factory
from core.preference.scorer import HeuristicRanker
from core.preference.scoring_client import HttpScoringRanker


def test_http_is_default_backend_and_does_not_load_v2(monkeypatch):
    monkeypatch.setattr(config, "MATCH_SCORING_BACKEND", "http")
    monkeypatch.setattr(config, "MATCH_SCORER_URL", "http://scorer.test")
    ranker_factory.reset_ranker_cache()

    ranker = ranker_factory.get_default_ranker()

    assert isinstance(ranker, HttpScoringRanker)
    assert ranker.base_url == "http://scorer.test"
    ranker_factory.reset_ranker_cache()


def test_local_v2_requires_explicit_backend(monkeypatch):
    from core.preference import v2_ranker

    local = HeuristicRanker()
    monkeypatch.setattr(config, "MATCH_SCORING_BACKEND", "local_v2")
    monkeypatch.setattr(v2_ranker, "get_default_ranker", lambda: local)
    ranker_factory.reset_ranker_cache()

    assert ranker_factory.get_default_ranker() is local
    assert ranker_factory.get_scoring_readiness()["backend"] == "local_v2"
    ranker_factory.reset_ranker_cache()
