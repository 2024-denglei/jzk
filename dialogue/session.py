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

    def __init__(self, owner_user_id: int, session_id: str | None = None):
        if owner_user_id <= 0:
            raise ValueError("owner_user_id 必须是有效用户 ID")
        self.owner_user_id = owner_user_id
        self.session_id = session_id or str(uuid.uuid4())
        self.state = DialogueState.START
        self.parsed_features: dict[str, Any] = {}
        self.constraints: dict[str, str] = {}  # 每个特征字段 → "must" | "prefer"
        self.history: list[dict[str, str]] = []
        self.candidates: list[dict] = []
        self.match_result_id: str | None = None
        self.match_total: int = 0
        self.match_next_cursor: str | None = None
        self.feedback_log: list[dict] = []
        self.pending_relaxations: list[str] = []  # 上轮诊断的瓶颈字段，供用户全局肯定时使用
        self.preference_profile: dict | None = None
        self._active_checkpoint: dict[str, Any] | None = None
        self.created_at = time.time()
        self.last_active = time.time()
        self.storage_version = 0

    def add_message(self, role: str, content: str):
        """添加对话记录。"""
        self.history.append({"role": role, "content": content})
        self.last_active = time.time()

    def export_checkpoint(self) -> dict[str, Any]:
        """导出可回滚的会话快照（中止生成时恢复）。"""
        return {
            "state": self.state.value,
            "parsed_features": dict(self.parsed_features),
            "constraints": dict(self.constraints),
            "history": [dict(m) for m in self.history],
            "candidates": list(self.candidates),
            "match_result_id": self.match_result_id,
            "match_total": self.match_total,
            "match_next_cursor": self.match_next_cursor,
            "pending_relaxations": list(self.pending_relaxations),
            "preference_profile": dict(self.preference_profile) if self.preference_profile else None,
        }

    def restore_checkpoint(self, checkpoint: dict[str, Any] | None) -> None:
        """从快照恢复会话（丢弃本轮未完成改动）。"""
        if not checkpoint:
            return
        ds = checkpoint.get("state")
        if ds:
            try:
                self.state = DialogueState(ds)
            except ValueError:
                self.state = DialogueState.COLLECTING
        self.parsed_features = dict(checkpoint.get("parsed_features") or {})
        self.constraints = dict(checkpoint.get("constraints") or {})
        self.history = [dict(m) for m in (checkpoint.get("history") or [])]
        self.candidates = list(checkpoint.get("candidates") or [])
        self.match_result_id = checkpoint.get("match_result_id") or None
        self.match_total = int(checkpoint.get("match_total") or 0)
        self.match_next_cursor = checkpoint.get("match_next_cursor") or None
        self.pending_relaxations = list(checkpoint.get("pending_relaxations") or [])
        raw_profile = checkpoint.get("preference_profile")
        self.preference_profile = dict(raw_profile) if raw_profile else None
        self.last_active = time.time()
        self._active_checkpoint = None

    def begin_turn(self) -> dict[str, Any]:
        """开始一轮对话：保存 checkpoint，供中止时回滚。"""
        cp = self.export_checkpoint()
        self._active_checkpoint = cp
        return cp

    def end_turn(self) -> None:
        """正常结束一轮，清除 checkpoint。"""
        self._active_checkpoint = None

    def abort_turn(self) -> bool:
        """若有进行中的轮次则回滚，返回是否发生了回滚。"""
        cp = getattr(self, "_active_checkpoint", None)
        if cp is None:
            return False
        self.restore_checkpoint(cp)
        return True

    def apply_rewind(
        self,
        history: list[dict],
        *,
        parsed_features: dict | None = None,
        constraints: dict | None = None,
        candidates: list | None = None,
        preference_profile: dict | None = None,
        match_result_id: str | None = None,
        match_total: int | None = None,
        match_next_cursor: str | None = None,
    ) -> None:
        """截断到指定历史并恢复条件。"""
        self.history = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in history
            if isinstance(m, dict) and (m.get("content") or "").strip()
        ]
        if parsed_features is not None:
            self.parsed_features = dict(parsed_features)
        if constraints is not None:
            self.constraints = dict(constraints)
        if candidates is not None:
            self.candidates = list(candidates)
        if preference_profile is not None:
            self.replace_profile(preference_profile)
        self.match_result_id = match_result_id
        self.match_total = int(match_total or 0)
        self.match_next_cursor = match_next_cursor
        self._active_checkpoint = None
        if self.history:
            self.state = DialogueState.PRESENTING if self.candidates else DialogueState.COLLECTING
        else:
            self.state = DialogueState.START
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

    def replace_profile(self, profile: dict | None) -> None:
        """整份替换当前偏好画像（完整快照，不做字段合并）。"""
        self.preference_profile = None if profile is None else dict(profile)
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

    def to_state(self) -> dict:
        """可持久化的会话状态（不含完整候选人列表）。"""
        return {
            "parsed_features": self.parsed_features,
            "constraints": self.constraints,
            "dialogue_state": self.state.value,
            "pending_relaxations": self.pending_relaxations,
            "preference_profile": self.preference_profile,
            "history": self.history[-40:],
            "match_result_id": self.match_result_id,
            "match_total": self.match_total,
            "match_next_cursor": self.match_next_cursor,
        }

    def load_state(self, state: dict | None):
        """从持久化状态恢复。"""
        if not state:
            return
        self.parsed_features = dict(state.get("parsed_features") or {})
        self.constraints = dict(state.get("constraints") or {})
        self.pending_relaxations = list(state.get("pending_relaxations") or [])
        raw_profile = state.get("preference_profile")
        self.preference_profile = dict(raw_profile) if raw_profile else None
        self.match_result_id = state.get("match_result_id") or None
        self.match_total = int(state.get("match_total") or 0)
        self.match_next_cursor = state.get("match_next_cursor") or None
        hist = state.get("history")
        if isinstance(hist, list):
            self.history = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in hist
                if isinstance(m, dict) and m.get("content")
            ]
        ds = state.get("dialogue_state") or state.get("state")
        if ds:
            try:
                self.state = DialogueState(ds)
            except ValueError:
                self.state = DialogueState.COLLECTING
        self.last_active = time.time()

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "parsed_features": self.parsed_features,
            "constraints": self.constraints,
            "preference_profile": self.preference_profile or {},
            "history": self.history,
            "candidates_count": len(self.candidates),
            "match_result_id": self.match_result_id,
            "match_total": self.match_total,
            "match_next_cursor": self.match_next_cursor,
            "feedback_count": len(self.feedback_log),
        }

    def to_storage_dict(self) -> dict:
        """序列化完整临时状态，供 Redis 跨实例共享。"""
        return {
            "owner_user_id": self.owner_user_id,
            "session_id": self.session_id,
            "state": self.state.value,
            "parsed_features": self.parsed_features,
            "constraints": self.constraints,
            "history": self.history,
            "candidates": self.candidates,
            "match_result_id": self.match_result_id,
            "match_total": self.match_total,
            "match_next_cursor": self.match_next_cursor,
            "feedback_log": self.feedback_log,
            "pending_relaxations": self.pending_relaxations,
            "preference_profile": self.preference_profile,
            "active_checkpoint": self._active_checkpoint,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "storage_version": self.storage_version,
        }

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> "SessionContext":
        session = cls(
            owner_user_id=int(data["owner_user_id"]),
            session_id=str(data["session_id"]),
        )
        try:
            session.state = DialogueState(data.get("state") or DialogueState.START.value)
        except ValueError:
            session.state = DialogueState.COLLECTING
        session.parsed_features = dict(data.get("parsed_features") or {})
        session.constraints = dict(data.get("constraints") or {})
        session.history = list(data.get("history") or [])
        session.candidates = list(data.get("candidates") or [])
        session.match_result_id = data.get("match_result_id") or None
        session.match_total = int(data.get("match_total") or 0)
        session.match_next_cursor = data.get("match_next_cursor") or None
        session.feedback_log = list(data.get("feedback_log") or [])
        session.pending_relaxations = list(data.get("pending_relaxations") or [])
        raw_profile = data.get("preference_profile")
        session.preference_profile = dict(raw_profile) if raw_profile else None
        checkpoint = data.get("active_checkpoint")
        session._active_checkpoint = dict(checkpoint) if checkpoint else None
        session.created_at = float(data.get("created_at") or time.time())
        session.last_active = float(data.get("last_active") or time.time())
        session.storage_version = int(data.get("storage_version") or 0)
        return session


