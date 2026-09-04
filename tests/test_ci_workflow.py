"""CI 工作流的静态守护。

结构收敛期间几乎每一步都要靠 CI 兜底，所以这里锁住几个容易被无声删掉的要素：
少了 postgres 或 redis service，集成测试会静默跳过而流水线照样是绿的；少了前端
的类型检查，后端契约改名不会被任何东西挡住。
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), "CI 工作流缺失"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run_commands(workflow: dict, job: str) -> str:
    return " ".join(step.get("run", "") for step in workflow["jobs"][job]["steps"])


def test_workflow_runs_on_push_and_pull_request(workflow: dict) -> None:
    # PyYAML 按 YAML 1.1 把裸键 on 解析成布尔 True。
    triggers = workflow[True] if True in workflow else workflow["on"]

    assert set(triggers) == {"push", "pull_request"}
    assert set(workflow["jobs"]) == {"backend", "frontend"}


def test_backend_job_provides_postgres_and_redis(workflow: dict) -> None:
    backend = workflow["jobs"]["backend"]

    assert set(backend["services"]) == {"postgres", "redis"}
    assert "TEST_DATABASE_URL" in backend["env"], "缺少它则集成测试会整体跳过"
    assert "REDIS_URL" in backend["env"]


def test_backend_job_runs_the_whole_suite(workflow: dict) -> None:
    """不允许用 -k 或 --ignore 把测试挑着跑。"""
    commands = _run_commands(workflow, "backend")

    assert "pytest" in commands
    assert "-k " not in commands
    assert "--ignore" not in commands


def test_backend_job_installs_from_the_lock_file(workflow: dict) -> None:
    """必须带 --locked：否则改了 pyproject 忘记重新锁定时 CI 会装出另一套依赖，

    而它验证的就不再是即将发布的那套环境了。
    """
    assert "uv sync --locked" in _run_commands(workflow, "backend")


def test_frontend_job_covers_types_tests_and_lint(workflow: dict) -> None:
    commands = _run_commands(workflow, "frontend")

    assert "npm ci" in commands
    assert "tsc -b" in commands
    assert "npm test" in commands
    assert "oxlint" in commands
