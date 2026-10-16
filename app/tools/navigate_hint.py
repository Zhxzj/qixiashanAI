"""工具：navigate_hint —— 快通道导航提示（模板拼装，不经 LLM 生成文本）。"""

from app.services.location import bearing_text, dist_m

SCHEMA = {
    "type": "function",
    "function": {
        "name": "navigate_hint",
        "description": "获取下一段导航提示（模板文本 + 音频占位）。游客问怎么走、下一步往哪走时调用；播报时照文本念，不要自己发挥方向。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["next", "repeat", "skip"],
                    "description": "next 下一条 / repeat 再说一遍 / skip 跳过，默认 next",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


async def run(args, ctx):
    state = ctx["state"]
    route = state.get("route")
    if not route:
        return {"error": {"code": "no_route", "message": "还没有规划路线，先让游客说想去哪。"}}

    locator = ctx["services"]["location"]
    loc = locator.ensure(state)
    target = locator.poi(route.get("to"))
    if target is None:
        return {"error": {"code": "not_found", "message": "目标点位数据缺失。"}}

    pos = (loc["lat"], loc["lng"])
    remaining = dist_m(pos, tuple(target["coord"]))
    bearing = bearing_text(pos, tuple(target["coord"]))
    step10 = max(10, round(remaining / 10) * 10)
    text = f"朝{bearing}走，大约 {step10} 米就到{target['name']}。"
    if args.get("action") == "repeat":
        text = "再说一遍，" + text
    return {
        "text": text,
        "audio_url": None,  # 构建期预生成音频后填 /audio/hint/xxx.mp3（M5）
        "next_poi_id": route.get("to"),
        "remaining_m": round(remaining),
    }

