"""Local host: ordered domain state, streaming chat and bounded image requests."""
from __future__ import annotations
import asyncio
import base64
import copy
import hashlib
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, Field
from app.agent.loop import AgentLoop
from app.config import load_config, save_config
from app.runtime import resource_path, user_path, APP_ID, API_VERSION, BUILD_ID
from app.services.location import LocationService, dist_m
from app.services.photos import PhotoService
from app.services.route import RouteService
from app.services.session import SessionStore
from app.services.weather import ConditionsService
from app.services.provider import Provider
from app.services.osm_map import OSMMapService
from app.services.places import PlaceService
from app.services import map_navigation as map_nav
from app.map_api import router as map_router
from app.annotations_api import router as annotations_router
from app.services.map_annotations import AnnotationStore
from app.ui_version import info as ui_info, WEB_REVISION
from app.services import page_credentials

WEB_DIR=resource_path("web")
DATA_DIR=resource_path("app/data")
AUDIO_DIR=resource_path("app/audio")
cfg=load_config()
sessions=SessionStore(user_path("state/sessions.sqlite3"))
provider=Provider()
services={"location":LocationService(DATA_DIR),"route":RouteService(DATA_DIR),"weather":ConditionsService(DATA_DIR),"photos":PhotoService(DATA_DIR,cfg),"provider":provider}
services["osm"]=OSMMapService(DATA_DIR)
services["places"]=PlaceService(DATA_DIR)
services["annotations"]=AnnotationStore(DATA_DIR/"map_annotations.json", user_path("config/map-annotations.json"), services["osm"].data["bounds"])
services["route"].osm=services["osm"]
agent=AgentLoop(cfg,sessions,services)
INSTANCE_ID=os.environ.get("QIXI_INSTANCE_ID") or uuid.uuid4().hex
CONTROL_TOKEN=os.environ.get("QIXI_CONTROL_TOKEN") or secrets.token_urlsafe(32)
recap_tasks={}
config_revision=0
media_slots=asyncio.Semaphore(2)
media_pending=0

@asynccontextmanager
async def lifespan(app):
    await provider.start()
    services["weather"].client=provider.weather
    services["photos"].client=provider.media
    yield
    for task in list(recap_tasks.values()):
        task.cancel()
    if recap_tasks:
        await asyncio.gather(*recap_tasks.values(),return_exceptions=True)
    await provider.close()

app=FastAPI(title="栖霞山小向导",version="0.6.0",lifespan=lifespan)
@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, error):
    if request.url.path == "/api/config":
        return JSONResponse({"detail":"Key格式无效，请重新输入（最多512个字符）"},422,headers={"Cache-Control":"no-store"})
    return await request_validation_exception_handler(request,error)
app.include_router(annotations_router(services["annotations"]))

@app.middleware("http")
async def local_guard(request:Request,call_next):
    if request.url.hostname not in ("127.0.0.1","localhost"):
        return JSONResponse({"detail":"无效本机地址"},403)
    origin=request.headers.get("origin")
    if origin and origin!=str(request.base_url).rstrip("/"):
        return JSONResponse({"detail":"只允许本机应用页面操作"},403)
    if request.url.path.startswith(("/api/map/","/_AMapService/")) and request.headers.get("sec-fetch-site")=="cross-site":
        return JSONResponse({"detail":"地图仅允许本机应用页面使用"},403)
    if request.method=="POST":
        if request.url.path.startswith("/api/map/annotations") and len(await request.body())>4096:
            return JSONResponse({"detail":"标注请求过大"},413)
        try:
            if int(request.headers.get("content-length","0"))>17_000_000:
                return JSONResponse({"detail":"请求太大，请压缩照片后再试"},413)
        except ValueError:
            return JSONResponse({"detail":"无效请求大小"},400)
    credential_context = page_credentials.request_key.set(page_credentials.get_key(request.headers.get("x-qixi-page", "")))
    page_context = page_credentials.request_page.set(request.headers.get("x-qixi-page", ""))
    try:
        response=await call_next(request)
    finally:
        page_credentials.request_key.reset(credential_context)
        page_credentials.request_page.reset(page_context)
    if request.url.path.startswith(("/api/","/js/","/css/")) or request.url.path in ("/","/index.html"):
        response.headers["Cache-Control"]="no-store"
    return response

def _sse(obj):
    return "data: "+json.dumps(obj,ensure_ascii=False)+"\n\n"

def _state_view(state):
    services["annotations"].ensure_route_version(state)
    services["osm"].ensure_route_version(state)
    navigation = map_nav.navigation_view(state)
    return {**{k:state.get(k) for k in ("session_id","generation","revision","location","route","visited","memory","announced")},
            "map_mode":state.get("prefs",{}).get("map_mode","demo"), "map_provider":map_nav.provider(state), "map_intent":state.get("_map_intent"), "navigation":navigation}

