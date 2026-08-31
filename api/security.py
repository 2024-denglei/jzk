"""浏览器 Cookie 端点的同源校验。"""

from fastapi import HTTPException, Request

import config


def validate_cookie_origin(request: Request) -> None:
    """拒绝来自未授权站点的 Cookie 写入、刷新和撤销请求。"""
    origin = request.headers.get("origin")
    if not origin:
        # 非浏览器客户端通常不发送 Origin；Cookie 的浏览器攻击场景会携带。
        return
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    allowed = set(config.CORS_ORIGINS)
    allowed.add(request_origin)
    if origin.rstrip("/") not in {item.rstrip("/") for item in allowed}:
        raise HTTPException(status_code=403, detail="请求来源不受信任")
