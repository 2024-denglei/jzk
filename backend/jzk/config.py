import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_BACKEND_ROOT / ".env")
load_dotenv()


class SecurityConfigError(RuntimeError):
    """生产安全配置不完整或仍在使用开发默认值。"""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_positive_int_set(name: str) -> frozenset[int]:
    values = frozenset(
        int(item.strip())
        for item in os.getenv(name, "").split(",")
        if item.strip()
    )
    if any(value <= 0 for value in values):
        raise ValueError(f"{name} 只能包含正整数用户 ID")
    return values


ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
JWT_SECRET = os.getenv("JWT_SECRET", "jzk-fertility-match-secret-change-me")
RATE_LIMIT_PEPPER = os.getenv("RATE_LIMIT_PEPPER", "") or JWT_SECRET
JWT_ISSUER = os.getenv("JWT_ISSUER", "jzk-api")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "jzk-web")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
USER_REFRESH_TOKEN_DAYS = int(os.getenv("USER_REFRESH_TOKEN_DAYS", "30"))
ADMIN_REFRESH_TOKEN_HOURS = int(os.getenv("ADMIN_REFRESH_TOKEN_HOURS", "8"))
USER_REFRESH_COOKIE_NAME = os.getenv("USER_REFRESH_COOKIE_NAME", "jzk_user_refresh")
ADMIN_REFRESH_COOKIE_NAME = os.getenv("ADMIN_REFRESH_COOKIE_NAME", "jzk_admin_refresh")
CORS_ORIGINS = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if item.strip()
]
CHAT_GENERATION_WORKER_ENABLED = _env_bool("CHAT_GENERATION_WORKER_ENABLED", False)
CHAT_GENERATION_WORKER_USER_IDS = _env_positive_int_set("CHAT_GENERATION_WORKER_USER_IDS")
CHAT_OUTBOX_WORKER_ENABLED = _env_bool("CHAT_OUTBOX_WORKER_ENABLED", False)
CHAT_OUTBOX_LEASE_SECONDS = int(os.getenv("CHAT_OUTBOX_LEASE_SECONDS", "60"))
CHAT_OUTBOX_MAX_ATTEMPTS = int(os.getenv("CHAT_OUTBOX_MAX_ATTEMPTS", "10"))
CHAT_OUTBOX_RETRY_BASE_SECONDS = int(os.getenv("CHAT_OUTBOX_RETRY_BASE_SECONDS", "2"))
CHAT_OUTBOX_RETRY_MAX_SECONDS = int(os.getenv("CHAT_OUTBOX_RETRY_MAX_SECONDS", "300"))
CHAT_GENERATION_LEASE_SECONDS = int(os.getenv("CHAT_GENERATION_LEASE_SECONDS", "60"))
CHAT_GENERATION_HEARTBEAT_SECONDS = int(os.getenv("CHAT_GENERATION_HEARTBEAT_SECONDS", "15"))
CHAT_GENERATION_MAX_ATTEMPTS = int(os.getenv("CHAT_GENERATION_MAX_ATTEMPTS", "3"))
CHAT_GENERATION_CHECKPOINT_INTERVAL_SECONDS = float(
    os.getenv("CHAT_GENERATION_CHECKPOINT_INTERVAL_SECONDS", "2")
)
CHAT_GENERATION_CHECKPOINT_CHARS = int(os.getenv("CHAT_GENERATION_CHECKPOINT_CHARS", "256"))
CHAT_GENERATION_STREAM_TTL_SECONDS = int(os.getenv("CHAT_GENERATION_STREAM_TTL_SECONDS", "3600"))
CHAT_MESSAGE_PAGE_SIZE_DEFAULT = int(os.getenv("CHAT_MESSAGE_PAGE_SIZE_DEFAULT", "50"))
CHAT_MESSAGE_PAGE_SIZE_MAX = int(os.getenv("CHAT_MESSAGE_PAGE_SIZE_MAX", "100"))
CHAT_LIST_PAGE_SIZE_DEFAULT = int(os.getenv("CHAT_LIST_PAGE_SIZE_DEFAULT", "20"))
CHAT_LIST_PAGE_SIZE_MAX = int(os.getenv("CHAT_LIST_PAGE_SIZE_MAX", "100"))
CHAT_CURSOR_TTL_SECONDS = int(os.getenv("CHAT_CURSOR_TTL_SECONDS", "86400"))
CHAT_BRANCH_MAX_PER_CHAT = int(os.getenv("CHAT_BRANCH_MAX_PER_CHAT", "200"))
CHAT_MESSAGE_MAX_PER_CHAT = int(os.getenv("CHAT_MESSAGE_MAX_PER_CHAT", "10000"))
CHAT_MESSAGE_MAX_CHARS = int(os.getenv("CHAT_MESSAGE_MAX_CHARS", "20000"))
CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES = int(
    os.getenv("CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES", "20000")
)

