"""工具：save_memory —— 记住此刻（游踪记忆）。"""

from __future__ import annotations

import time

SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "把此刻存进游客的游历记忆（生成日记海报时会用到）。游客说记住这里、帮我记一下时调用，尽量保留他的原话。",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["poi", "note", "photo", "moment"],
                    "description": "记忆类型，默认 poi",
                },
                "poi_id": {"type": "string", "description": "关联点位（可选）"},
                "note": {"type": "string", "description": "游客的原话或一句备注"},
                "photo_id": {"type": "string", "description": "关联照片（可选）"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


async def run(args, ctx):
    state = ctx["state"]
    loc = ctx["services"]["location"].ensure(state)
    poi_id = args.get("poi_id") or (loc.get("snapped") or {}).get("poi_id")
    entry = {
        "kind": args.get("kind", "poi"),
        "poi_id": poi_id,
        "note": args.get("note", ""),
        "photo_id": args.get("photo_id"),
        "ts": int(time.time()),
    }
    state["memory"].append(entry)
    return {"saved": True, "total": len(state["memory"])}

