"""工具：get_location —— 当前位置（吸附后）。"""

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_location",
        "description": "获取游客当前位置（已吸附到最近路径与景点），返回坐标、最近点位与周边前三。游客问我在哪、我旁边有什么、这是什么地方时调用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


async def run(args, ctx):
    locator = ctx["services"]["location"]
    state = ctx["state"]
    loc = locator.ensure(state)
    top3 = locator.nearest_pois(loc["lat"], loc["lng"], limit=3)
    return {
        "lat": loc["lat"],
        "lng": loc["lng"],
        "source": loc.get("source"),
        "snapped": loc.get("snapped"),
        "nearby_top3": top3,
    }

