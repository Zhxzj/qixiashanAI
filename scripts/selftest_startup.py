"""启动链路自检（开发用）：按"没有 PYTHONPATH 的干净环境"起一次服务，验证：
找环境 → 装依赖 → 选端口 → 起服务 → /api/health 通过。

用法：
    .venv\\Scripts\\python scripts\\selftest_startup.py [--port 8022]
退出码 0 = 通过。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8022)
    ap.add_argument("--timeout", type=int, default=40)
    args = ap.parse_args()

    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["QIXI_TEST_PORT"] = str(args.port)
    env["QIXI_NO_BROWSER"] = "1"
    env["TEMP"] = str(ROOT / ".tmp")

    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        print("[FAIL] 没有 .venv，先跑 start.bat", flush=True)
        return 1

    proc = subprocess.Popen(
        [str(py), "scripts/sync_bootstrap.py"], cwd=str(ROOT), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    ok = False
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(0.6)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=1) as r:
                ok = bool(json.loads(r.read().decode("utf-8", "ignore")).get("ok"))
                if ok:
                    break
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    out = b""
    try:
        out = proc.communicate(timeout=8)[0] or b""
    except Exception:
        pass
    text = out.decode("utf-8", "replace")
    broke = "ModuleNotFoundError" in text or "Traceback" in text

    print(f"[{'PASS' if ok else 'FAIL'}] 服务在 {args.port} 起得来")
    print(f"[{'PASS' if not broke else 'FAIL'}] 无导入错误/异常")
    if broke:
        tail = "\n".join(text.strip().splitlines()[-8:])
        print(tail.encode("utf-8", "replace").decode("utf-8"))
    return 0 if (ok and not broke) else 1


if __name__ == "__main__":
    sys.exit(main())
