"""智能生育匹配系统 — 对话智能体服务入口。"""

import logging
import sys
import os

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import config
from core.data_loader import load_donor_data
from core.feature_engine import FeatureEncoder
from dialogue.session import SessionManager
from dialogue.nlu import create_llm_client
from api.chat import router as chat_router, inject_dependencies as inject_chat_deps
from api.chat_stream import router as stream_router, inject_dependencies as inject_stream_deps
from api.feedback import router as feedback_router, inject_dependencies as inject_feedback_deps
from api.search import router as search_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ============ 创建 FastAPI 应用 ============

app = FastAPI(
    title="智能生育匹配系统 - 对话智能体",
    description="基于 LLM 的智能对话匹配系统原型",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 启动时加载数据 ============

@app.on_event("startup")
async def startup():
    """应用启动时加载数据、初始化组件。"""
    logger.info("正在加载捐精人数据...")
    donor_df = load_donor_data()
    logger.info(f"已加载 {len(donor_df)} 条可用捐精人数据")

    logger.info("正在构建特征矩阵...")
    encoder = FeatureEncoder(donor_df)
    encoder.encode_all()
    logger.info(f"特征矩阵维度: {encoder.feature_matrix.shape}")

    session_manager = SessionManager()

    llm_client = None
    if config.LLM_API_KEY:
        llm_client = create_llm_client()
        logger.info(f"LLM 已配置: model={config.LLM_MODEL}, base_url={config.LLM_BASE_URL}")
    else:
        logger.warning("未配置 LLM_API_KEY，对话功能将使用模拟模式")
        llm_client = None

    # 注入依赖
    inject_chat_deps(session_manager, encoder, donor_df, llm_client)
    inject_stream_deps(session_manager, encoder, donor_df, llm_client)
    inject_feedback_deps(session_manager)

    # 保存到 app.state 供其他模块访问
    app.state.donor_df = donor_df
    app.state.encoder = encoder
    app.state.session_manager = session_manager
    app.state.llm_client = llm_client

    logger.info("系统启动完成！")


# ============ 注册路由 ============

app.include_router(chat_router)
app.include_router(stream_router)
app.include_router(feedback_router)
app.include_router(search_router)

# 静态文件服务
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
docs_dir = os.path.join(os.path.dirname(__file__), "docs")
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
if os.path.isdir(docs_dir):
    app.mount("/docs-static", StaticFiles(directory=docs_dir), name="docs-static")


@app.get("/")
async def index():
    """首页 → 前端界面（V2）。"""
    v3_path = os.path.join(frontend_dir, "index_v3.html")
    if os.path.exists(v3_path):
        return FileResponse(v3_path)
    return {"message": "智能生育匹配系统 - 对话智能体 API", "docs": "/docs"}


@app.get("/v1")
async def index_v1():
    """旧版界面。"""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "旧版界面未找到"}


@app.get("/architecture")
async def architecture():
    """架构图页面。"""
    arch_path = os.path.join(docs_dir, "research_architecture.html")
    if os.path.exists(arch_path):
        return FileResponse(arch_path)
    return {"message": "架构图未找到"}


@app.get("/api/featured")
async def featured_donors(page: int = 1, page_size: int = 12):
    """返回捐精人列表，按标本数量降序，支持分页。"""
    from core.data_loader import get_donor_display_info
    df = app.state.donor_df
    sorted_df = df.sort_values("标本数量", ascending=False)
    total = len(sorted_df)
    total_pages = (total + page_size - 1) // page_size
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_df = sorted_df.iloc[start:end]
    items = []
    for _, row in page_df.iterrows():
        items.append({
            "donor_info": get_donor_display_info(row),
            "score": 0,
            "match_pct": None,
            "reason": "",
            "match_level": "featured",
            "field_match": {},
        })
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@app.get("/health")
async def health():
    """健康检查。"""
    return {"status": "ok"}


# ============ 直接运行 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )
