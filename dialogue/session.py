"""会话管理模块：维护多轮对话上下文。"""

import time
import uuid
from enum import Enum
from typing import Any

from config import SESSION_TIMEOUT_MINUTES


class DialogueState(str, Enum):
    START = "start"
    COLLECTING = "collecting"
    CONFIRMING = "confirming"
    MATCHING = "matching"
    PRESENTING = "presenting"
    FEEDBACK = "feedback"
    REFINING = "refining"
    END = "end"


class SessionContext:
    """单个会话上下文。"""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.state = DialogueState.START
        self.parsed_features: dict[str, Any] = {}
        self.constraints: dict[str, str] = {}  # 每个特征字段 → "must" | "prefer"
        self.history: list[dict[str, str]] = []
        self.candidates: list[dict] = []
        self.feedback_log: list[dict] = []
        self.pending_relaxations: list[str] = []  # 上轮诊断的瓶颈字段，供用户全局肯定时使用
        self.created_at = time.time()
        self.last_active = time.time()

    def add_message(self, role: str, content: str):
        """添加对话记录。"""
        self.history.append({"role": role, "content": content})
        self.last_active = time.time()

    def update_features(
        self,
        new_features: dict,
        new_constraints: dict | None = None,
        remove_fields: list | None = None,
    ):
        """累积更新需求特征和约束（新值覆盖旧值，null 不覆盖，REMOVE/remove_fields 删除）。"""
        for key, value in new_features.items():
            if value == "REMOVE":
                self.parsed_features.pop(key, None)
                self.constraints.pop(key, None)
            elif value is not None:
                self.parsed_features[key] = value
        if remove_fields:
            for field in remove_fields:
                self.parsed_features.pop(field, None)
                self.constraints.pop(field, None)
        if new_constraints:
            for key, level in new_constraints.items():
                if level and level in ("must", "prefer"):
                    self.constraints[key] = level
        self.last_active = time.time()

    def add_feedback(self, candidate_id: str, feedback: str, reason: str | None = None):
        """记录用户反馈。"""
        self.feedback_log.append({
            "candidate_id": candidate_id,
            "feedback": feedback,
            "reason": reason,
            "timestamp": time.time(),
        })
        self.last_active = time.time()

    def is_expired(self) -> bool:
        """检查会话是否超时。"""
        return (time.time() - self.last_active) > SESSION_TIMEOUT_MINUTES * 60

    def get_llm_messages(self) -> list[dict[str, str]]:
        """获取供 LLM 使用的对话历史（最近20轮）。"""
        return self.history[-20:]

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "parsed_features": self.parsed_features,
            "constraints": self.constraints,
            "history": self.history,
            "candidates_count": len(self.candidates),
            "feedback_count": len(self.feedback_log),
        }


class SessionManager:
    """全局会话管理器。"""

    def __init__(self):
        self._sessions: dict[str, SessionContext] = {}

    def create_session(self) -> SessionContext:
        """创建新会话。"""
        self._cleanup_expired()
        session = SessionContext()
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionContext | None:
        """获取会话，不存在或过期返回 None。"""
        session = self._sessions.get(session_id)
        if session and not session.is_expired():
            return session
        if session and session.is_expired():
            del self._sessions[session_id]
        return None

    def get_or_create(self, session_id: str | None) -> SessionContext:
        """获取或创建会话。"""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
        return self.create_session()

    def _cleanup_expired(self):
        """清理过期会话。"""
        expired = [
            sid for sid, s in self._sessions.items() if s.is_expired()
        ]
        for sid in expired:
            del self._sessions[sid]
