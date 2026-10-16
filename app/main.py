"""栖霞山小向导 · 本地宿主（M1/M2 骨架）。

- /api/chat：SSE 流式对话（事件：delta/tool_start/tool_end/done/error）
- /api/state /api/conditions /api/data：页面状态
- /api/demo/*：演示控制台（跳点 / 前进 / 重置）
- / 静态托管 web/
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.loop import AgentLoop
from app.config import load_config, save_config
from app.runtime import resource_path
from app.services.location import LocationService
from app.services.photos import PhotoService
from app.services.route import RouteService
from app.services.session import SessionStore
from app.services.weather import ConditionsService

WEB_DIR = resource_path("web")
DATA_DIR = resource_path("app/data")
AUDIO_DIR = resource_path("app/audio")

app = FastAPI(title="栖霞山小向导", version="0.1.0")
cfg = load_config()
sessions = SessionStore()
services = {
    "location": LocationService(DATA_DIR),
    "route": RouteService(DATA_DIR),
    "weather": ConditionsService(DATA_DIR),
    "photos": PhotoService(DATA_DIR, cfg),
}
agent = AgentLoop(cfg, sessions, services)


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _state_view(state: dict) -> dict:
    return {
        "session_id": state["session_id"],
        "location": state.get("location"),
        "route": state.get("route"),
        "visited": state.get("visited", []),
        "memory": state.get("memory", []),
        "announced": state.get("announced", []),
    }


def _sync_arrival(state: dict) -> dict | None:
    """到点检测：首次进入某点位 35m 内 → 记为到访并返回播报信息（到点自动讲解数据源）。"""
    loc = state.get("location") or {}
    snapped = loc.get("snapped") or {}
    pid = snapped.get("poi_id")
    if not pid or pid in state["announced"]:
        return None
    try:
        if float(snapped.get("distance_m")) > 35:
            return None
    except (TypeError, ValueError):
        return None
    state["announced"].append(pid)
    state["visited"].append(
        {"poi_id": pid, "ts": int(loc.get("ts") or 0), "stay_s": 0}
    )
    poi = services["location"].poi(pid)
    audio = AUDIO_DIR / "poi" / f"{pid}.mp3"
    return {
        "poi_id": pid,
        "name": (poi or {}).get("name", ""),
        "line": (poi or {}).get("text_short", ""),
        "audio_url": f"/audio/poi/{pid}.mp3" if audio.exists() else None,
    }


class ChatIn(BaseModel):
    session_id: str = "demo"
    text: str


class ConfigIn(BaseModel):
    deepseek_api_key: str


class GotoIn(BaseModel):
    session_id: str = "demo"
    poi_id: str


class AdvanceIn(BaseModel):
    session_id: str = "demo"
    meters: float = 100


class ResetIn(BaseModel):
    session_id: str = "demo"


class PhotoIn(BaseModel):
    session_id: str = "demo"
    data_url: str
    photo_id: str | None = None


class RecapIn(BaseModel):
    session_id: str = "demo"
    photos: list[dict] = []


def _decode_data_url(data_url: str) -> bytes:
    raw = (data_url or "").strip()
    if not raw:
        raise HTTPException(400, "空照片")
    if "," in raw and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        raise HTTPException(400, "照片格式不对")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "model": cfg.get("model"),
        "key_configured": bool(cfg.get("deepseek_api_key")),
    }


@app.post("/api/config")
async def set_config(body: ConfigIn):
    cfg["deepseek_api_key"] = body.deepseek_api_key.strip()
    save_config(cfg)
    return {"saved": True, "key_configured": bool(cfg.get("deepseek_api_key"))}


@app.post("/api/config/test")
async def test_config():
    if not cfg.get("deepseek_api_key"):
        return {"ok": False, "message": "还没有填 Key"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10)) as client:
            resp = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {cfg['deepseek_api_key']}"},
                json={
                    "model": cfg.get("model", "deepseek-flash"),
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 4,
                    "thinking": {"type": "disabled"},
                },
            )
        if resp.status_code == 200:
            return {"ok": True, "message": "连接正常"}
        return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"网络错误：{type(e).__name__}"}


@app.get("/api/data")
async def data():
    locator = services["location"]
    return {"pois": locator.pois, "routes": locator.routes}


@app.get("/api/state")
async def get_state(session_id: str = "demo"):
    state = sessions.get(session_id)
    services["location"].ensure(state)
    return _state_view(state)


@app.get("/api/conditions")
async def conditions():
    return await services["weather"].get(days=1)


@app.get("/api/samples")
async def samples():
    """内置示例照片（一键体验海报流程用）。"""
    d = DATA_DIR / "samples"
    items = []
    if d.exists():
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                items.append({"name": p.stem, "url": f"/samples/{p.name}"})
    return {"items": items}


@app.post("/api/photo/detect")
async def photo_detect(body: PhotoIn):
    """无 GPS 照片识别（M8）：本地粗排 + Vision 直比。"""
    state = sessions.get(body.session_id)
    services["location"].ensure(state)
    raw = _decode_data_url(body.data_url)
    try:
        return await services["photos"].match_photo(raw)
    except Exception as e:  # 兜底：任何意外都变成结构化结果，前端给友好提示
        return {
            "ok": False,
            "mode": "error",
            "message": f"照片处理失败（{type(e).__name__}），换一张 JPG/PNG 再试",
            "candidates": [],
        }


@app.post("/api/recap")
async def recap(body: RecapIn):
    """海报管线入口：回放小传 + 日记文案（+ 天气背景）。"""
    state = sessions.get(body.session_id)
    services["location"].ensure(state)
    try:
        state["_conditions"] = await services["weather"].get(days=1)
    except Exception:
        state["_conditions"] = None
    out = await services["photos"].build_recap(state)
    return {
        "replay_lines": out["replay_lines"],
        "diary": out["diary"],
        "visited": [
            {
                "poi_id": v["poi_id"],
                "name": (services["location"].poi(v["poi_id"]) or {}).get("name", v["poi_id"]),
            }
            for v in state.get("visited", [])
        ],
        "memory_count": len(state.get("memory", [])),
        "conditions": (state.get("_conditions") or {}),
    }


@app.get("/audio/poi/{poi_id}.mp3")
async def poi_audio(poi_id: str):
    """预生成到点播报音频（构建期 edge-tts；缺失返回 404，前端回退浏览器 TTS）。"""
    safe = "".join(c for c in poi_id if c.isalnum() or c in "_-")
    path = AUDIO_DIR / "poi" / f"{safe}.mp3"
    if not path.exists():
        raise HTTPException(404, "no audio")
    return FileResponse(path, media_type="audio/mpeg")


@app.post("/api/demo/goto")
async def demo_goto(body: GotoIn):
    state = sessions.get(body.session_id)
    loc = services["location"].jump_to_poi(state, body.poi_id)
    if loc is None:
        return {"error": f"没有这个点位：{body.poi_id}"}
    return {"state": _state_view(state), "arrived": _sync_arrival(state)}


@app.post("/api/demo/advance")
async def demo_advance(body: AdvanceIn):
    state = sessions.get(body.session_id)
    services["location"].advance(state, body.meters)
    return {"state": _state_view(state), "arrived": _sync_arrival(state)}


@app.post("/api/demo/reset")
async def demo_reset(body: ResetIn):
    state = sessions.reset(body.session_id)
    services["location"].ensure(state)
    return {"state": _state_view(state), "arrived": None}


@app.post("/api/chat")
async def chat(body: ChatIn):
    async def gen():
        try:
            async for ev in agent.stream(body.session_id, body.text):
                yield _sse(ev)
        except Exception as e:  # 兜底：不让流中断得不明不白，前端能显示原因
            yield _sse({"type": "error", "message": f"服务端异常（{type(e).__name__}），再试一次"})
            yield _sse({"type": "done", "text": ""})

    return StreamingResponse(gen(), media_type="text/event-stream")


app.mount("/samples", StaticFiles(directory=str(DATA_DIR / "samples")), name="samples")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def run_server(port: int | None = None) -> None:
    """开发与打包共用的启动函数（端口优先取 QIXI_PORT 环境变量）。"""
    import os

    import uvicorn

    port = int(port or os.environ.get("QIXI_PORT") or cfg.get("port", 8017))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    run_server()

