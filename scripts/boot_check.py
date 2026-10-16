"""启动自检：真正拉起 uvicorn → 请求 health / 首页 / 静态资源 → 自动关闭。

用法： .venv\\Scripts\\python scripts\\boot_check.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

PORT = int(os.environ.get("QIXI_TEST_PORT", "8017"))


def probe(server: uvicorn.Server) -> None:
    base = f"http://127.0.0.1:{PORT}"
    time.sleep(4)
    try:
        r = urllib.request.urlopen(f"{base}/api/health", timeout=10)
        print("[PASS] /api/health ->", r.read().decode("utf-8"))
    except Exception as e:
        print("[FAIL] /api/health ->", e)
    try:
        r = urllib.request.urlopen(f"{base}/", timeout=10)
        body = r.read()
        ok = r.status == 200 and len(body) > 500
        print(f"[{'PASS' if ok else 'FAIL'}] 首页 -> {r.status} len={len(body)}")
    except Exception as e:
        print("[FAIL] 首页 ->", e)
    try:
        r = urllib.request.urlopen(f"{base}/js/app.js", timeout=10)
        body = r.read()
        ok = r.status == 200 and len(body) > 500
        print(f"[{'PASS' if ok else 'FAIL'}] 静态资源 app.js -> {r.status} len={len(body)}")
    except Exception as e:
        print("[FAIL] app.js ->", e)
    for path in ("/poster.html", "/poster/poster-app.js", "/poster/skill/renderer/render.js",
                 "/vendor/html-to-image.js", "/poster/skill/motifs/maple_leaf_line.svg"):
        try:
            r = urllib.request.urlopen(f"{base}{path}", timeout=10)
            body = r.read()
            ok = r.status == 200 and len(body) > 80
            print(f"[{'PASS' if ok else 'FAIL'}] {path} -> {r.status} len={len(body)}")
        except Exception as e:
            print(f"[FAIL] {path} ->", e)
    server.should_exit = True


def main() -> int:
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=probe, args=(server,), daemon=True).start()
    server.run()
    print("boot check 完成，服务已自动关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())