# LLM 配置
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# PostgreSQL（官方库；运行时权威数据源）。不给默认值：这里曾内置一串开发凭证，
# 指向 127.0.0.1:5432——而 compose 对宿主机发布的是 5433，于是忘配 DATABASE_URL
# 的后果不是启动失败，而是连接被拒或（更糟）连上本机另一个库。
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# 管理端可选用独立角色；未设置时回退 DATABASE_URL
DATABASE_ADMIN_URL = os.getenv("DATABASE_ADMIN_URL", "") or DATABASE_URL
# 仅供离线 schema/数据迁移脚本使用；生产应配置无常驻 LOGIN 的迁移角色。
DATABASE_MIGRATOR_URL = os.getenv("DATABASE_MIGRATOR_URL", "") or DATABASE_URL
PG_POOL_MIN_SIZE = int(os.getenv("PG_POOL_MIN_SIZE", "1"))
PG_POOL_MAX_SIZE = int(os.getenv("PG_POOL_MAX_SIZE", "10"))
PG_POOL_TIMEOUT_SECONDS = float(os.getenv("PG_POOL_TIMEOUT_SECONDS", "5"))

# Redis 手机验证码（测试阶段会把验证码直接返回给客户端）
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
REDIS_CONNECT_TIMEOUT_SECONDS = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "2"))
REDIS_SOCKET_TIMEOUT_SECONDS = float(os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "2"))
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL_SECONDS", "30"))
VERIFICATION_CODE_TTL_SECONDS = int(os.getenv("VERIFICATION_CODE_TTL_SECONDS", "300"))
VERIFICATION_CODE_COOLDOWN_SECONDS = int(os.getenv("VERIFICATION_CODE_COOLDOWN_SECONDS", "60"))
VERIFICATION_CODE_MAX_ATTEMPTS = int(os.getenv("VERIFICATION_CODE_MAX_ATTEMPTS", "5"))
EXPOSE_TEST_VERIFICATION_CODE = _env_bool("EXPOSE_TEST_VERIFICATION_CODE", True)

# Redis 防爆破限制
USER_LOGIN_LIMIT = int(os.getenv("USER_LOGIN_LIMIT", "5"))
USER_LOGIN_WINDOW_SECONDS = int(os.getenv("USER_LOGIN_WINDOW_SECONDS", "600"))
ADMIN_LOGIN_LIMIT = int(os.getenv("ADMIN_LOGIN_LIMIT", "5"))
ADMIN_LOGIN_WINDOW_SECONDS = int(os.getenv("ADMIN_LOGIN_WINDOW_SECONDS", "900"))
CODE_PHONE_HOURLY_LIMIT = int(os.getenv("CODE_PHONE_HOURLY_LIMIT", "5"))
CODE_PHONE_DAILY_LIMIT = int(os.getenv("CODE_PHONE_DAILY_LIMIT", "10"))
CODE_IP_HOURLY_LIMIT = int(os.getenv("CODE_IP_HOURLY_LIMIT", "20"))
CODE_VERIFY_IP_HOURLY_LIMIT = int(os.getenv("CODE_VERIFY_IP_HOURLY_LIMIT", "30"))

# 首次启动若无管理员则创建（务必在生产修改）
ADMIN_BOOTSTRAP_USERNAME = os.getenv("ADMIN_BOOTSTRAP_USERNAME", "admin")
ADMIN_BOOTSTRAP_PASSWORD = os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "Admin@ChangeMe1")

# 历史 Excel 仅用于一次性导入/联调，不再作为运行时数据源。这里不再提供
# DATA_FILE_PATH 默认值：它曾指向一个仓库里并不存在的文件名，把「忘了传参」
# 推迟到脚本读文件时才炸。灌库脚本改为强制显式传 --file。
DATA_SHEET_NAME = "人造数据"

