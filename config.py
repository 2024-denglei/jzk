import os
from dotenv import load_dotenv

load_dotenv()

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

# Redis 手机验证码（测试阶段会把验证码直接返回给客户端）
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
VERIFICATION_CODE_TTL_SECONDS = int(os.getenv("VERIFICATION_CODE_TTL_SECONDS", "300"))
VERIFICATION_CODE_COOLDOWN_SECONDS = int(os.getenv("VERIFICATION_CODE_COOLDOWN_SECONDS", "60"))
EXPOSE_TEST_VERIFICATION_CODE = os.getenv("EXPOSE_TEST_VERIFICATION_CODE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}

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
COSINE_WEIGHT = 0.6
EUCLIDEAN_WEIGHT = 0.4

# 会话配置
SESSION_TIMEOUT_MINUTES = 30

# 服务配置（若本机 8000 被占用，可设 PORT=8010）
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8010"))
# 热重载：默认开启，生产可设 RELOAD=0
RELOAD = os.getenv("RELOAD", "1").strip().lower() not in ("0", "false", "no")

# Agent Trace 目录（JSONL）
TRACE_DIR = os.getenv(
    "TRACE_DIR",
    os.path.join(os.path.dirname(__file__), "data", "traces"),
)
TRACE_ENABLED = os.getenv("TRACE_ENABLED", "1").strip().lower() not in ("0", "false", "no")

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
