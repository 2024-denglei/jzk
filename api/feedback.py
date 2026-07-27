"""用户反馈 API 路由。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_deps = {}


def inject_dependencies(session_manager):
    """注入运行时依赖。"""
    _deps["session_manager"] = session_manager


class FeedbackRequest(BaseModel):
    session_id: str
    candidate_id: str
    feedback: str  # "like" | "dislike"
    reason: str | None = None


class FeedbackResponse(BaseModel):
    success: bool
    message: str


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """提交用户反馈。"""
    session_manager = _deps.get("session_manager")
    if not session_manager:
        raise HTTPException(status_code=500, detail="系统未就绪")

    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    if request.feedback not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="feedback 仅支持 like/dislike")

    session.add_feedback(request.candidate_id, request.feedback, request.reason)

    return FeedbackResponse(
        success=True,
        message="感谢您的反馈！我们会根据您的偏好优化推荐结果。",
    )


@router.get("/api/session/{session_id}")
async def get_session_info(session_id: str):
    """获取会话信息。"""
    session_manager = _deps.get("session_manager")
    if not session_manager:
        raise HTTPException(status_code=500, detail="系统未就绪")

    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    return session.to_dict()
