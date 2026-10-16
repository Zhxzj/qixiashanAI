"""工具：list_nearby —— 周边点位（可按方向过滤）。"""

from __future__ import annotations

import math

from app.services.location import bearing_text, dist_m

SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_nearby",
        "description": "列出游客周边的景点（按距离排序），可选半径与方向过滤。游客问附近有什么、前面是什么时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "radius_m": {"type": "integer", "description": "搜索半径（米），默认 300"},
                "direction": {
                    "type": "string",
                    "enum": ["front", "left", "right", "back", "all"],
                    "description": "相对行进方向过滤，默认 all",
                },
                "limit": {"type": "integer", "description": "返回数量上限，默认 5"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def _heading_angle(locator, snapped) -> float | None:
    """由当前吸附点与下一顶点估算行进方向（北为 0，顺时针，度）。"""
    route = next(
        (r for r in locator.routes if r["route_id"] == snapped.get("route_id")), None
    )
    if not route:
        return None
    geo = route["geometry"]
    idx = snapped.get("point_idx", 0)
    if idx >= len(geo) - 1:
        idx = max(0, len(geo) - 2)
    a, b = geo[idx], geo[idx + 1]
    dy = b[0] - a[0]
    dx = b[1] - a[1]
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def _bearing_angle(a, b) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    y = math.sin(math.radians(lng2 - lng1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.cos(math.radians(lng2 - lng1))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


async def run(args, ctx):
    locator = ctx["services"]["location"]
    loc = locator.ensure(ctx["state"])
    radius = int(args.get("radius_m", 300) or 300)
    limit = int(args.get("limit", 5) or 5)
    direction = args.get("direction", "all")
    pos = (loc["lat"], loc["lng"])
    heading = _heading_angle(locator, loc.get("snapped") or {})

    items = []
    for p in locator.pois:
        d = dist_m(pos, tuple(p["coord"]))
        if d > radius:
            continue
        if direction != "all" and heading is not None:
            delta = (_bearing_angle(pos, tuple(p["coord"])) - heading) % 360
            if direction == "front" and not (delta <= 60 or delta >= 300):
                continue
            if direction == "right" and not (60 < delta <= 150):
                continue
            if direction == "back" and not (150 < delta <= 210):
                continue
            if direction == "left" and not (210 < delta < 300):
                continue
        items.append(
            {
                "poi_id": p["poi_id"],
                "name": p["name"],
                "distance_m": round(d, 1),
                "bearing": bearing_text(pos, tuple(p["coord"])),
                "category": p["category"],
                "one_liner": p["text_short"],
            }
        )
    items.sort(key=lambda x: x["distance_m"])
    return {"items": items[:limit]}

