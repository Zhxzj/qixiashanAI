"""路线规划（骨架版，含天气感知入口）。"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.location import dist_m


def _load(path) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class RouteService:
    def __init__(self, data_dir):
        self.routes = _load(Path(data_dir) / "routes.json")
        self.pois = {p["poi_id"]: p for p in _load(Path(data_dir) / "poi.json")}

    def route_of_poi(self, poi_id: str):
        for r in self.routes:
            if any(pt["poi_id"] == poi_id for pt in r["points"]):
                return r
        return None

    def plan(
        self,
        state: dict,
        to: str,
        via: list | None = None,
        theme: str = "classic",
        consider_weather: bool = True,
        conditions: dict | None = None,
    ) -> dict:
        poi = self.pois.get(to)
        route = self.route_of_poi(to)
        fallback_used = False
        if route is None:
            route = next(r for r in self.routes if r["route_id"] == "classic")
            fallback_used = True

        loc = state.get("location") or {}
        snapped = loc.get("snapped") or {}
        same = snapped.get("route_id") == route["route_id"]
        start_idx = snapped.get("point_idx", 0) if same else 0
        if not same:
            fallback_used = True

        target_idx = len(route["geometry"]) - 1
        for pt in route["points"]:
            if pt["poi_id"] == to:
                target_idx = pt["geo_idx"]
                break
        if target_idx < start_idx:
            target_idx = start_idx

        geo = route["geometry"]
        total = 0.0
        for i in range(start_idx, target_idx):
            total += dist_m(tuple(geo[i]), tuple(geo[i + 1]))

        steps = []
        for pt in route["points"]:
            if start_idx < pt["geo_idx"] <= target_idx:
                name = self.pois[pt["poi_id"]]["name"]
                steps.append(
                    {
                        "poi_id": pt["poi_id"],
                        "instruction": f"前往{name}",
                        "stay_s": pt.get("stay_s", 120),
                    }
                )
        if not steps:
            name = (poi or {}).get("name", to)
            steps.append({"poi_id": to, "instruction": f"前往{name}", "stay_s": 120})

        stay_s = sum(s["stay_s"] for s in steps)
        duration_min = max(1, round(total / 45 + stay_s / 60))

        weather_note = None
        light_tip = None
        attrs = route.get("attrs", {})
        if consider_weather and conditions:
            today = (conditions.get("weather", {}) or {}).get("today", {}) or {}
            rain = today.get("rain_prob") or 0
            if rain >= 50:
                if attrs.get("slippery_risk", 0) >= 3:
                    weather_note = f"今天下雨概率 {rain}%，这条线石阶多，走慢点"
                else:
                    weather_note = f"今天下雨概率 {rain}%，带上伞"
            tmax = today.get("max") or 0
            if tmax >= 28 and attrs.get("shade_ratio", 0) < 0.5:
                weather_note = (
                    (weather_note + "；") if weather_note else ""
                ) + "日头烈，中途多在树荫歇脚"
            sunset = today.get("sunset")
            light = (poi or {}).get("best_light")
            if sunset and light in ("傍晚", "暮"):
                light_tip = f"落日约 {sunset}，{(poi or {}).get('photo_spot', '这里')}看晚霞正好"

        state["route"] = {
            "route_id": route["route_id"],
            "to": to,
            "current_step": 0,
            "remaining_m": round(total),
        }
        return {
            "route_id": route["route_id"],
            "theme": route.get("theme", theme),
            "name": (poi or {}).get("name", to),
            "to": to,
            "distance_m": round(total),
            "duration_min": duration_min,
            "steps": steps,
            "geometry": geo[start_idx : target_idx + 1],
            "fallback_used": fallback_used,
            "weather_note": weather_note,
            "light_tip": light_tip,
        }