def _sync_arrival(state,now=None):
    if not services["annotations"].ensure_route_version(state):
        return None
    if not services["osm"].ensure_route_version(state):
        state.pop("_arrival_pending", None)
        return None
    now=time.monotonic() if now is None else now
    loc=state.get("location") or {}
    if map_nav.real_mode(state):
        if not map_nav.quality(state):
            state.pop("_arrival_pending",None)
            return None
    snap=loc.get("snapped") or {}
    pid=snap.get("poi_id")
    poi=services["location"].poi(pid)
    reference = (state.get("_map_pois",{}).get(pid) or {}).get("coord") if map_nav.real_mode(state) else (poi or {}).get("coord")
    distance=dist_m((loc["lat"],loc["lng"]),reference) if poi and reference else float("inf")
    if map_nav.real_mode(state):
        distance += loc.get("accuracy_m",float("inf"))
    pending=state.get("_arrival_pending")
    if pending:
        visit=next((v for v in reversed(state["visited"]) if v["poi_id"]==pending["poi_id"]),None)
        elapsed=int(now-pending["entered"])
        if visit and elapsed>visit["stay_s"]:
            visit["stay_s"]=elapsed
            sessions.save(state,bump=False)
    if not poi or distance>35:
        state.pop("_arrival_pending",None)
        return None
    if pid in state["announced"]:
        return None
    if not pending or pending["poi_id"]!=pid:
        state["_arrival_pending"]={"poi_id":pid,"entered":now,"sample_at":loc.get("sample_at",0)}
        return None
    if now-pending["entered"]<8:
        return None
    if map_nav.real_mode(state) and loc.get("sample_at",0)-pending.get("sample_at",0)<5:
        return None
    state["announced"].append(pid)
    state["visited"].append({"poi_id":pid,"ts":int(time.time()),"stay_s":int(now-pending["entered"]),"source":loc.get("source","sim")})
    audio=AUDIO_DIR/"poi"/f"{pid}.mp3"
    event={"event_id":uuid.uuid4().hex,"poi_id":pid,"name":poi["name"],"line":poi.get("text_short",""),"audio_url":f"/audio/poi/{pid}.mp3" if audio.exists() else None}
    sessions.save(state)
    return event

Sid=Annotated[str,Field(min_length=1,max_length=96,pattern=r"^[A-Za-z0-9_-]+$")]
class SessionIn(BaseModel):
    session_id:Sid="demo"
    generation:int|None=None
class ChatIn(SessionIn):
    text:str=Field(min_length=1,max_length=8000)
    request_id:Sid=Field(default_factory=lambda:uuid.uuid4().hex)
class ConfigIn(BaseModel):
    deepseek_api_key:str=Field(max_length=512)
class GotoIn(SessionIn):
    poi_id:str
class AdvanceIn(SessionIn):
    meters:float=Field(default=100,ge=0,le=5000,allow_inf_nan=False)
class PhotoIn(SessionIn):
    data_url:str=Field(max_length=16_800_000)
    photo_id:Sid|None=None
    allow_cloud:bool=False
class PhotoMeta(BaseModel):
    id:Sid
    poi_id:str|None=None
    source:str="unknown"
    ts:int|None=None
class RecapIn(SessionIn):
    photos:list[PhotoMeta]=Field(default_factory=list,max_length=12)
class CancelIn(SessionIn):
    request_id:Sid|None=None
class ControlIn(BaseModel):
    token:str
    action:str="exit"

def checked_state(body):
    st=sessions.get(body.session_id)
    if body.generation is not None and st["generation"]!=body.generation:
        raise HTTPException(409,"行程已重置，请刷新")
    services["location"].ensure(st)
    return st

def _decode_data_url(value):
    raw=value.split(",",1)[-1] if value.startswith("data:") else value
    try:
        data=base64.b64decode(raw,validate=True)
    except ValueError:
        raise HTTPException(400,"照片格式不对")
    if not data or len(data)>12_000_000:
        raise HTTPException(413,"识别图片需在 12MB 内")
    return data

@app.get("/api/health")
async def health():
    return {"ok":True,"app_id":APP_ID,"build_id":BUILD_ID,"api_version":API_VERSION,"instance_id":INSTANCE_ID,"model":cfg["model"],"key_configured":bool(cfg["deepseek_api_key"])}

@app.get("/api/ui-version")
async def ui_version():
    return ui_info()

