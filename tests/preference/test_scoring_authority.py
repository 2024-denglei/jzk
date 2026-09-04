"""守住 docs/adr/0001：打分权威只有 services/match_scorer 一处。

同一个神经网络曾有两份实现——HTTP 服务和 core/preference/v2/ 的进程内副本，各自
维护一份网络定义、权重文件与配置。这种重复的失效方式最难查：两份实现给出不同的
分数既不报错也没有堆栈，只表现为同一个画像换个部署就排出不同的人。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "services" / "match_scorer"


def _production_sources() -> list[Path]:
    """仓库里的生产 Python 代码，排除虚拟环境、测试与训练脚本。"""
    skip_dirs = {".venv", "node_modules", "tests", "__pycache__"}
    return [
        path
        for path in ROOT.rglob("*.py")
        if not skip_dirs & set(path.parts)
    ]


def test_only_the_scoring_service_runs_inference() -> None:
    """torch 只允许出现在打分服务里。

    主应用一旦能自己加载检查点，「打分服务不可用」就会多出一条静默降级的诱惑，
    而那条路径用的是另一份权重。
    """
    offenders = [
        path.relative_to(ROOT)
        for path in _production_sources()
        if SCORER not in path.parents
        and any(
            line.startswith(("import torch", "from torch"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert not offenders, f"打分服务之外出现了推理代码：{offenders}"


def test_the_in_process_model_copy_is_gone() -> None:
    assert not (ROOT / "core" / "preference" / "v2").exists()
    assert not (ROOT / "core" / "preference" / "v2_ranker.py").exists()
    assert not (ROOT / "core" / "preference" / "v2_adapter.py").exists()


def test_the_repository_keeps_only_the_checkpoint_the_service_declares() -> None:
    """仓库里不留第二份权重文件。

    进程内副本用的是 models/best_model_v2.pt，与打分服务的检查点是两个不同的
    文件。留着它就等于留着一份没人负责、也没人验证的权重。
    """
    declared = SCORER / "settings.py"
    assert "best_mae_model_v4.pt" in declared.read_text(encoding="utf-8")

    checkpoints = sorted(p.name for p in (ROOT / "models").glob("*.pt"))
    assert checkpoints == ["best_mae_model_v4.pt"], f"models/ 下有多余权重：{checkpoints}"
