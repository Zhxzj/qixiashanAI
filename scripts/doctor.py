"""环境自检（给使用手册和 troubleshooting 用）。

用法：.venv\\Scripts\\python scripts\\doctor.py
检查：Python 版本 / 依赖 / 端口 / DeepSeek 连通 / Open-Meteo 连通 / 素材与语音是否齐。
"""

from __future__ import annotations

import json
import socket
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK = "[OK]  "
BAD = "[!!]  "


def line(mark: str, text: str) -> None:
    print(mark + text)


def check_python() -> None:
    v = sys.version_info
    ok = v >= (3, 10)
    line(OK if ok else BAD, f"Python {v.major}.{v.minor}.{v.micro}" + ("" if ok else "（需要 3.10 以上）"))


def check_deps() -> None:
    missing = []
    for mod in ("fastapi", "uvicorn", "httpx", "PIL", "edge_tts"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    core_missing = [m for m in missing if m in ("fastapi", "uvicorn", "httpx")]
    if core_missing:
        line(BAD, "核心依赖缺失：" + ", ".join(core_missing) + "（跑一遍 scripts\\start.bat 会自动装）")
    elif missing:
        line(OK, "核心依赖齐全（可选组件缺失：" + ", ".join(missing) + "，只在重跑素材/语音脚本时需要）")
    else:
        line(OK, "依赖齐全（fastapi / uvicorn / httpx / Pillow / edge-tts）")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) != 0


def check_ports() -> None:
    free = [p for p in (8017, 8018, 8019, 8020, 8021, 8022) if port_free(p)]
    if len(free) == 6:
        line(OK, "端口 8017-8022 全部空闲")
    elif free:
        line(OK, f"端口 {free[0]} 可用（其余被占用，启动脚本会自动选空闲端口）")
    else:
        line(BAD, "8017–8022 都被占用。先关掉占用程序，或运行 scripts\\stop.bat")


def probe(url: str, timeout: int = 6) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200, str(r.status)
    except Exception as e:
        return False, type(e).__name__


def check_network_and_key() -> None:
    from app.config import load_config

    cfg = load_config()
    key = cfg.get("deepseek_api_key") or ""
    if not key:
        line(BAD, "DeepSeek Key 未配置（页面右上角填上就能对话；不填也能看地图和海报流程）")
        return
    ok, info = probe("https://api.deepseek.com", timeout=8)
    line(OK if ok else BAD, f"DeepSeek 接口可达（{info}），Key 已配置（{key[:6]}…）" if ok else f"DeepSeek 接口不可达（{info}）：检查网络/公司代理")


def check_weather() -> None:
    ok, info = probe("https://api.open-meteo.com/v1/forecast?latitude=32.15&longitude=118.95&current=temperature_2m")
    line(OK if ok else BAD, "Open-Meteo 天气可达" if ok else f"Open-Meteo 不可达（{info}）：页面会回落到本地手工数据，不影响其他功能")


def check_assets() -> None:
    pois = len(json.loads((ROOT / "app" / "data" / "poi.json").read_text(encoding="utf-8")))
    samples = len(list((ROOT / "app" / "data" / "samples").glob("*.jpg")))
    refs = len(list((ROOT / "app" / "data" / "refs").glob("*")))
    audio = len(list((ROOT / "app" / "audio" / "poi").glob("*.mp3")))
    line(OK, f"数据：点位 {pois} 个 · 示例照片 {samples} 张 · 参考图目录 {refs} 个 · 播报语音 {audio} 条")
    if audio == 0:
        line(BAD, "没有播报语音：跑 scripts\\make_audio.py 重新生成（需要联网）")


def main() -> int:
    print("栖霞山小向导 · 环境自检")
    print("-" * 46)
    check_python()
    check_deps()
    check_ports()
    check_assets()
    check_network_and_key()
    check_weather()
    print("-" * 46)
    print("自检结束。" + time.strftime("%H:%M:%S"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
