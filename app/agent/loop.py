"""Agent 循环：DeepSeek chat + tool calling（SSE 事件流）。

事件协议（冻结）：delta / tool_start / tool_end / done / error。
工程注意（见规格 §12）：主循环关闭思考模式（延迟优先）；图片只能放 user 消息。
"""

from __future__ import annotations

import json

import httpx

from app.agent.prompts import SYSTEM_PROMPT
from app.tools import load_tools

API_URL = "https://api.deepseek.com/chat/completions"
MAX_TOOL_ROUNDS = 6
HISTORY_LIMIT = 40


class AgentLoop:
    def __init__(self, cfg: dict, sessions, services: dict):
        self.cfg = cfg
        self.sessions = sessions
        self.services = services
        self.tool_schemas, self.tool_handlers = load_tools()

    async def stream(self, session_id: str, text: str):
        state = self.sessions.get(session_id)
        self.services["location"].ensure(state)

        if not self.cfg.get("deepseek_api_key"):
            yield {
                "type": "error",
                "message": "还没配置 DeepSeek API Key。点右上角填一下，测通了再聊。",
            }
            return

        history_len = len(state["history"])
        msgs = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + state["history"]
            + [{"role": "user", "content": text}]
        )
        full_text = ""

        for _ in range(MAX_TOOL_ROUNDS):
            content = ""
            calls: dict = {}
            err = None
            async for ev in self._request_stream(msgs):
                if ev["kind"] == "delta":
                    content += ev["text"]
                    full_text += ev["text"]
                    yield {"type": "delta", "text": ev["text"]}
                elif ev["kind"] == "error":
                    err = ev["message"]
                    break
                elif ev["kind"] == "done":
                    calls = ev["calls"]
            if err:
                yield {"type": "error", "message": err}
                break
            if not calls:
                break
            assistant_msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {
                        "id": c["id"] or f"call_{i}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                    }
                    for i, c in calls.items()
                ],
            }
            msgs.append(assistant_msg)
            for c in calls.values():
                name = c["name"]
                yield {
                    "type": "tool_start",
                    "name": name,
                    "args": self._safe_args(c["arguments"]),
                }
                result = await self._run_tool(name, c["arguments"], state)
                ok = not (isinstance(result, dict) and "error" in result)
                yield {"type": "tool_end", "name": name, "ok": ok}
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": c["id"] or "call_x",
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        # 记录本轮（user + assistant/tool 消息）到会话历史，并做窗口裁剪
        state["history"].extend(msgs[1 + history_len :])
        self._trim_history(state)
        yield {"type": "done", "text": full_text}

    # ---------- 内部 ----------

    async def _request_stream(self, msgs: list):
        body = {
            "model": self.cfg.get("model", "deepseek-flash"),
            "messages": msgs,
            "tools": self.tool_schemas,
            "tool_choice": "auto",
            "stream": True,
            "max_tokens": 900,
            "temperature": 0.7,
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.get('deepseek_api_key', '')}",
            "Content-Type": "application/json",
        }
        calls: dict = {}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15)) as client:
                async with client.stream("POST", API_URL, json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode("utf-8", "ignore")[:300]
                        yield {
                            "kind": "error",
                            "message": f"DeepSeek 接口返回 {resp.status_code}：{detail}",
                        }
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if isinstance(delta.get("content"), str) and delta["content"]:
                            yield {"kind": "delta", "text": delta["content"]}
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = calls.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
        except httpx.HTTPError as e:
            yield {
                "kind": "error",
                "message": f"网络出问题了（{type(e).__name__}），再试一次？",
            }
            return
        yield {"kind": "done", "calls": calls}

    async def _run_tool(self, name: str, raw_args: str, state: dict):
        handler = self.tool_handlers.get(name)
        if handler is None:
            return {"error": {"code": "unknown_tool", "message": f"未知工具 {name}"}}
        args = self._safe_args(raw_args)
        ctx = {"state": state, "services": self.services}
        try:
            return await handler(args, ctx)
        except Exception as e:  # 工具异常→结构化错误，让模型友好降级
            return {"error": {"code": "tool_failed", "message": f"{type(e).__name__}: {e}"}}

    @staticmethod
    def _safe_args(raw: str) -> dict:
        try:
            args = json.loads(raw) if raw else {}
            return args if isinstance(args, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _trim_history(state: dict) -> None:
        """按条数裁剪历史，并保证不从孤立的 tool 消息开头。"""
        h = state["history"]
        while len(h) > HISTORY_LIMIT:
            h.pop(0)
        changed = True
        while h and changed:
            changed = False
            while h and h[0].get("role") == "tool":
                h.pop(0)
                changed = True
            if h and h[0].get("role") == "assistant" and h[0].get("tool_calls"):
                h.pop(0)
                changed = True

