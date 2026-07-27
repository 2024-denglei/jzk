import os
from dotenv import load_dotenv

load_dotenv()

# LLM 配置
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# 数据文件路径
DATA_FILE_PATH = os.getenv(
    "DATA_FILE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "人造精子匹配数据.xlsx"),
)
DATA_SHEET_NAME = "人造数据"

# 匹配配置
MATCH_THRESHOLD = 0.7
MATCH_TOP_K = 50
COSINE_WEIGHT = 0.6
EUCLIDEAN_WEIGHT = 0.4

# 会话配置
SESSION_TIMEOUT_MINUTES = 30

# 服务配置
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
