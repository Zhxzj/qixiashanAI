"""Per-session ordering, cancellation and SQLite snapshots (no images)."""
import asyncio
import json
import sqlite3
from contextlib import closing
def new_state(session_id, generation=0):
    return {"session_id": session_id, "generation": generation, "revision": 0,
            "location": None, "route": None, "visited": [], "memory": [], "prefs": {},
            "announced": [], "history": [], "turns": [], "tool_results": {}}
class SessionStore:
    def __init__(self, path=None):
        self.path, self._sessions, self._locks, self._tasks = path, {}, {}, {}
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, body TEXT NOT NULL)")
    def get(self, session_id="demo"):
        if session_id not in self._sessions:
            st = None
            if self.path:
                with closing(sqlite3.connect(self.path)) as db, db:
                    row = db.execute("SELECT body FROM sessions WHERE id=?", (session_id,)).fetchone()
                if row:
                    try:
                        st = json.loads(row[0])
                    except ValueError:
                        pass
            self._sessions[session_id] = st or new_state(session_id)
            self._sessions[session_id].pop("_arrival_pending", None)
        return self._sessions[session_id]
    def lock(self, sid):
        return self._locks.setdefault(sid, asyncio.Lock())
    def register(self, sid, request_id):
        self._tasks.setdefault(sid, {}).setdefault(request_id, set()).add(asyncio.current_task())
    def unregister(self, sid, request_id):
        group = self._tasks.get(sid, {}).get(request_id, set())
        group.discard(asyncio.current_task())
        if not group:
            self._tasks.get(sid, {}).pop(request_id, None)
    def cancel(self, sid, request_id=None):
        for rid, group in list(self._tasks.get(sid, {}).items()):
            if request_id is None or rid == request_id:
                for task in tuple(group):
                    if task is not asyncio.current_task():
                        task.cancel()
    def save(self, state, bump=True):
        if self.get(state["session_id"]) is not state:
            return False
        if bump:
            state["revision"] += 1
        if self.path:
            keys = ("session_id", "generation", "revision", "location", "route", "visited", "memory", "prefs", "announced", "history", "turns", "tool_results")
            body = json.dumps({k: state[k] for k in keys}, ensure_ascii=False)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (state["session_id"], body))
        return True
    def reset(self, session_id="demo"):
        old = self.get(session_id)
        self.cancel(session_id)
        old["generation"] += 1
        st = new_state(session_id, old["generation"])
        self._sessions[session_id] = st
        self.save(st)
        return st
