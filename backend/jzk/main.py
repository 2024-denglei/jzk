"""智能生育匹配系统 — 对话智能体服务入口。"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from jzk import config
from jzk.db.donors_repo import load_donor_data
from jzk.domain.feature_engine import FeatureEncoder
from jzk.api.search import router as search_router
from jzk.api.auth import router as auth_router
from jzk.api.user import router as user_router
from jzk.api.donors import router as donors_router
from jzk.api.admin import router as admin_router
from jzk.api.admin_users import router as admin_users_router
from jzk.api.admin_admins import router as admin_admins_router
from jzk.api.admin_requests import router as admin_requests_router
from jzk.api.voice import router as voice_router
from jzk.api.match import router as match_router
from jzk.api.chats import router as chats_v2_router, message_router as messages_v2_router
from jzk.api.generation_events import router as generation_events_router
from jzk.api.admin_chats import router as admin_chats_v2_router
from jzk.api.admin_chat_feedback import router as admin_chat_feedback_router
from jzk.db.database import close_pools, init_db, initialize_pools
from jzk.redis_client import close_redis_pool

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
    config.validate_chat_v2_config()
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

    app.state.donor_df = donor_df
    app.state.encoder = encoder

    logger.info("系统启动完成！")


@app.on_event("shutdown")
async def shutdown():
    close_pools()
    close_redis_pool()


# ============ 注册路由 ============

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
app.include_router(admin_chats_v2_router)
app.include_router(admin_chat_feedback_router)

def _existing_dir(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent
client_dist = str(
    _existing_dir(
        Path.cwd() / "frontend" / "client" / "dist",
        _BACKEND_ROOT / "frontend" / "client" / "dist",
        _REPO_ROOT / "frontend" / "client" / "dist",
    )
    or (Path.cwd() / "frontend" / "client" / "dist")
)
admin_dist = str(
    _existing_dir(
        Path.cwd() / "frontend" / "admin" / "dist",
        _BACKEND_ROOT / "frontend" / "admin" / "dist",
        _REPO_ROOT / "frontend" / "admin" / "dist",
    )
    or (Path.cwd() / "frontend" / "admin" / "dist")
)


@app.get("/api/featured")
async def featured_donors(page: int = 1, page_size: int = 12):
    """返回捐精人列表，按标本数量降序，支持分页。"""
    from jzk.domain.data_loader import get_donor_display_info, to_card_donor_info
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
_SPA_BUILD_HINT = "请先构建前端：cd frontend && npm run build"


def _spa_index(dist: str):
    return FileResponse(os.path.join(dist, "index.html"), headers=_SPA_NO_CACHE)


def _spa_fallback(dist: str, full_path: str, *, reserved: tuple[str, ...]):
    if full_path.startswith(reserved):
        raise HTTPException(status_code=404, detail="Not Found")
    candidate = os.path.join(dist, full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)
    return _spa_index(dist)


if os.path.isdir(admin_dist):
    admin_assets = os.path.join(admin_dist, "assets")
    if os.path.isdir(admin_assets):
        app.mount("/admin/assets", StaticFiles(directory=admin_assets), name="admin-assets")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{full_path:path}", include_in_schema=False)
    async def admin_spa(full_path: str = ""):
        return _spa_fallback(
            admin_dist,
            full_path,
            reserved=("assets/",),
        )


if os.path.isdir(client_dist):
    client_assets = os.path.join(client_dist, "assets")
    if os.path.isdir(client_assets):
        app.mount("/assets", StaticFiles(directory=client_assets), name="client-assets")

    @app.get("/", include_in_schema=False)
    async def spa_index():
        return _spa_index(client_dist)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """客户端路由回退；管理端与 API 前缀不走这里。"""
        return _spa_fallback(
            client_dist,
            full_path,
            reserved=(
                "api/",
                "docs",
                "openapi",
                "redoc",
                "health",
                "assets/",
                "admin",
            ),
        )
elif not os.path.isdir(admin_dist):
    @app.get("/", include_in_schema=False)
    async def index_fallback():
        """未构建 React 前端时返回提示。"""
        return {
            "message": "智能生育匹配系统 API",
            "docs": "/docs",
            "hint": _SPA_BUILD_HINT,
        }


# ============ 直接运行 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "jzk.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.RELOAD,
        reload_dirs=[os.path.dirname(__file__)] if config.RELOAD else None,
    )
