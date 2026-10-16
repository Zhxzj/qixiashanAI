"""工具：get_poi —— 点位讲解资料。"""

SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_poi",
        "description": "获取某个景点的讲解资料（简介或详解、事实清单、来源）。讲解类问题必须以本工具返回内容为准。",
        "parameters": {
            "type": "object",
            "properties": {
                "poi_id": {"type": "string", "description": "点位 ID（也可传点位中文名）"},
                "detail": {
                    "type": "string",
                    "enum": ["short", "full"],
                    "description": "short 为简介，full 为详解；默认 short",
                },
            },
            "required": ["poi_id"],
            "additionalProperties": False,
        },
    },
}


async def run(args, ctx):
    locator = ctx["services"]["location"]
    key = (args.get("poi_id") or "").strip()
    poi = locator.poi(key)
    if poi is None:
        poi = next((p for p in locator.pois if p["name"] == key), None)
    if poi is None:
        return {"error": {"code": "not_found", "message": f"没有找到点位：{key}"}}
    detail = args.get("detail", "short")
    item = {
        "poi_id": poi["poi_id"],
        "name": poi["name"],
        "text": poi["text_full"] if detail == "full" else poi["text_short"],
        "facts": poi["facts"],
        "tags": poi["tags"],
        "best_light": poi.get("best_light"),
        "photo_spot": poi.get("photo_spot"),
        "sources": poi.get("sources", []),
    }
    if poi.get("audio"):
        item["audio_url"] = f"/audio/poi/{poi['poi_id']}.mp3"
    return item

