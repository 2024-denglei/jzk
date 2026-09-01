"""智能生育匹配系统 — 对话智能体服务入口。"""

import logging
import sys
import os

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

import config
from core.data_loader import load_donor_data
from core.feature_engine import FeatureEncoder
from dialogue.session import SessionManager
from dialogue.session_store import create_session_store
from dialogue.session_store import (
    SessionConflict,
    SessionLimitExceeded,
    SessionStoreUnavailable,
    SessionTooLarge,
)
from dialogue.nlu import create_async_llm_client, create_llm_client
from api.chat import router as chat_router, inject_dependencies as inject_chat_deps
from api.chat_stream import router as stream_router, inject_dependencies as inject_stream_deps
from api.feedback import router as feedback_router, inject_dependencies as inject_feedback_deps
from api.search import router as search_router
from api.auth import router as auth_router
from api.user import router as user_router
from api.donors import router as donors_router
from api.admin import router as admin_router
from api.admin_users import router as admin_users_router
from api.admin_admins import router as admin_admins_router
from api.admin_requests import router as admin_requests_router
from api.voice import router as voice_router
from api.match import router as match_router
from api.chats import router as chats_v2_router, message_router as messages_v2_router
from api.generation_events import router as generation_events_router
from db.database import close_pools, init_db, initialize_pools
from redis_client import close_redis_pool

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


@app.exception_handler(SessionStoreUnavailable)
async def session_store_unavailable_handler(_request, exc: SessionStoreUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(SessionConflict)
async def session_conflict_handler(_request, exc: SessionConflict):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(SessionLimitExceeded)
async def session_limit_handler(_request, exc: SessionLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.exception_handler(SessionTooLarge)
async def session_too_large_handler(_request, exc: SessionTooLarge):
    return JSONResponse(status_code=413, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    content_length = request.headers.get("content-length")
    content_type = request.headers.get("content-type", "").lower()
    request_limit = (
        config.MAX_JSON_BODY_BYTES
        if "application/json" in content_type
        else config.MAX_REQUEST_BODY_BYTES
    )
    try:
        request_too_large = bool(
            content_length and int(content_length) > request_limit
        )
    except ValueError:
        request_too_large = True
    if request_too_large:
        response = JSONResponse(status_code=413, content={"detail": "请求体过大"})
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if config.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ============ 启动时加载数据 ============

@app.on_event("startup")
async def startup():
    """应用启动时加载数据、初始化组件。"""
    config.validate_security_config()
    logger.info("正在初始化 PostgreSQL 官方库...")
    try:
        initialize_pools()
        init_db()
    except Exception as e:
        logger.error("数据库初始化失败: %s", e)
        raise
    logger.info("PostgreSQL 已就绪")

    logger.info("正在从数据库加载捐精人数据...")
    donor_df = load_donor_data()
    logger.info(f"已加载 {len(donor_df)} 条捐精人数据")

    logger.info("正在构建特征矩阵...")
    encoder = FeatureEncoder(donor_df)
    encoder.encode_all()
    logger.info(f"特征矩阵维度: {encoder.feature_matrix.shape}")

    session_manager = SessionManager(create_session_store())

    llm_client = None
    async_llm_client = None
    if config.LLM_API_KEY:
        llm_client = create_llm_client()
        async_llm_client = create_async_llm_client()
        logger.info(f"LLM 已配置: model={config.LLM_MODEL}, base_url={config.LLM_BASE_URL}")
    else:
        logger.warning("未配置 LLM_API_KEY，对话功能将使用模拟模式")
        llm_client = None

    inject_chat_deps(session_manager, encoder, donor_df, llm_client)
    inject_stream_deps(session_manager, encoder, donor_df, async_llm_client)
    inject_feedback_deps(session_manager)

    app.state.donor_df = donor_df
    app.state.encoder = encoder
    app.state.session_manager = session_manager
    app.state.llm_client = llm_client
    app.state.async_llm_client = async_llm_client

    logger.info("系统启动完成！")


@app.on_event("shutdown")
async def shutdown():
    close_pools()
    close_redis_pool()


# ============ 注册路由 ============

app.include_router(chat_router)
app.include_router(stream_router)
app.include_router(feedback_router)
app.include_router(search_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(donors_router)
app.include_router(admin_router)
app.include_router(admin_users_router)
app.include_router(admin_admins_router)
app.include_router(admin_requests_router)
app.include_router(voice_router)
app.include_router(match_router)
app.include_router(chats_v2_router)
app.include_router(messages_v2_router)
app.include_router(generation_events_router)

# 静态文件服务
docs_dir = os.path.join(os.path.dirname(__file__), "docs")
web_dist = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.isdir(docs_dir):
    app.mount("/docs-static", StaticFiles(directory=docs_dir), name="docs-static")


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
    from core.data_loader import get_donor_display_info, to_card_donor_info
    df = app.state.donor_df
    if df is None or len(df) == 0:
        return {"items": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 0}
    if "状态" in df.columns:
        df = df[df["状态"].fillna("active") != "disabled"]
    if len(df) == 0:
        return {"items": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 0}
    col = "标本数量" if "标本数量" in df.columns else df.columns[0]
    sorted_df = df.sort_values(col, ascending=False)
    total = len(sorted_df)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_df = sorted_df.iloc[start:end]
    items = []
    for _, row in page_df.iterrows():
        items.append({
            "donor_info": to_card_donor_info(get_donor_display_info(row)),
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


# ============ React SPA（生产构建） ============

_SPA_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _spa_index_response():
    return FileResponse(os.path.join(web_dist, "index.html"), headers=_SPA_NO_CACHE)


if os.path.isdir(web_dist):
    assets_dir = os.path.join(web_dist, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    @app.get("/")
    async def spa_index():
        return _spa_index_response()

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """SPA 前端路由回退；跳过已有 API/静态前缀。"""
        if full_path.startswith(("api/", "docs-static/", "docs", "openapi", "redoc", "health", "architecture", "assets/")):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = os.path.join(web_dist, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return _spa_index_response()
else:
    @app.get("/")
    async def index_fallback():
        """未构建 React 前端时返回提示。"""
        return {
            "message": "智能生育匹配系统 API",
            "docs": "/docs",
            "hint": "请先构建前端：cd web && npm run build",
        }


# ============ 直接运行 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.RELOAD,
        reload_dirs=[os.path.dirname(__file__)] if config.RELOAD else None,
    )
