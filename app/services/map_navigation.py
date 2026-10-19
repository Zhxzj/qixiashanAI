"""GCJ-02 navigation, transient official results, ordered requests; no SDK secrets."""
import math
import time
import uuid
from app.services.location import dist_m
from app.services.geometry import project, length

BOUNDS = (118.91, 32.12, 119.01, 32.20)  # working extent, not a legal park boundary


def coordinate(value, bounds=None):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("坐标应为[纬度,经度]")
    lat, lng = value
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError("坐标必须为有限数值")
    bounds=bounds or BOUNDS
    if not (bounds[1] <= lat <= bounds[3] and bounds[0] <= lng <= bounds[2]):
        raise ValueError("点位不在栖霞山工作范围内，请核对同名地点")
    return [float(lat), float(lng)]


def real_mode(state):
    return state.get("prefs", {}).get("map_mode") == "real"


def provider(state):
    return state.get("prefs", {}).get("map_provider", "amap")


def coordinate_system(state):
    return "WGS84" if provider(state)=="osm" else "GCJ-02"


def stop(state):
    state.pop("_nav", None)
    state.pop("_arrival_pending", None)
    state.pop("_map_off_since", None)
    if (state.get("location") or {}).get("source") == "device":
        state["location"]["navigation_eligible"] = False


def start_route(state, origin, destination, via=None):
    stop(state)
    bounds=state.get("prefs",{}).get("map_bounds",BOUNDS)
    route = {"status": "pending", "request_id": uuid.uuid4().hex,
             "origin": coordinate(origin,bounds), "destination": coordinate(destination,bounds), "bounds":bounds,
             "via_coords": [coordinate(p,bounds) for p in (via or [])], "coordinate_system": coordinate_system(state),
             "provider": provider(state), "data_status": "provider_request_pending", "created_at": time.time()}
    state["route"] = route
    state.pop("_map_intent", None)
    return route


def commit_route(state, request_id, payload):
    pending = state.get("route") or {}
    if pending.get("request_id") != request_id or pending.get("status") != "pending":
        raise LookupError("规划已被新请求替代，请使用最新路线")
    if time.time() - pending["created_at"] > 90:
        raise LookupError("规划请求已过期，请重试")
    if payload.get("error"):
        state["route"] = {**pending, "status": "no_path", "error": {"code": "provider_unavailable", "message": "高德未能返回连续步行路线，请重新选择起终点"}}
        return state["route"]
    geo = [coordinate(p,pending.get("bounds")) for p in payload["geometry"]]
    if not 2 <= len(geo) <= 12000:
        raise ValueError("路线顶点数量无效")
    if dist_m(geo[0], pending["origin"]) > 150 or dist_m(geo[-1], pending["destination"]) > 150:
        raise ValueError("路线端点偏移过大，请核对可通行入口")
    if any(dist_m(a, b) > 500 for a, b in zip(geo, geo[1:])):
        raise ValueError("路线存在过大断点，不能用直线补齐")
    total = length(geo)
    if total < 2 or total > 40000:
        raise ValueError("路线长度不合理")
    steps = []
    previous = 0
    for s in payload["steps"]:
        at = s["at_m"]
        if not math.isfinite(at) or at < previous or at > total + 30:
            raise ValueError("路线分段进度无效")
        steps.append({"instruction": s["instruction"][:300], "at_m": min(at, total), "poi_id": s.get("poi_id")})
        previous = at
    if not steps:
        raise ValueError("步行方案没有步骤")
    for via in pending.get("via_coords", []):
        if project(via, geo)[2] > 150:
            raise ValueError("路线没有覆盖途经点")
    is_osm=pending.get("provider")=="osm"
    state["route"] = {**pending, "status": "ready", "data_status": "osm_local_not_field_verified" if is_osm else "amap_provider_not_field_verified",
                      "route_id": request_id, "geometry": geo, "steps": steps, "current_step": 0,
                      "total_m": round(total, 1), "distance_m": round(total), "remaining_m": round(total),
                      "progress_m": 0.0, "duration_min": payload["duration_min"], "name": payload["name"][:100],
                      "navigation_status": "stopped", "fallback_used": False,
                      "constraints": {"theme_applied": False, "weather_applied": False},
                      "weather_note": "OSM本地步行路网；未验证现场开放情况，不保证无台阶或实时封闭信息。" if is_osm else "高德推荐步行路线；未验证现场开放情况，主题、遮阴与台阶条件未作保证。"}
    return state["route"]


def quality(state, now=None):
    now = time.time() if now is None else now
    loc = state.get("location") or {}
    nav = state.get("_nav") or {}
    return bool(real_mode(state) and nav.get("token") and loc.get("source") == "device"
                and loc.get("coordinate_system") == coordinate_system(state) and loc.get("navigation_eligible")
                and 0 <= now - loc.get("sample_at", 0) <= 15
                and 0 < loc.get("accuracy_m", float("inf")) <= 25)


