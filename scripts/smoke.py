"""冒烟自测：不依赖 LLM 的端到端检查（M1/M2 验收）。

用法： .venv\\Scripts\\python scripts\\smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

RESULTS: list = []


def check(name: str, cond: bool, extra: str = "") -> None:
    RESULTS.append((name, bool(cond), extra))
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  {extra}" if extra else ""))


def main() -> int:
    client = TestClient(app)

    r = client.get("/api/health")
    check("health 接口", r.status_code == 200 and r.json().get("ok"))

    data = client.get("/api/data").json()
    check(
        "数据加载（>=10 点位 / 3 路线）",
        len(data["pois"]) >= 10 and len(data["routes"]) >= 3,
        f"pois={len(data['pois'])} routes={len(data['routes'])}",
    )

    st = client.get("/api/state", params={"session_id": "t1"}).json()
    check(
        "初始定位在山门附近",
        ((st.get("location") or {}).get("snapped") or {}).get("poi_id") == "shanmen",
    )

    out = client.post(
        "/api/demo/goto", json={"session_id": "t1", "poi_id": "qianfoyan"}
    ).json()
    check("跳转到千佛岩并触发到点", (out.get("arrived") or {}).get("poi_id") == "qianfoyan")

    out2 = client.post(
        "/api/demo/goto", json={"session_id": "t1", "poi_id": "qianfoyan"}
    ).json()
    check("同点位不重复播报", out2.get("arrived") is None)

    out = client.post(
        "/api/demo/advance", json={"session_id": "t1", "meters": 120}
    ).json()
    new_lng = out["state"]["location"]["lng"]
    check("模拟行进更新坐标", new_lng != 118.9581, f"lng={new_lng}")

    # ---- 工具层直测 ----
    from app.tools import load_tools

    schemas, handlers = load_tools()
    check(
        "七件套工具注册",
        len(schemas) == 7 and all(s["function"]["name"] in handlers for s in schemas),
        ",".join(s["function"]["name"] for s in schemas),
    )

    from app.services.location import LocationService
    from app.services.route import RouteService
    from app.services.session import SessionStore
    from app.services.weather import ConditionsService

    data_dir = ROOT / "app" / "data"
    services = {
        "location": LocationService(data_dir),
        "route": RouteService(data_dir),
        "weather": ConditionsService(data_dir),
    }
    store = SessionStore()
    st1 = store.get("t2")
    services["location"].ensure(st1)
    ctx = {"state": st1, "services": services}

    out = asyncio.run(handlers["get_location"]({}, ctx))
    check("get_location 返回吸附点", (out.get("snapped") or {}).get("poi_id") == "shanmen")

    out = asyncio.run(
        handlers["get_poi"]({"poi_id": "qianfoyan", "detail": "short"}, ctx)
    )
    check("get_poi 千佛岩资料", "294" in (out.get("text") or "") or "294" in str(out.get("facts")))

    out = asyncio.run(
        handlers["plan_route"]({"to": "fenglinhu", "consider_weather": False}, ctx)
    )
    check(
        "plan_route 出步骤",
        len(out.get("steps", [])) >= 2,
        f"distance={out.get('distance_m')}m steps={len(out.get('steps', []))}",
    )

    out = asyncio.run(handlers["save_memory"]({"note": "第一次看见红叶"}, ctx))
    check("save_memory 记录", out.get("saved") is True and out.get("total") == 1)

    out = asyncio.run(handlers["navigate_hint"]({}, ctx))
    check("navigate_hint 出文本", isinstance(out.get("text"), str) and bool(out["text"]))

    cond = client.get("/api/conditions").json()
    check(
        "天气/红叶接口（网络或兜底）",
        cond.get("source") in ("open-meteo", "fallback") and "red_leaf" in cond,
        f"source={cond.get('source')} tip={cond.get('red_leaf', {}).get('text')}",
    )

    # ---- M3/M4/M6 新增能力 ----
    out = client.post(
        "/api/demo/goto", json={"session_id": "t3", "poi_id": "qianfoyan"}
    ).json()
    check("到点信息带语音地址", "audio_url" in (out.get("arrived") or {}),
          str((out.get("arrived") or {}).get("audio_url")))

    r = client.get("/api/samples")
    check("示例照片接口", r.status_code == 200 and len(r.json().get("items", [])) >= 1,
          f"{len(r.json().get('items', []))} 张")

    audio = client.get("/audio/poi/qianfoyan.mp3")
    check("预生成语音可下载", audio.status_code == 200 and len(audio.content) > 2000,
          f"{len(audio.content)} bytes")

    rec = client.post(
        "/api/recap", json={"session_id": "t3", "photos": []}
    ).json()
    check(
        "回放小传三行",
        len(rec.get("replay_lines", [])) == 3 and bool((rec.get("diary") or {}).get("title")),
        f"{(rec.get('replay_lines') or [''])[0][:24]}…",
    )

    det = client.post(
        "/api/photo/detect",
        json={"session_id": "t3", "data_url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="},
    ).json()
    check(
        "照片识别接口有降级路径",
        det.get("mode") in ("no_refs", "no_key", "vision", "vision_failed", "error"),
        f"mode={det.get('mode')}",
    )

    h = client.get("/api/health").json()
    if not h.get("key_configured"):
        with client.stream(
            "POST", "/api/chat", json={"session_id": "t1", "text": "你好"}
        ) as resp:
            body = "".join(resp.iter_text())
        check("未配 Key 时友好报错", '"error"' in body and "API Key" in body)
    else:
        check("未配 Key 时友好报错", True, "跳过：本机已配置 Key")

    failed = [x for x in RESULTS if not x[1]]
    print("-" * 44)
    print(f"共 {len(RESULTS)} 项，失败 {len(failed)} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

