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
    if state.get("prefs",{}).get("map_mode")=="real":
        from app.services.map_navigation import quality
        return {"source":loc.get("source"),"lat":loc.get("lat"),"lng":loc.get("lng"),
                "coordinate_system":loc.get("coordinate_system"),"accuracy_m":loc.get("accuracy_m"),
                "sample_at":loc.get("sample_at"),"navigation_eligible":quality(state),
                "snapped":loc.get("snapped"),"notice":"真实模式不使用坐标系未知的草稿景点；不可把手动起点称为用户当前位置。"}
    top3 = locator.nearest_pois(loc["lat"], loc["lng"], limit=3)
    return {
        "lat": loc["lat"],
        "lng": loc["lng"],
        "source": loc.get("source"),
        "snapped": loc.get("snapped"),
        "nearby_top3": top3,
    }

