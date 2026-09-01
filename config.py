import os
from urllib.parse import urlparse

from dotenv import load_dotenv

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
# 分支化长期对话 V2。迁移期间默认关闭，由灰度开关逐步启用。
CHAT_STORAGE_V2_READ_ENABLED = _env_bool("CHAT_STORAGE_V2_READ_ENABLED", False)
CHAT_STORAGE_V2_WRITE_ENABLED = _env_bool("CHAT_STORAGE_V2_WRITE_ENABLED", False)
CHAT_STORAGE_V2_WRITE_PERCENT = int(os.getenv("CHAT_STORAGE_V2_WRITE_PERCENT", "100"))
CHAT_STORAGE_V2_WRITE_USER_IDS = _env_positive_int_set("CHAT_STORAGE_V2_WRITE_USER_IDS")
CHAT_STORAGE_V2_ROLLOUT_SALT = os.getenv("CHAT_STORAGE_V2_ROLLOUT_SALT", "jzk-chat-v2")
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

# PostgreSQL（官方库；运行时权威数据源）
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:jzk_dev_change_me@127.0.0.1:5432/jzk",
)
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

# 历史 Excel 仅用于一次性导入/联调，不再作为运行时数据源
DATA_FILE_PATH = os.getenv(
    "DATA_FILE_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "新生成的模拟捐精人信息数据3000条(1).xlsx",
    ),
)
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
MATCH_MODEL_VERSION = os.getenv("MATCH_MODEL_VERSION", "v2")
COSINE_WEIGHT = 0.6
EUCLIDEAN_WEIGHT = 0.4

MAX_REQUEST_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", "25000000"))
MAX_JSON_BODY_BYTES = int(os.getenv("MAX_JSON_BODY_BYTES", "1000000"))
MAX_AUDIO_UPLOAD_BYTES = int(os.getenv("MAX_AUDIO_UPLOAD_BYTES", "20000000"))
MAX_EXCEL_UPLOAD_BYTES = int(os.getenv("MAX_EXCEL_UPLOAD_BYTES", "10000000"))

# 服务配置（若本机 8000 被占用，可设 PORT=8010）
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

_AGENT_ROOT = os.path.dirname(__file__)
V2_CHECKPOINT_PATH = os.getenv(
    "V2_CHECKPOINT_PATH",
    os.path.join(_AGENT_ROOT, "models", "best_model_v2.pt"),
)
V2_CONFIG_PATH = os.getenv(
    "V2_CONFIG_PATH",
    os.path.join(_AGENT_ROOT, "core", "preference", "v2", "config_v2.json"),
)
V2_FORCE_CPU = os.getenv("V2_FORCE_CPU", "1").strip().lower() in {"1", "true", "yes"}


_INSECURE_JWT_SECRETS = {
    "",
    "change-me-in-production",
    "jzk-fertility-match-secret-change-me",
}


def validate_security_config() -> None:
    """在生产启动前拒绝已知不安全的开发配置。"""
    validate_chat_v2_config()
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

    if errors:
        raise SecurityConfigError("生产安全配置校验失败：" + "；".join(errors))


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
    if not 0 <= CHAT_STORAGE_V2_WRITE_PERCENT <= 100:
        errors.append("CHAT_STORAGE_V2_WRITE_PERCENT 必须在 0 到 100 之间")
    if not CHAT_STORAGE_V2_ROLLOUT_SALT.strip():
        errors.append("CHAT_STORAGE_V2_ROLLOUT_SALT 不能为空")
    if CHAT_OUTBOX_RETRY_BASE_SECONDS > CHAT_OUTBOX_RETRY_MAX_SECONDS:
        errors.append("CHAT_OUTBOX_RETRY_BASE_SECONDS 不能大于 CHAT_OUTBOX_RETRY_MAX_SECONDS")
    if errors:
        raise SecurityConfigError("V2 对话配置校验失败：" + "；".join(errors))
