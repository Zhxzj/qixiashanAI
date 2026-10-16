"""工具注册表：每个工具一个模块（SCHEMA + async run(args, ctx)）。

约定（冻结）：
- SCHEMA 为 OpenAI function schema（含 additionalProperties: false，兼容 strict 模式）
- run 返回可 JSON 序列化的 dict；出错返回 {"error": {"code", "message"}}
- ctx = {"state": 会话状态, "services": {location, route, weather}}
"""

from __future__ import annotations

from importlib import import_module

TOOL_MODULES = [
    "get_location",
    "list_nearby",
    "get_poi",
    "plan_route",
    "navigate_hint",
    "save_memory",
    "get_conditions",
]


def load_tools():
    schemas: list = []
    handlers: dict = {}
    for name in TOOL_MODULES:
        mod = import_module(f"app.tools.{name}")
        schemas.append(mod.SCHEMA)
        handlers[mod.SCHEMA["function"]["name"]] = mod.run
    return schemas, handlers

