"""Local desktop map API. Official JS SDK computes routes; bounded proxy adds jscode."""
import asyncio
import json
import secrets
from datetime import date
from typing import Literal
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, ConfigDict, Field
from app.config import save_config
from app.runtime import user_path
from app.services import map_navigation as nav


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Session(Input):
    session_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    generation: int


class Mode(Session):
    mode: Literal["real", "demo"]
    provider: Literal["amap","osm"] = "amap"


class MapConfig(Input):
    js_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    security_code: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$")


class RouteStart(Session):
    sequence: int = Field(ge=0)
    origin: list[float] = Field(min_length=2, max_length=2)
    destination: list[float] = Field(min_length=2, max_length=2)
    via: list[list[float]] = Field(default_factory=list, max_length=5)


class Step(Input):
    instruction: str = Field(min_length=1, max_length=300)
    at_m: float = Field(ge=0, le=40000)
    poi_id: str | None = Field(default=None, max_length=96)


class Match(Input):
    poi_id: str = Field(max_length=96)
    amap_id: str = Field(min_length=1, max_length=96)
    coord: list[float] = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1, max_length=100)


class RouteCommit(Session):
    request_id: str = Field(max_length=96)
    geometry: list[list[float]] = Field(default_factory=list, max_length=12000)
    steps: list[Step] = Field(default_factory=list, max_length=500)
    matches: list[Match] = Field(default_factory=list, max_length=20)
    duration_min: float = Field(default=0, ge=0, le=1440)
    name: str = Field(default="步行路线", max_length=100)
    error: bool = False


class RouteCancel(Session):
    request_id: str = Field(min_length=1, max_length=96)


class Locate(Session):
    pass


class Sample(Session):
    token: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    coordinate_system: Literal["GCJ-02","WGS84"]
    raw_wgs84: list[float] = Field(min_length=2, max_length=2)
    accuracy_m: float = Field(gt=0, le=100000)
    sample_at: float


class Stop(Session):
    token: str = Field(max_length=128)


class Facility(Input):
    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    lat: float
    lng: float
    coordinate_system: Literal["GCJ-02","WGS84"]
    source: str = Field(min_length=1, max_length=200)
    verified_at: str = Field(min_length=1, max_length=40)
    opening_hours: str | None = Field(default=None, max_length=100)
    accessible: bool | None = None
    notes: str = Field(default="", max_length=500)
    entrance_coord: list[float] | None = Field(default=None, min_length=2, max_length=2)
    access_verified: bool = False
    access_source: str = Field(default="", max_length=500)


class Facilities(Input):
    items: list[Facility] = Field(max_length=100)


class OSMPlan(RouteStart):
    name: str = Field(default="步行目的地",max_length=100)
    avoid_steps: bool = False
    annotation_targets: list["AnnotationTarget"] = Field(default_factory=list, max_length=7)


class AnnotationTarget(Input):
    id: str = Field(min_length=1, max_length=96)
    role: str = Field(pattern=r"^(origin|destination|via:[0-4])$")
    position_revision: str = Field(min_length=64, max_length=64)


