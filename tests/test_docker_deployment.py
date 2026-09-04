import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


BACKEND = ROOT / "backend"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (BACKEND / "Dockerfile").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pyproject() -> str:
    return (BACKEND / "pyproject.toml").read_text(encoding="utf-8")


def test_dockerfile_builds_frontend_and_runs_backend(dockerfile: str) -> None:
    assert "npm run build" in dockerfile
    assert (
        "COPY --from=web-builder /build/frontend/client/dist ./frontend/client/dist"
        in dockerfile
    )
    assert (
        "COPY --from=web-builder /build/frontend/admin/dist ./frontend/admin/dist"
        in dockerfile
    )
    assert "COPY frontend/.npmrc" in dockerfile
    assert "npm ci --legacy-peer-deps" in dockerfile
    assert '"jzk.main:app"' in dockerfile


def test_image_installs_from_the_lock_file_without_dev_dependencies(dockerfile: str) -> None:
    """镜像必须用 --locked 安装，且不带开发依赖。

    少了 --locked，改了 pyproject 却忘记重新锁定时镜像会静默装出另一套依赖；
    少了 --no-dev，pytest 之类只在 CI 用的东西会一路带进运行镜像。
    """
    assert "uv sync --locked --no-dev" in dockerfile
    assert (BACKEND / "uv.lock").exists()


def test_the_backend_is_an_installable_package(pyproject: str) -> None:
    """pytest 必须通过安装 `jzk` 包来导入，不能再靠把仓库根塞进 pythonpath。"""
    assert "package = true" in pyproject
    assert "pythonpath =" not in pyproject
    assert 'testpaths = ["../tests"]' in pyproject
    assert 'packages = ["jzk"]' in pyproject


def test_httpx_is_declared_as_a_direct_dependency(pyproject: str) -> None:
    """httpx 必须写在依赖声明里，不能靠镜像里补一条 pip install。

    jzk.api.match 与 jzk.domain.preference.scoring_client 直接 import httpx，而新版
    openai SDK 依赖的是 httpx2，不会顺带装上它。少了这行声明，一次干净的安装会
    装出一个导入即失败的环境。
    """
    assert "httpx>=0.27,<1" in pyproject


def test_torch_is_pinned_exactly_and_taken_from_the_cpu_index(pyproject: str) -> None:
    """docs/adr/0001 要求线上与离线共用同一检查点，加载它的构建也属于那份契约。

    放宽成 >= 会让不同环境拿到不同 torch 构建，而推理结果不一致既不报错也没有
    堆栈；默认的 PyPI 版还会在 Linux 上拖进整套 nvidia-* CUDA 运行时。
    """
    assert re.search(r'"torch==\d+\.\d+\.\d+"', pyproject), "torch 必须精确钉住版本"
    assert "https://download.pytorch.org/whl/cpu" in pyproject
    assert 'torch = { index = "pytorch-cpu" }' in pyproject


def test_python_version_matches_the_runtime_base_image(
    pyproject: str, dockerfile: str
) -> None:
    """依赖声明里的 Python 版本必须与运行镜像一致。

    放宽上界会让 uv 在开发机上挑一个更新的解释器，于是本地测的是 cp314 的 wheel、
    线上发的是 cp312 的。
    """
    base = re.search(r"FROM python:(\d+\.\d+)-", dockerfile)
    assert base, "Dockerfile 未声明 python 基础镜像"
    major_minor = base.group(1)

    assert f'requires-python = ">={major_minor},<' in pyproject
    assert (BACKEND / ".python-version").read_text(encoding="utf-8").strip() == major_minor


def test_compose_contains_complete_runtime_stack() -> None:
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")

    for service in ("app", "scorer", "postgres", "redis"):
        assert f"  {service}:" in compose
    assert "postgres:5432/jzk" in compose
    assert "redis://redis:6379/0" in compose
    assert "http://scorer:8020" in compose
    assert "condition: service_healthy" in compose
    assert "dockerfile: backend/Dockerfile" in compose
    assert "jzk.scorer.app:app" in compose
    assert "name: postgres_jzk_pg_data" in compose
    assert "name: postgres_jzk_redis_data" in compose


def test_secrets_and_local_artifacts_are_excluded_from_image() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert ".git" in ignored
    assert ".venv" in ignored
    assert "frontend/node_modules" in ignored
