from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_builds_frontend_and_runs_backend() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "npm run build" in dockerfile
    assert "COPY --from=web-builder /build/web/dist ./web/dist" in dockerfile
    assert "https://download.pytorch.org/whl/cpu" in dockerfile
    assert '"main:app"' in dockerfile


def test_httpx_is_declared_as_a_direct_dependency() -> None:
    """httpx 必须写在 requirements.txt 里，不能靠镜像里补一条 pip install。

    api/match.py 与 core/preference/scoring_client.py 直接 import httpx，而新版
    openai SDK 依赖的是 httpx2，不会顺带装上它。少了这行声明，一次干净的
    pip install -r requirements.txt 会装出一个导入即失败的环境。
    """
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "httpx>=0.27,<1" in requirements


def test_compose_contains_complete_runtime_stack() -> None:
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")

    for service in ("app", "scorer", "postgres", "redis"):
        assert f"  {service}:" in compose
    assert "postgres:5432/jzk" in compose
    assert "redis://redis:6379/0" in compose
    assert "http://scorer:8020" in compose
    assert "condition: service_healthy" in compose
    assert "name: postgres_jzk_pg_data" in compose
    assert "name: postgres_jzk_redis_data" in compose


def test_secrets_and_local_artifacts_are_excluded_from_image() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert ".git" in ignored
    assert ".venv" in ignored
    assert "web/node_modules" in ignored