def router(cfg, sessions, services, checked_state):
    api = APIRouter()
    proxy_slots = asyncio.Semaphore(4)
    facilities_path = user_path("config/map-facilities.json")

    def check(body):
        state = checked_state(body)
        if not nav.real_mode(state):
            raise HTTPException(409, "请先切换到真实地图模式")
        return state

    def require_free(sid):
        if sessions.lock(sid).locked():
            raise HTTPException(409, "当前对话正在更新行程，请先取消回答或等待完成后重试")

    def validate_facilities(body):
        ids = set()
        for item in body.items:
            nav.coordinate([item.lat, item.lng],services["osm"].data["bounds"] if item.coordinate_system=="WGS84" else None)
            try:
                date.fromisoformat(item.verified_at)
            except ValueError:
                raise ValueError("核实日期需为YYYY-MM-DD有效日期")
            if not item.name.strip() or not item.source.strip():
                raise ValueError("厕所名称与来源不能为空")
            if item.id in ids:
                raise ValueError("厕所ID重复")
            if item.entrance_coord is not None:
                nav.coordinate(item.entrance_coord, services["osm"].data["bounds"])
            if item.access_verified:
                if item.coordinate_system != "WGS84" or not item.entrance_coord or not item.access_source.strip():
                    raise ValueError("核实厕所接入需WGS84入口坐标及接入证据来源")
                services["osm"].snap(item.entrance_coord, max_distance=3)
            ids.add(item.id)
        return [i.model_dump() for i in body.items]

    @api.get("/api/map/config")
    async def get_config():
        return {"js_key": cfg.get("amap_js_key", ""), "configured": bool(cfg.get("amap_js_key") and cfg.get("amap_security_code")),
                "security_configured": bool(cfg.get("amap_security_code")), "coordinate_system": "GCJ-02",
                "bounds": nav.BOUNDS, "sdk_version": "2.0", "facility_status": "user_data_only",
                "default_provider":"osm","osm_ready":True,"osm_coordinate_system":"WGS84"}

    @api.post("/api/map/config")
    async def set_config(body: MapConfig):
        if cfg.get("amap_js_key") and body.js_key != cfg["amap_js_key"] and not body.security_code:
            raise HTTPException(422, "更换JS Key时请同时填写对应的安全密钥")
        code = body.security_code or cfg.get("amap_security_code", "")
        if not code:
            raise HTTPException(422, "请填写对应JS Key的安全密钥")
        updated = {**cfg, "amap_js_key": body.js_key, "amap_security_code": code}
        try:
            save_config(updated)
        except OSError:
            raise HTTPException(500, "地图配置保存失败，请检查用户目录权限")
        cfg.update(updated)
        return {"saved": True, "restart_map": True}

    @api.get("/_AMapService/{path:path}")
    async def proxy(path: str, request: Request):
        allowed = {"v3/place/text", "v3/place/around", "v3/place/polygon", "v3/place/detail",
                   "v3/direction/walking", "v4/direction/walking", "v5/direction/walking",
                   "v3/assistant/coordinate/convert", "v4/map/styles"}
        if path not in allowed:
            raise HTTPException(403, "地图代理不支持此接口")
        if len(request.url.query) > 8192:
            raise HTTPException(413, "地图查询过长")
        if not cfg.get("amap_js_key") or not cfg.get("amap_security_code"):
            raise HTTPException(409, "请先配置高德JS Key和安全密钥")
        params = [(k, v) for k, v in request.query_params.multi_items() if k not in ("jscode", "key")]
        if request.query_params.get("key") not in (None, cfg["amap_js_key"]):
            raise HTTPException(403, "地图Key不匹配")
        params += [("key", cfg["amap_js_key"]), ("jscode", cfg["amap_security_code"])]
        upstream = "https://webapi.amap.com/" if path == "v4/map/styles" else "https://restapi.amap.com/"
        try:
            async with asyncio.timeout(20):
                async with proxy_slots:
                    async with services["provider"].maps.stream("GET", upstream + path, params=params) as response:
                        if response.status_code != 200:
                            raise HTTPException(502, "高德服务暂不可用")
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 2_000_000:
                                raise HTTPException(502, "地图服务响应过大")
                            chunks.append(chunk)
                        return Response(b"".join(chunks), media_type=response.headers.get("content-type", "application/json").split(";")[0],
                                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except (httpx.HTTPError, TimeoutError):
            raise HTTPException(502, "高德网络请求失败，请重试")

    @api.post("/api/map/mode")
    async def mode(body: Mode):
        initial = checked_state(body)
        if initial.get("prefs", {}).get("map_mode") == body.mode and nav.provider(initial)==body.provider:
            return {"mode": body.mode}
        require_free(body.session_id)
        async with sessions.lock(body.session_id):
            state = checked_state(body)
            if state.get("prefs", {}).get("map_mode") == body.mode and nav.provider(state)==body.provider:
                return {"mode": body.mode}
            nav.stop(state)
            state["prefs"]["map_mode"] = body.mode
            state["prefs"]["map_provider"] = body.provider
            state["prefs"]["map_bounds"] = services["osm"].data["bounds"] if body.provider=="osm" else nav.BOUNDS
            state["route"] = None
            state["location"] = None
            state.pop("_map_intent", None)
            state["_map_pois"] = services["osm"].internal_matches(services["location"].pois) if body.provider=="osm" else {}
            sessions.save(state)
            return {"mode": body.mode}

    @api.get("/api/map/places")
    async def places(major: bool = False):
        return services["places"].catalog(major)

    @api.get("/api/map/place")
    async def place(place_id: str):
        result = services["places"].detail(place_id)
        if result is None:
            raise HTTPException(404, "没有这个景点")
        return result

    @api.get("/api/map/review")
    async def review():
        return services["places"].review

    @api.get("/api/map/osm/data")
    async def osm_data():
        result=services["osm"].public_data()
        from urllib.parse import urlsplit
        url=cfg.get("osm_tile_url","https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        parts=urlsplit(url)
        if parts.scheme!="https" or not parts.netloc or parts.username or parts.password or not all(p in url for p in ("{z}","{x}","{y}")):
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        result["tile_url"]=url
        return result

    @api.get("/api/map/osm/source")
    async def osm_source():
        return FileResponse(services["osm"].path.parent/"source.osm.gz",filename="qixiashan-source.osm.gz",media_type="application/gzip")

    @api.get("/api/map/osm/database")
    async def osm_database():
        return FileResponse(services["osm"].path,filename="qixiashan-osm-map.json",media_type="application/json")

    @api.post("/api/map/osm/plan")
    async def osm_plan(body:OSMPlan):
        require_free(body.session_id)
        async with sessions.lock(body.session_id):
            state=check(body)
            if nav.provider(state)!="osm":raise HTTPException(409,"请先切换到OSM地图")
            if body.sequence<=state.get("_map_plan_sequence",-1):raise HTTPException(409,"路线请求已过期")
            try:
                from app.services.map_annotations import AnnotationConflict
                coords={"origin":body.origin,"destination":body.destination,**{f"via:{i}":p for i,p in enumerate(body.via)}}
                try:
                    targets=services["annotations"].targets([p.model_dump() for p in body.annotation_targets],coords)
                except AnnotationConflict as e:
                    raise HTTPException(409,str(e))
                pending=nav.start_route(state,body.origin,body.destination,body.via)
                state["_map_plan_sequence"]=body.sequence
                result=services["osm"].plan(body.origin,body.destination,body.via,body.name,body.avoid_steps)
                route=nav.commit_route(state,pending["request_id"],result)
                route.update({k:result[k] for k in ("access_notes","data_version","way_ids","avoid_steps")})
                for target in targets:
                    snap=services["osm"].snap(target["coord"])
                    target.update(road_endpoint=snap["point"],gap_straight_m=round(snap["distance"],1))
                    route["access_notes"].append(f"{target['name']}：路线仅覆盖已知道路；设施与道路端点直线相距约{round(snap['distance'])}米，后续通行及入口请现场确认。")
                route["annotation_targets"]=targets
                route["constraints"]["avoid_steps"]=body.avoid_steps
                if (state.get("location") or {}).get("source")!="device":
                    state["location"]={"lat":body.origin[0],"lng":body.origin[1],"source":"manual","coordinate_system":"WGS84","snapped":{}}
                state["_map_pois"]=services["osm"].internal_matches(services["location"].pois)
                sessions.save(state)
                return route
            except ValueError as e:
                state["route"]={"status":"no_path","provider":"osm","error":{"code":"no_path","message":str(e)}}
                raise HTTPException(422,str(e))

    @api.post("/api/map/route/start")
    async def start(body: RouteStart):
        require_free(body.session_id)
        async with sessions.lock(body.session_id):
            state = check(body)
            if nav.provider(state)=="osm":raise HTTPException(409,"OSM只接受本地路网算路，请使用OSM规划入口")
            if body.sequence <= state.get("_map_plan_sequence", -1):
                raise HTTPException(409, "规划请求已过期")
            try:
                result = nav.start_route(state, body.origin, body.destination, body.via)
            except ValueError as e:
                raise HTTPException(422, str(e))
            state["_map_plan_sequence"] = body.sequence
            if (state.get("location") or {}).get("source") != "device":
                state["location"] = {"lat": body.origin[0], "lng": body.origin[1], "source": "manual", "coordinate_system": "GCJ-02", "snapped": {}}
            sessions.save(state)
            return result

    @api.post("/api/map/route/commit")
    async def commit(body: RouteCommit):
        require_free(body.session_id)
        async with sessions.lock(body.session_id):
            state = check(body)
            if nav.provider(state)=="osm":raise HTTPException(409,"OSM路线必须由本地路网生成，不能上传外部几何")
            # Validate matches before committing anything (atomic on failure).
            matches = {}
            try:
                for m in body.matches:
                    poi = services["location"].poi(m.poi_id)
                    if not poi or poi["name"] != m.name:
                        raise ValueError("讲解关联需与内部景点名称完全一致")
                    matches[m.poi_id] = {"coord": nav.coordinate(m.coord), "amap_id": m.amap_id, "name": m.name}
                result = nav.commit_route(state, body.request_id, body.model_dump())
            except ValueError as e:
                raise HTTPException(422, str(e))
            except LookupError as e:
                raise HTTPException(409, str(e))
            state["_map_pois"] = matches
            sessions.save(state)
            return result

    @api.post("/api/map/location/start")
    async def locate(body: Locate):
        state = check(body)
        nav.stop(state)
        token = secrets.token_urlsafe(24)
        state["_nav"] = {"token": token, "sequence": -1}
        return {"token": token}

    @api.post("/api/map/route/cancel")
    async def cancel_route(body: RouteCancel):
        state = check(body)
        if (state.get("route") or {}).get("request_id") == body.request_id:
            state["route"] = None
            nav.stop(state)
        return {"cancelled": True}

    @api.post("/api/map/location")
    async def sample(body: Sample):
        state = check(body)
        if not services["annotations"].ensure_route_version(state):
            raise HTTPException(409,"设施位置已更新，请重新规划")
        if not services["osm"].ensure_route_version(state):
            raise HTTPException(409, "路网版本已更新，请重新规划")
        try:
            result = nav.location_sample(state, body.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e))
        except LookupError as e:
            raise HTTPException(409, str(e))
        nav.navigation_view(state)
        return result  # location samples do not write SQLite / revision every few seconds

    @api.post("/api/map/stop")
    async def stop(body: Stop):
        state = check(body)
        if (state.get("_nav") or {}).get("token") != body.token:
            raise HTTPException(409, "导航已经停止或更新")
        nav.stop(state)
        return {"stopped": True}

    @api.get("/api/map/facilities")
    async def facilities():
        try:
            items = validate_facilities(Facilities(items=json.loads(facilities_path.read_text(encoding="utf-8")))) if facilities_path.exists() else []
        except (ValueError, OSError):
            raise HTTPException(422, "厕所数据文件无效，请重新导入")
        return {"items": items, "status": "available" if items else "厕所位置待补充"}

    @api.post("/api/map/facilities/preview")
    async def preview(body: Facilities):
        try:
            return {"items": validate_facilities(body), "count": len(body.items)}
        except ValueError as e:
            raise HTTPException(422, str(e))

    @api.post("/api/map/facilities/import")
    async def import_facilities(body: Facilities):
        import os
        import tempfile
        try:
            items = validate_facilities(body)
        except ValueError as e:
            raise HTTPException(422, str(e))
        fd, temp = tempfile.mkstemp(dir=facilities_path.parent, prefix="facilities-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, facilities_path)
        except OSError:
            raise HTTPException(500, "厕所数据保存失败")
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return {"saved": True, "count": len(items)}

    return api