class SessionManager:
    """全局会话管理器。"""

    def __init__(self, store=None):
        from dialogue.session_store import InMemorySessionStore

        self._store = store or InMemorySessionStore()

    def create_session(self, user_id: int) -> SessionContext:
        """创建新会话。"""
        self._cleanup_expired()
        session = SessionContext(owner_user_id=user_id)
        self._store.save(session)
        return session

    def get_session(self, user_id: int, session_id: str) -> SessionContext | None:
        """获取当前用户的会话，不存在、越权或过期均返回 None。"""
        session = self._store.load(user_id, session_id)
        if session and not session.is_expired():
            return session
        if session and session.is_expired():
            self._store.delete(user_id, session_id)
        return None

    def get_or_create(self, user_id: int, session_id: str | None) -> SessionContext:
        """获取当前用户的会话，不存在时创建新会话。"""
        if session_id:
            session = self.get_session(user_id, session_id)
            if session:
                return session
        return self.create_session(user_id)

    def put_session(self, session: SessionContext) -> SessionContext:
        """写入/覆盖内存会话（用于从 DB resume）。"""
        session.last_active = time.time()
        self._store.save(session)
        return session

    def restore_session(
        self,
        user_id: int,
        session_id: str,
        state: dict | None = None,
        candidates: list | None = None,
    ) -> SessionContext:
        """按用户和 session_id 恢复或创建，并灌入状态。"""
        session = self.get_session(user_id, session_id)
        if not session:
            session = SessionContext(owner_user_id=user_id, session_id=session_id)
        session.load_state(state)
        if candidates is not None:
            session.candidates = list(candidates)
        if session.state == DialogueState.START and (session.history or session.parsed_features):
            session.state = DialogueState.PRESENTING if session.candidates else DialogueState.COLLECTING
        return self.put_session(session)

    def _cleanup_expired(self):
        """清理过期会话。"""
        self._store.cleanup_expired()
