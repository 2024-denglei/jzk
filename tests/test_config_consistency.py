"""同一个配置项在多处声明时，必须在这里被钉在一起。

这个文件针对的不是某个函数的行为，而是「同一件事被写了两遍，其中一遍忘了改」这类
缺陷。它已经真实发生过两次：`.env.example` 里的 `PORT=8000` 与 `config.PORT` 默认值
8010 不一致；`.env.example` 的 `DATABASE_URL` 指向 5432，而容器实际只对宿主机发布
5433。两次都不报错，只是连不上。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _code_only(text: str) -> str:
    """去掉整行注释，只留可执行部分。

    下面几项检查的是「代码里不该再出现某个名字」，而解释这个名字为何被淘汰的注释
    恰恰应该保留，否则下一个人会重新把它加回来。
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


@pytest.fixture(scope="module")
def env_example() -> str:
    return (ROOT / ".env.example").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose() -> str:
    return (ROOT / "compose.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config_source() -> str:
    return (ROOT / "backend" / "jzk" / "config.py").read_text(encoding="utf-8")


def test_app_port_is_the_same_number_everywhere(
    env_example: str, compose: str, config_source: str
) -> None:
    """应用端口在五处声明，必须同为 8010。

    读 config.py 源码而不是 import config，否则测的就是本机 .env 而非默认值。
    """
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

    assert re.search(r'PORT = int\(os\.getenv\("PORT", "8010"\)\)', config_source)
    assert re.search(r"^PORT=8010$", env_example, re.MULTILINE)
    assert '"${APP_PORT:-8010}:8010"' in compose
    assert "--port" in dockerfile and '"8010"' in dockerfile
    assert "http://127.0.0.1:8010" in vite


def test_env_example_connects_to_the_port_compose_publishes(
    env_example: str, compose: str
) -> None:
    """`.env.example` 面向宿主机，端口必须是 compose 对外发布的那个。

    容器内部是 5432，对宿主机发布的是 5433。把 5432 抄进 DATABASE_URL 会连到本机
    另一个 PostgreSQL（如果恰好装了），那比连不上更难查。
    """
    published = re.search(r"\$\{POSTGRES_PORT:-(\d+)\}:5432", compose)
    assert published, "compose.yml 未发布 postgres 端口"
    host_port = published.group(1)

    urls = [
        line.lstrip("# ").strip()
        for line in env_example.splitlines()
        if "postgresql://" in line
    ]
    assert urls, ".env.example 未给出任何 PostgreSQL 连接串"
    for url in urls:
        assert f"127.0.0.1:{host_port}/" in url, f"{url} 未指向 {host_port}"


def test_scorer_token_has_exactly_one_environment_variable_name() -> None:
    """主应用与打分服务共享同一个密钥，因此只能有一个变量名。

    曾经主应用读 MATCH_SCORER_TOKEN、服务端读 SCORER_TOKEN。两者默认值相同，本地
    因此一直是通的；一旦在生产只改其中一个，就变成打分请求 401——而这条路径本身
    是降级可用的，故障会以「匹配结果为空」的形式出现。
    """
    this_file = Path(__file__).resolve()
    sources = [
        path
        for path in ROOT.rglob("*.py")
        if ".venv" not in path.parts
        and "node_modules" not in path.parts
        and path.resolve() != this_file
    ]
    offenders = [
        path.relative_to(ROOT)
        for path in sources
        if "MATCH_SCORER_TOKEN" in _code_only(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"这些文件仍在用第二个 token 名：{offenders}"

    scorer_settings = (
        ROOT / "backend" / "jzk" / "scorer" / "settings.py"
    ).read_text(encoding="utf-8")
    assert 'os.getenv("SCORER_TOKEN"' in scorer_settings
    assert 'os.getenv("SCORER_TOKEN"' in (
        ROOT / "backend" / "jzk" / "config.py"
    ).read_text(encoding="utf-8")


def test_the_runtime_stack_is_defined_by_a_single_compose_file() -> None:
    """整套服务只由根目录 compose.yml 定义。

    db/postgres 下曾有第二份 Compose，同样占用 jzk-postgres 这个 container_name，
    两份一起用会互相抢名字，且它发布的是 5432 而根目录发布 5433。
    """
    found = [
        path.relative_to(ROOT)
        for path in ROOT.rglob("*compose*.y*ml")
        if ".venv" not in path.parts and "node_modules" not in path.parts
    ]
    assert found == [Path("compose.yml")], f"存在重复的 compose 定义：{found}"


def test_database_url_has_no_built_in_default(config_source: str) -> None:
    """数据库连接串必须显式配置，缺了就启动失败。

    这里曾内置一串指向 127.0.0.1:5432 的开发凭证，而容器发布的是 5433：忘配的后果
    不是启动报错，而是连接被拒——或者在本机另装了 PostgreSQL 时静默连错库。
    """
    assert 'os.getenv("DATABASE_URL", "")' in config_source
    assert "jzk_dev_change_me@127.0.0.1" not in _code_only(config_source)


def test_missing_database_url_fails_validation(monkeypatch) -> None:
    from jzk import config

    monkeypatch.setattr(config, "DATABASE_URL", "")
    with pytest.raises(config.SecurityConfigError, match="DATABASE_URL"):
        config.validate_database_config()

    monkeypatch.setattr(config, "DATABASE_URL", "mysql://x/y")
    with pytest.raises(config.SecurityConfigError, match="postgresql"):
        config.validate_database_config()


def test_excel_import_path_has_no_default(config_source: str) -> None:
    """灌库数据源必须显式传入，不给默认值。

    这里曾默认指向一个仓库中并不存在的 xlsx 文件名，把「忘了指定数据源」推迟到读
    文件时才暴露。历史 Excel 已不是运行时数据源，配置层不该再有它的位置。
    """
    assert "DATA_FILE_PATH" not in _code_only(config_source)

    seed_script = (
        ROOT / "backend" / "scripts" / "seed_donors_from_excel.py"
    ).read_text(encoding="utf-8")
    assert 'add_argument("--file", required=True)' in seed_script