@app.get("/")
@app.get("/index.html")
async def index():
    html=(WEB_DIR/"index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__WEB_REVISION__",WEB_REVISION).replace("__UI_INFO__",json.dumps(ui_info(),ensure_ascii=False)))

@app.post("/api/config")
async def set_config(body:ConfigIn, request:Request):
    global config_revision
    try:
        page_credentials.set_key(request.headers.get("x-qixi-page", ""), body.deepseek_api_key.strip())
    except ValueError as error:
        raise HTTPException(400,str(error))
    config_revision+=1
    return {"saved":False,"memory_only":True,"key_configured":bool(body.deepseek_api_key.strip())}

@app.post("/api/config/forget")
async def forget_config(body:dict):
    page=body.get("page_id", "")
    if not page_credentials.valid_page(page):
        raise HTTPException(400,"无效页面")
    page_credentials.forget(page)
    return {"forgotten":True}

@app.post("/api/config/test")
async def test_config():
    if not cfg["deepseek_api_key"]:
        return {"ok":False,"message":"还没有填 Key"}
    try:
        async with asyncio.timeout(25):
            resp=await provider.chat.post("https://api.deepseek.com/chat/completions",headers={"Authorization":f"Bearer {cfg['deepseek_api_key']}"},json={"model":cfg["model"],"messages":[{"role":"user","content":"ping"}],"max_tokens":4,"thinking":{"type":"disabled"}})
        return {"ok":resp.status_code==200,"message":"连接正常" if resp.status_code==200 else f"HTTP {resp.status_code}，请检查 Key 或稍后重试"}
    except (httpx.HTTPError,TimeoutError) as e:
        return {"ok":False,"message":f"网络错误：{type(e).__name__}"}

@app.get("/api/app")
async def app_info():
    return {"instance_id":INSTANCE_ID,"control_token":CONTROL_TOKEN}

@app.get("/api/diagnostics")
async def diagnostics():
    return {**await health(),"data_status":"draft_pending_verification","runtime":"portable/source","storage":"当前用户目录","photo_persistence":False,"shutdown_available":hasattr(app.state,"server")}

@app.post("/api/app/control")
async def control(body:ControlIn):
    if not secrets.compare_digest(body.token,CONTROL_TOKEN):
        raise HTTPException(403,"实例验证失败")
    if body.action!="exit" or not hasattr(app.state,"server"):
        raise HTTPException(409,"请在启动器中退出应用")
    async def stop():
        await asyncio.sleep(0.2)
        app.state.server.should_exit=True
    asyncio.create_task(stop())
    return {"stopping":True}

@app.get("/api/data")
async def data():
    locator=services["location"]
    return {"pois":locator.pois,"routes":locator.routes,"data_status":"draft_pending_verification"}

@app.get("/api/state")
async def get_state(session_id:Sid="demo"):
    # Long chat turns own the write queue; polling can still read a coherent
    # snapshot without waiting for the model. Arrival evaluation resumes after it.
    if sessions.lock(session_id).locked():
        return {**copy.deepcopy(_state_view(sessions.get(session_id))),"arrived":None}
    async with sessions.lock(session_id):
        st=sessions.get(session_id)
        services["location"].ensure(st)
        event=_sync_arrival(st)
        return {**_state_view(st),"arrived":event}

@app.get("/api/conditions")
async def conditions():
    return await services["weather"].get()

@app.get("/api/samples")
async def samples():
    return {"items":[{"name":p.stem,"url":f"/samples/{p.name}"} for p in sorted((DATA_DIR/"samples").glob("*.jpg"))]}

@app.post("/api/photo/detect")
async def detect(body:PhotoIn):
    global media_pending
    checked_state(body)
    if media_pending>=8:
        raise HTTPException(429,"照片任务较多，请稍后再试")
    media_pending+=1
    try:
        async with asyncio.timeout(85):
            async with media_slots:
                raw=_decode_data_url(body.data_url)
                out=await services["photos"].match_photo(raw,allow_cloud=body.allow_cloud)
                return {**out,"photo_id":body.photo_id}
    except TimeoutError:
        raise HTTPException(503,"照片识别超时，请手动选择地点或重试")
    finally:
        media_pending-=1

async def make_recap(snapshot,photos):
    snapshot["photos"]=photos
    snapshot["_conditions"]=await services["weather"].get()
    out=await services["photos"].build_recap(snapshot)
    return {**out,"visited":[{"poi_id":v["poi_id"],"name":services["location"].poi(v["poi_id"])["name"]} for v in snapshot["visited"]],"memory_count":len(snapshot["memory"]),"conditions":snapshot["_conditions"],"snapshot_revision":snapshot["revision"]}

