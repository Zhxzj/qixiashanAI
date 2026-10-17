"""定位吸附与模拟行进（M1/M2 骨架版）。"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

EARTH_R = 6371000.0


def _load(path) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dist_m(a, b) -> float:
    """两坐标（lat, lng）间近似距离（米）。"""
    lat1, lng1 = a
    lat2, lng2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def bearing_text(a, b) -> str:
    lat1, lng1 = a
    lat2, lng2 = b
    y = math.sin(math.radians(lng2 - lng1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.cos(math.radians(lng2 - lng1))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    dirs = ["正北", "东北", "正东", "东南", "正南", "西南", "正西", "西北"]
    return dirs[int((deg + 22.5) % 360 // 45)]


class LocationService:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.pois = _load(self.data_dir / "poi.json")
        self.routes = _load(self.data_dir / "routes.json")
        self.poi_by_id = {p["poi_id"]: p for p in self.pois}

    def poi(self, poi_id: str):
        return self.poi_by_id.get(poi_id)

    def snap(self, lat: float, lng: float) -> dict:
        """吸附到最近路线顶点 + 最近点位（80m 内）。"""
        best = None
        for route in self.routes:
            for idx, vertex in enumerate(route["geometry"]):
                d = dist_m((lat, lng), tuple(vertex))
                if best is None or d < best["distance_m"]:
                    best = {
                        "route_id": route["route_id"],
                        "point_idx": idx,
                        "distance_m": round(d, 1),
                    }
        if best is None:
            best = {"route_id": None, "point_idx": 0, "distance_m": None}
        near = self.nearest_pois(lat, lng, limit=1, radius_m=80)
        best["route_distance_m"] = best["distance_m"]
        best["poi_id"] = near[0]["poi_id"] if near else None
        best["poi_distance_m"] = near[0]["distance_m"] if near else None
        best["distance_m"] = best["poi_distance_m"]
        return {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            **best,
        }

    def nearest_pois(self, lat: float, lng: float, limit: int = 3, radius_m: float | None = None) -> list:
        items = []
        for p in self.pois:
            d = dist_m((lat, lng), tuple(p["coord"]))
            if radius_m is not None and d > radius_m:
                continue
            items.append(
                {
                    "poi_id": p["poi_id"],
                    "name": p["name"],
                    "distance_m": round(d, 1),
                    "bearing": bearing_text((lat, lng), tuple(p["coord"])),
                    "category": p["category"],
                    "one_liner": p["text_short"],
                }
            )
        items.sort(key=lambda x: x["distance_m"])
        return items[:limit]

    def ensure(self, state: dict) -> dict:
        if not state.get("location"):
            if state.get("prefs", {}).get("map_mode") == "real":
                state["location"] = {"lat": None, "lng": None, "source": "unavailable", "snapped": {}}
                return state["location"]
            sm = self.pois[0]
            lat, lng = sm["coord"]
            state["location"] = {
                "lat": lat,
                "lng": lng,
                "source": "sim",
                "confidence": 0.9,
                "ts": int(time.time()),
                "snapped": self.snap(lat, lng),
            }
        return state["location"]

    def set_position(self, state: dict, lat: float, lng: float, source: str = "sim") -> dict:
        state["location"] = {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "source": source,
            "confidence": 0.9,
            "ts": int(time.time()),
            "snapped": self.snap(lat, lng),
        }
        return state["location"]

    def jump_to_poi(self, state: dict, poi_id: str):
        p = self.poi_by_id.get(poi_id)
        if not p:
            return None
        lat, lng = p["coord"]
        return self.set_position(state, lat, lng)


    def advance(self, state: dict, meters: float) -> dict:
        from app.services.geometry import project, length, at
        loc = self.ensure(state)
        plan = state.get("route")
        if plan and plan.get("status") == "ready":
            geo = plan["geometry"]
        else:
            route = next((r for r in self.routes if r["route_id"] == loc["snapped"].get("route_id")), self.routes[0])
            geo = route["geometry"]
        offset = project((loc["lat"],loc["lng"]),geo)[0]
        progress = min(length(geo), max(0, offset + max(0,float(meters))))
        pos = at(geo,progress)
        result = self.set_position(state,*pos)
        if plan and plan.get("status") == "ready":
            plan["progress_m"] = progress
            plan["remaining_m"] = max(0,round(plan["total_m"]-progress))
            while plan["current_step"] < len(plan["steps"]) and plan["steps"][plan["current_step"]]["at_m"] <= progress+1:
                plan["current_step"] += 1
        return result
