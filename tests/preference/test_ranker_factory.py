from jzk import config

from jzk.domain.preference import ranker_factory
from jzk.domain.preference.scoring_client import HttpScoringRanker


def test_the_only_ranker_is_the_scoring_service_client(monkeypatch):
    monkeypatch.setattr(config, "MATCH_SCORER_URL", "http://scorer.test")
    ranker_factory.reset_ranker_cache()

    ranker = ranker_factory.get_default_ranker()

    assert isinstance(ranker, HttpScoringRanker)
    assert ranker.base_url == "http://scorer.test"
    ranker_factory.reset_ranker_cache()


def test_no_configuration_can_select_in_process_inference(monkeypatch):
    """不存在任何配置能让打分退回进程内推理。

    进程内曾有一份同一网络的副本，由 MATCH_SCORING_BACKEND=local_v2 选中，各自
    维护一份权重与配置。两份实现给出的分数不一致既不报错也没有堆栈，只是同一个
    画像换个部署就排出不同的人。副本已按 docs/adr/0001 删除，这里守住它不回来。
    """
    assert not hasattr(config, "MATCH_SCORING_BACKEND"), "后端选择开关应已删除"

    # 即使有人把旧开关塞回配置，工厂也不该再认它。
    monkeypatch.setattr(config, "MATCH_SCORING_BACKEND", "local_v2", raising=False)
    ranker_factory.reset_ranker_cache()

    assert isinstance(ranker_factory.get_default_ranker(), HttpScoringRanker)
    ranker_factory.reset_ranker_cache()