# 匹配配置
MATCH_THRESHOLD = 0.7
# <=0 表示不截断，返回全部符合条件的候选人
MATCH_TOP_K = int(os.getenv("MATCH_TOP_K", "0"))
MATCH_RESULT_PAGING_ENABLED = _env_bool("MATCH_RESULT_PAGING_ENABLED", True)
MATCH_SNAPSHOT_ENABLED = _env_bool("MATCH_SNAPSHOT_ENABLED", True)
MATCH_RESULT_MAX_CANDIDATES = int(os.getenv("MATCH_RESULT_MAX_CANDIDATES", "20000"))
MATCH_RESULT_PAGE_SIZE_DEFAULT = int(os.getenv("MATCH_RESULT_PAGE_SIZE_DEFAULT", "20"))
MATCH_RESULT_PAGE_SIZE_MAX = int(os.getenv("MATCH_RESULT_PAGE_SIZE_MAX", "50"))
MATCH_SNAPSHOT_RETENTION_DAYS = int(os.getenv("MATCH_SNAPSHOT_RETENTION_DAYS", "180"))
MATCH_CURSOR_TTL_SECONDS = int(os.getenv("MATCH_CURSOR_TTL_SECONDS", "86400"))
MATCH_MODEL_VERSION = os.getenv("MATCH_MODEL_VERSION", "v32-v4-best-mae")
MATCH_SCORER_URL = os.getenv(
    "MATCH_SCORER_URL", "http://127.0.0.1:8020"
).strip().rstrip("/")
MATCH_SCORER_CONTRACT_VERSION = os.getenv(
    "MATCH_SCORER_CONTRACT_VERSION", "1"
).strip()
MATCH_SCORER_TIMEOUT_SECONDS = float(
    os.getenv("MATCH_SCORER_TIMEOUT_SECONDS", "15")
)
MATCH_SCORER_MAX_CANDIDATES = int(
    os.getenv("MATCH_SCORER_MAX_CANDIDATES", "20000")
)
MATCH_SCORER_CANDIDATE_POOL = int(
    os.getenv("SCORER_CANDIDATE_POOL", "5000")
)
# 与打分服务共享的同一个密钥。它必须两端一致，所以只能有一个环境变量名——曾经
# 主应用读 MATCH_SCORER_TOKEN、服务端读 SCORER_TOKEN，只改一处就会在运行时鉴权
# 失败。服务端的 SCORER_* 是一整族变量，故统一到它的命名。
SCORER_TOKEN = os.getenv("SCORER_TOKEN", "dev-match-scorer-token-change-me")
COSINE_WEIGHT = 0.6
EUCLIDEAN_WEIGHT = 0.4

MAX_REQUEST_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", "25000000"))
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "1000000"))
MAX_AUDIO_UPLOAD_BYTES = int(os.getenv("MAX_AUDIO_UPLOAD_BYTES", "20000000"))
MAX_EXCEL_UPLOAD_BYTES = int(os.getenv("MAX_EXCEL_UPLOAD_BYTES", "10000000"))

# 服务配置。8010 是唯一的应用端口，compose、Dockerfile 的 EXPOSE 和前端 dev
# 代理三处都指向它，改这里必须同时改那三处。
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8010"))
# 热重载：默认开启，生产可设 RELOAD=0
RELOAD = os.getenv("RELOAD", "1").strip().lower() not in ("0", "false", "no")

MATCH_LOG_DIR = os.getenv(
    "MATCH_LOG_DIR",
    os.path.join(os.path.dirname(__file__), "data", "match_logs"),
)

# 对话匹配：空则本进程调用 POST /api/match；设为完整 URL 则打外部匹配服务
MATCH_API_URL = os.getenv("MATCH_API_URL", "").strip()


_INSECURE_JWT_SECRETS = {
    "",
    "change-me-in-production",
    "jzk-fertility-match-secret-change-me",
}