@app.post("/api/recap")
async def recap(body:RecapIn):
    async with sessions.lock(body.session_id):
        snapshot=copy.deepcopy(checked_state(body))
    photos=[p.model_dump() for p in body.photos]
    for p in photos:
        if p["poi_id"] is not None and not services["location"].poi(p["poi_id"]):
            raise HTTPException(422,"照片点位无效")
        if p["source"] not in ("manual","gps","sample"):
            p["poi_id"]=None
    key=hashlib.sha256(json.dumps([body.session_id,snapshot["generation"],snapshot["revision"],snapshot["visited"],photos,cfg["model"],config_revision,page_credentials.request_page.get()],sort_keys=True).encode()).hexdigest()
    if key not in recap_tasks:
        if len(recap_tasks)>=32:
            for k,t in list(recap_tasks.items()):
                if t.done():
                    recap_tasks.pop(k,None)
        if len(recap_tasks)>=32:
            raise HTTPException(429,"日记任务较多，请稍后重试")
        recap_tasks[key]=asyncio.create_task(make_recap(snapshot,photos))
    try:
        async with asyncio.timeout(95):
            result=await asyncio.shield(recap_tasks[key])
    except Exception:
        recap_tasks.pop(key,None)
        raise HTTPException(503,"日记生成未完成，请稍后重试")
    current=sessions.get(body.session_id)
    if (current["generation"],current["revision"])!=(snapshot["generation"],snapshot["revision"]):
        raise HTTPException(409,"行程已更新，请重新生成")
    return result

@app.post("/api/demo/goto")
async def goto(body:GotoIn):
    async with sessions.lock(body.session_id):
        st=checked_state(body)
        map_nav.stop(st)
        st["prefs"]["map_mode"]="demo"
        if services["location"].jump_to_poi(st,body.poi_id) is None:
            raise HTTPException(404,"没有这个点位")
        st["route"]=None
        event=_sync_arrival(st)
        sessions.save(st)
        return {"state":_state_view(st),"arrived":event}

@app.post("/api/demo/advance")
async def advance(body:AdvanceIn):
    async with sessions.lock(body.session_id):
        st=checked_state(body)
        map_nav.stop(st)
        if map_nav.real_mode(st):
            st["prefs"]["map_mode"]="demo"
            st["location"]=None
            st["route"]=None
        services["location"].advance(st,body.meters)
        event=_sync_arrival(st)
        sessions.save(st)
        return {"state":_state_view(st),"arrived":event}

@app.post("/api/demo/reset")
async def reset(body:SessionIn):
    previous_mode=sessions.get(body.session_id).get("prefs",{}).get("map_mode","demo")
    previous_provider=map_nav.provider(sessions.get(body.session_id))
    st=sessions.reset(body.session_id)
    st["prefs"]["map_mode"]=previous_mode
    st["prefs"]["map_provider"]=previous_provider
    st["prefs"]["map_bounds"]=services["osm"].data["bounds"] if previous_provider=="osm" else map_nav.BOUNDS
    if previous_provider=="osm":st["_map_pois"]=services["osm"].internal_matches(services["location"].pois)
    services["location"].ensure(st)
    sessions.save(st,bump=False)
    return {"state":_state_view(st),"arrived":None}

@app.post("/api/chat/cancel")
async def cancel(body:CancelIn):
    sessions.cancel(body.session_id,body.request_id)
    return {"cancelled":True}

@app.post("/api/chat")
async def chat(body:ChatIn):
    async def gen():
        try:
            async for ev in agent.stream(body.session_id,body.text,body.request_id,body.generation):
                yield _sse(ev)
        except Exception as e:
            yield _sse({"type":"error","message":f"服务异常（{type(e).__name__}），请重试"})
            yield _sse({"type":"done","text":"","status":"failed"})
    return StreamingResponse(gen(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})

@app.get("/audio/poi/{poi_id}.mp3")
async def audio(poi_id:str):
    if not services["location"].poi(poi_id):
        raise HTTPException(404,"no audio")
    path=AUDIO_DIR/"poi"/f"{poi_id}.mp3"
    if not path.exists():
        raise HTTPException(404,"no audio")
    return FileResponse(path,media_type="audio/mpeg")

app.include_router(map_router(cfg,sessions,services,checked_state))
app.mount("/samples",StaticFiles(directory=DATA_DIR/"samples"),name="samples")
app.mount("/",StaticFiles(directory=WEB_DIR,html=True),name="web")

def run_server(port=None):
    import uvicorn
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=int(port or os.environ.get("QIXI_PORT") or cfg["port"]),log_level="warning"))
    app.state.server=server
    server.run()
if __name__=="__main__":
    run_server()
