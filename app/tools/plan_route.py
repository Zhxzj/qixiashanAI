"""工具：plan_route —— 路线规划（天气感知）。"""

SCHEMA = {
    "type": "function",
    "function": {
        "name": "plan_route",
        "description": "为游客规划到目标点位的路线（含分段步骤、距离、时长），会结合天气给出提示。游客说想去哪、怎么走、累了要换路线时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "目标点位 ID 或名称"},
                "via": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "途经点（可选）",
                },
                "theme": {
                    "type": "string",
                    "enum": ["classic", "autumn", "family"],
                    "description": "路线主题，默认 classic",
                },
                "consider_weather": {
                    "type": "boolean",
                    "description": "是否结合天气给提示，默认 true",
                },
            },
            "required": ["to"],
            "additionalProperties": False,
        },
    },
}


async def run(args, ctx):
    services = ctx["services"]
    locator = services["location"]
    key = (args.get("to") or "").strip()
    poi = locator.poi(key)
    if poi is None:
        poi = next((p for p in locator.pois if p["name"] == key), None)
    if poi is None:
        return {"error": {"code": "not_found", "message": f"地图里没有这个点位：{key}"}}

    conditions = None
    if args.get("consider_weather", True):
        try:
            conditions = await services["weather"].get(days=1)
        except Exception:
            conditions = None

    return services["route"].plan(
        ctx["state"],
        poi["poi_id"],
        via=args.get("via") or [],
        theme=args.get("theme", "classic"),
        consider_weather=bool(args.get("consider_weather", True)),
        conditions=conditions,
    )