def validate_security_config() -> None:
    """在生产启动前拒绝已知不安全的开发配置。"""
    validate_database_config()
    validate_chat_v2_config()
    validate_match_scoring_config()
    if ENVIRONMENT not in {"development", "test", "production"}:
        raise SecurityConfigError("ENVIRONMENT 仅支持 development、test 或 production")
    if ENVIRONMENT != "production":
        return

    errors: list[str] = []
    if JWT_SECRET in _INSECURE_JWT_SECRETS or len(JWT_SECRET.encode("utf-8")) < 32:
        errors.append("JWT_SECRET 必须是至少 32 字节的随机密钥，且不能使用示例值")
    if len(RATE_LIMIT_PEPPER.encode("utf-8")) < 32:
        errors.append("RATE_LIMIT_PEPPER 必须是至少 32 字节的随机密钥")
    if EXPOSE_TEST_VERIFICATION_CODE:
        errors.append("生产环境必须设置 EXPOSE_TEST_VERIFICATION_CODE=0")
    if ADMIN_BOOTSTRAP_USERNAME == "admin":
        errors.append("生产环境不能使用默认管理员用户名 admin")
    if ADMIN_BOOTSTRAP_PASSWORD == "Admin@ChangeMe1" or len(ADMIN_BOOTSTRAP_PASSWORD) < 12:
        errors.append("生产环境必须设置至少 12 位且非默认的管理员引导密码")
    if not CORS_ORIGINS or "*" in CORS_ORIGINS:
        errors.append("生产环境必须配置明确的 CORS_ORIGINS，不能使用通配符")
    if PG_POOL_MIN_SIZE < 1 or PG_POOL_MAX_SIZE < PG_POOL_MIN_SIZE:
        errors.append("PostgreSQL 连接池大小配置无效")
    if REDIS_MAX_CONNECTIONS < 1:
        errors.append("Redis 连接池大小配置无效")

    redis_url = urlparse(REDIS_URL)
    if redis_url.scheme not in {"redis", "rediss"}:
        errors.append("REDIS_URL 必须使用 redis:// 或 rediss://")
    elif not redis_url.password:
        errors.append("生产 Redis 必须配置认证凭证")
    if (
        SCORER_TOKEN == "dev-match-scorer-token-change-me"
        or len(SCORER_TOKEN.encode("utf-8")) < 32
    ):
        errors.append("生产环境必须设置至少32字节的 SCORER_TOKEN")

    if errors:
        raise SecurityConfigError("生产安全配置校验失败：" + "；".join(errors))


def validate_database_config() -> None:
    """数据库连接串必须显式配置，任何环境都不例外。"""
    errors: list[str] = []
    if not DATABASE_URL:
        errors.append("必须设置 DATABASE_URL（参考 .env.example）")
    else:
        scheme = urlparse(DATABASE_URL).scheme
        if scheme not in {"postgresql", "postgres"}:
            errors.append("DATABASE_URL 必须是 postgresql:// 连接串")
    if errors:
        raise SecurityConfigError("数据库配置校验失败：" + "；".join(errors))


