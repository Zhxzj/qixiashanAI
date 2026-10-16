"""会话状态存储（内存版；单机 demo 足够，结构见规格 §3.0）。"""

from __future__ import annotations


def new_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "location": None,      # 懒初始化：首次访问时落在山门
        "route": None,
        "visited": [],
        "memory": [],
        "prefs": {},
        "announced": [],       # 已主动播报过的点位
        "history": [],         # LLM 对话历史（user/assistant/tool 消息）
    }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    def get(self, session_id: str = "demo") -> dict:
        if session_id not in self._sessions:
            self._sessions[session_id] = new_state(session_id)
        return self._sessions[session_id]

    def reset(self, session_id: str = "demo") -> dict:
        self._sessions[session_id] = new_state(session_id)
        return self._sessions[session_id]