def location_sample(state, body, now=None):
    now = time.time() if now is None else now
    nav = state.get("_nav") or {}
    if not nav.get("token") or nav["token"] != body["token"]:
        raise LookupError("导航已停止，请重新开始定位")
    if body["sequence"] <= nav.get("sequence", -1):
        raise LookupError("过期的位置样本")
    lat, lng = body["lat"], body["lng"]
    raw = body["raw_wgs84"]
    expected=coordinate_system(state)
    if body.get("coordinate_system", "GCJ-02")!=expected:
        raise ValueError("定位坐标系与当前地图不一致，请重新开始定位")
    # Device can be outside the park: show its range honestly, never snap it into the park.
    for xy in ([lat, lng], raw):
        if len(xy) != 2 or any(not math.isfinite(v) for v in xy) or not (-90 <= xy[0] <= 90 and -180 <= xy[1] <= 180):
            raise ValueError("设备坐标无效")
    if dist_m(raw, [lat, lng]) > 1500:
        raise ValueError("坐标转换偏移异常")
    if expected=="WGS84" and dist_m(raw,[lat,lng])>0.2:
        raise ValueError("OSM直接使用WGS84，不应进行高德坐标转换")
    age = now - body["sample_at"]
    if age < -5 or age > 30:
        raise ValueError("定位已过期，请重新获取")
    accuracy = body["accuracy_m"]
    if not math.isfinite(accuracy) or not 0 < accuracy <= 100000:
        raise ValueError("定位精度无效")
    previous = state.get("location") or {}
    if previous.get("source") == "device" and body["sample_at"] <= previous.get("sample_at", 0):
        raise LookupError("位置时间没有前进")
    eligible = age <= 15 and accuracy <= 25
    reason = None if eligible else "定位精度或新鲜度不足，实时判断暂停"
    if previous.get("source") == "device":
        dt = body["sample_at"] - previous.get("sample_at", 0)
        if 0 < dt < 30 and dist_m([lat, lng], [previous["lat"], previous["lng"]]) > 15 * dt + accuracy + previous.get("accuracy_m", 0):
            # Do not replace the trusted baseline with a teleport (next sample must still pass).
            previous["navigation_eligible"] = False
            state.pop("_arrival_pending", None)
            nav["sequence"] = body["sequence"]
            return {"accepted": False, "reason": "定位跳变，等待稳定样本", "eligible": False}
    if body["sample_at"] - previous.get("sample_at", 0) > 15:
        state.pop("_arrival_pending", None)
    nav["sequence"] = body["sequence"]
    state["location"] = {"lat": lat, "lng": lng, "raw_wgs84": raw, "source": "device",
                         "coordinate_system": expected, "sample_at": body["sample_at"], "ts": int(body["sample_at"]),
                         "accuracy_m": accuracy, "navigation_eligible": eligible, "snapped": {}}
    if not eligible:
        state.pop("_arrival_pending", None)
    # Only explicit official POI-to-internal-ID matches may drive legacy narration.
    nearby = []
    for pid, poi in state.get("_map_pois", {}).items():
        d = dist_m([lat, lng], poi["coord"])
        nearby.append((d, pid))
    if nearby and eligible:
        d, pid = min(nearby)
        state["location"]["snapped"] = {"poi_id": pid if d <= 35 else None, "poi_distance_m": d}
    return {"accepted": True, "eligible": eligible, "reason": reason}


def navigation_view(state, now=None):
    now = time.time() if now is None else now
    route = state.get("route") or {}
    if route.get("status") == "pending" and now - route.get("created_at", 0) > 90:
        route["status"] = "no_path"
        route["error"] = {"code": "expired", "message": "规划已过期，请重新规划"}
    valid = quality(state, now)
    if route.get("provider") not in ("amap","osm") or route.get("status") != "ready":
        return {"active": bool(state.get("_nav")), "eligible": valid, "status": "no_route"}
    if not valid:
        route["navigation_status"] = "waiting_location" if state.get("_nav") else "stopped"
        state.pop("_map_off_since", None)
        return {"active": bool(state.get("_nav")), "eligible": False, "status": route["navigation_status"]}
    loc = state["location"]
    pos = [loc["lat"], loc["lng"]]
    offset, _, off, _ = project(pos, route["geometry"])
    threshold = max(35, 2 * loc["accuracy_m"])
    if off > threshold:
        state.setdefault("_map_off_since", now)
        status = "off_route" if now - state["_map_off_since"] >= 8 else "checking_deviation"
    else:
        state.pop("_map_off_since", None)
        status = "on_route"
        route["progress_m"] = round(offset, 1)
        route["remaining_m"] = round(max(0, route["total_m"] - offset))
        route["current_step"] = next((i for i, s in enumerate(route["steps"]) if s["at_m"] > offset + 2), len(route["steps"]))
        # Projection alone is not arrival; require actual proximity with uncertainty included.
        target = next((p for p in route.get("annotation_targets", []) if p["role"] == "destination"), None)
        if target:
            if dist_m(pos, target["road_endpoint"]) + loc["accuracy_m"] <= 35:
                status = "road_endpoint_nearby"
        elif dist_m(pos, route["destination"]) + loc["accuracy_m"] <= 35:
            status = "destination_nearby"
    route["navigation_status"] = status
    return {"active": True, "eligible": True, "status": status, "off_route_m": round(off),
            "progress_m": route["progress_m"], "remaining_m": route["remaining_m"]}