def validate_match_scoring_config() -> None:
    """校验通往打分服务的传输配置。

    按 docs/adr/0001，打分只有 HTTP 这一条通路，因此不再有后端选择开关：进程内
    推理的副本已删除，配置里留一个只有单一取值的开关只会让人以为还能切回去。
    """
    errors: list[str] = []
    parsed = urlparse(MATCH_SCORER_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append("MATCH_SCORER_URL 必须是有效的 http/https URL")
    if not SCORER_TOKEN:
        errors.append("SCORER_TOKEN 不能为空")
    if MATCH_SCORER_CONTRACT_VERSION != "1":
        errors.append("MATCH_SCORER_CONTRACT_VERSION 当前仅支持 1")
    if MATCH_SCORER_TIMEOUT_SECONDS <= 0:
        errors.append("MATCH_SCORER_TIMEOUT_SECONDS 必须大于0")
    if MATCH_SCORER_MAX_CANDIDATES <= 0:
        errors.append("MATCH_SCORER_MAX_CANDIDATES 必须大于0")
    if MATCH_SCORER_CANDIDATE_POOL <= 0:
        errors.append("SCORER_CANDIDATE_POOL 必须大于0")
    if MATCH_SCORER_CANDIDATE_POOL > MATCH_SCORER_MAX_CANDIDATES:
        errors.append("SCORER_CANDIDATE_POOL 不能大于 MATCH_SCORER_MAX_CANDIDATES")
    if errors:
        raise SecurityConfigError("匹配评分配置校验失败：" + "；".join(errors))


def validate_chat_v2_config() -> None:
    """拒绝会导致任务丢失、无界加载或无法续租的 V2 对话配置。"""
    errors: list[str] = []
    positive_values = {
        "CHAT_GENERATION_LEASE_SECONDS": CHAT_GENERATION_LEASE_SECONDS,
        "CHAT_GENERATION_HEARTBEAT_SECONDS": CHAT_GENERATION_HEARTBEAT_SECONDS,
        "CHAT_GENERATION_MAX_ATTEMPTS": CHAT_GENERATION_MAX_ATTEMPTS,
        "CHAT_GENERATION_CHECKPOINT_INTERVAL_SECONDS": CHAT_GENERATION_CHECKPOINT_INTERVAL_SECONDS,
        "CHAT_GENERATION_CHECKPOINT_CHARS": CHAT_GENERATION_CHECKPOINT_CHARS,
        "CHAT_GENERATION_STREAM_TTL_SECONDS": CHAT_GENERATION_STREAM_TTL_SECONDS,
        "CHAT_OUTBOX_LEASE_SECONDS": CHAT_OUTBOX_LEASE_SECONDS,
        "CHAT_OUTBOX_MAX_ATTEMPTS": CHAT_OUTBOX_MAX_ATTEMPTS,
        "CHAT_OUTBOX_RETRY_BASE_SECONDS": CHAT_OUTBOX_RETRY_BASE_SECONDS,
        "CHAT_OUTBOX_RETRY_MAX_SECONDS": CHAT_OUTBOX_RETRY_MAX_SECONDS,
        "CHAT_MESSAGE_PAGE_SIZE_DEFAULT": CHAT_MESSAGE_PAGE_SIZE_DEFAULT,
        "CHAT_MESSAGE_PAGE_SIZE_MAX": CHAT_MESSAGE_PAGE_SIZE_MAX,
        "CHAT_LIST_PAGE_SIZE_DEFAULT": CHAT_LIST_PAGE_SIZE_DEFAULT,
        "CHAT_LIST_PAGE_SIZE_MAX": CHAT_LIST_PAGE_SIZE_MAX,
        "CHAT_CURSOR_TTL_SECONDS": CHAT_CURSOR_TTL_SECONDS,
        "CHAT_BRANCH_MAX_PER_CHAT": CHAT_BRANCH_MAX_PER_CHAT,
        "CHAT_MESSAGE_MAX_PER_CHAT": CHAT_MESSAGE_MAX_PER_CHAT,
        "CHAT_MESSAGE_MAX_CHARS": CHAT_MESSAGE_MAX_CHARS,
        "CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES": CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES,
    }
    for name, value in positive_values.items():
        if value <= 0:
            errors.append(f"{name} 必须大于 0")
    if CHAT_GENERATION_HEARTBEAT_SECONDS >= CHAT_GENERATION_LEASE_SECONDS:
        errors.append("CHAT_GENERATION_HEARTBEAT_SECONDS 必须小于 CHAT_GENERATION_LEASE_SECONDS")
    if CHAT_MESSAGE_PAGE_SIZE_DEFAULT > CHAT_MESSAGE_PAGE_SIZE_MAX:
        errors.append("CHAT_MESSAGE_PAGE_SIZE_DEFAULT 不能大于 CHAT_MESSAGE_PAGE_SIZE_MAX")
    if CHAT_LIST_PAGE_SIZE_DEFAULT > CHAT_LIST_PAGE_SIZE_MAX:
        errors.append("CHAT_LIST_PAGE_SIZE_DEFAULT 不能大于 CHAT_LIST_PAGE_SIZE_MAX")
    if CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES > MATCH_RESULT_MAX_CANDIDATES:
        errors.append("CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES 不能大于 MATCH_RESULT_MAX_CANDIDATES")
    if CHAT_OUTBOX_RETRY_BASE_SECONDS > CHAT_OUTBOX_RETRY_MAX_SECONDS:
        errors.append("CHAT_OUTBOX_RETRY_BASE_SECONDS 不能大于 CHAT_OUTBOX_RETRY_MAX_SECONDS")
    if errors:
        raise SecurityConfigError("V2 对话配置校验失败：" + "；".join(errors))
