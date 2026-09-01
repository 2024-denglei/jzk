"""用户反馈与临时会话查询 API。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_utils import get_current_user_id
from core.preference.match_log import append_feedback_event
from db.donors_repo import get_donor_by_code
from db.match_runs_repo import match_run_contains

router = APIRouter()

_deps = {}


def record_feedback(session_id: str, donor_code: str, feedback: str) -> None:
    event = {"like": "like", "dislike": "dislike"}[feedback]
    append_feedback_event({
        "session_id": session_id,
        "donor_code": donor_code,
        "event": event,
    })

def inject_dependencies(session_manager):
    """注入运行时依赖。"""
    _deps["session_manager"] = session_manager


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    candidate_id: str = Field(min_length=1, max_length=100)
    feedback: Literal["like", "dislike"]
    reason: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    success: bool
    message: str


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    user_id: int = Depends(get_current_user_id),
):
    """提交用户反馈。"""
    session_manager = _deps.get("session_manager")
    if not session_manager:
        raise HTTPException(status_code=500, detail="系统未就绪")

    session = session_manager.get_session(user_id, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    belongs = False
    if session.match_result_id:
        donor = get_donor_by_code(request.candidate_id)
        belongs = bool(
            donor
            and donor.get("status") == "active"
            and match_run_contains(
                session.match_result_id, user_id, int(donor["id"])
            )
        )
    else:
        # 兼容迁移前创建、尚无严格快照的会话。
        candidate_ids: set[str] = set()
        for candidate in session.candidates:
            if not isinstance(candidate, dict):
                continue
            donor_info = candidate.get("donor_info")
            if isinstance(donor_info, dict) and donor_info.get("code") is not None:
                candidate_ids.add(str(donor_info["code"]))
            for key in ("candidate_id", "code", "id"):
                if candidate.get(key) is not None:
                    candidate_ids.add(str(candidate[key]))
        belongs = request.candidate_id in candidate_ids
    if not belongs:
        raise HTTPException(status_code=404, detail="候选人不属于该会话")

    session.add_feedback(request.candidate_id, request.feedback, request.reason)
    session_manager.put_session(session)
    record_feedback(request.session_id, request.candidate_id, request.feedback)

    return FeedbackResponse(
        success=True,
        message="感谢您的反馈！我们会根据您的偏好优化推荐结果。",
    )


@router.get("/api/session/{session_id}")
async def get_session_info(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """获取会话信息。"""
    session_manager = _deps.get("session_manager")
    if not session_manager:
        raise HTTPException(status_code=500, detail="系统未就绪")

    session = session_manager.get_session(user_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    return session.to_dict()
