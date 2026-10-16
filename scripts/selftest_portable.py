"""便携包自检（演示前 / 发给别人前跑一遍）：

1) 便携 Python 能导入依赖与应用（fastapi/uvicorn/httpx/PIL + app.main）；
2) 双击 start.bat 的实际链路（pythonw 静默启动）能起服务、/api/health 通过；
3) 结束后尽量把测试进程收掉。

用法：
    .venv\\Scripts\\python scripts\\selftest_portable.py
    .venv\\Scripts\\python scripts\\selftest_portable.py --stage dist\\枫客松-小栖-demo-free --port 8017
退出码 0 = 通过。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _health(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return bool(json.loads(r.read().decode("utf-8", "ignore")).get("ok"))
    except Exception:
        return False


def _listening_pid(port: int) -> str | None:
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        for line in (r.stdout or "").splitlines():
            if "LISTENING" not in line:
                continue
            m = re.search(rf"127\.0\.0\.1:{port}\s+.*LISTENING\s+(\d+)", line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=str(ROOT / "dist" / "枫客松-小栖-demo-free"))
    ap.add_argument("--port", type=int, default=8017)
    args = ap.parse_args()

    stage = Path(args.stage)
    py = stage / "runtime" / "python" / "python.exe"
    if not py.exists():
        print(f"[FAIL] 没找到便携运行时：{py}（先跑 scripts\\build_portable.bat）")
        return 1

    ok_all = True

    # 1) 导入探针
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = f"{stage};{stage / 'runtime' / 'packages'}"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [str(py), "-c", "import fastapi, uvicorn, httpx, PIL, app.main; print('import OK')"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120,
    )
    probe_ok = r.returncode == 0
    ok_all &= probe_ok
    print(f"[{'PASS' if probe_ok else 'FAIL'}] 依赖与应用可导入"
          + ("" if probe_ok else f"：{(r.stderr or '')[-300:]}"))

    # 2) start.bat 实际链路
    if _health(args.port):
        print(f"[WARN] 端口 {args.port} 上已有本程序在跑，先停掉再测（scripts\\stop.bat）。")
        return 1 if not ok_all else 0

    run_env = dict(env)
    run_env["QIXI_NO_BROWSER"] = "1"
    log_path = stage / "launcher.log"
    try:
        subprocess.run(["cmd", "/c", "start.bat"], cwd=str(stage), env=run_env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    except Exception as e:
        print(f"[WARN] 调 start.bat 出错（继续等端口）：{type(e).__name__}")

    boot_ok = False
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(1.0)
        if _health(args.port):
            boot_ok = True
            break
    ok_all &= boot_ok
    print(f"[{'PASS' if boot_ok else 'FAIL'}] start.bat 链路能起服务（http://127.0.0.1:{args.port}）")

    # 3) 收尾
    pid = _listening_pid(args.port) if boot_ok else None
    if pid:
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=20)
            time.sleep(1.5)
            stopped = not _health(args.port)
        except Exception:
            stopped = False
        ok_all &= stopped
        print(f"[{'PASS' if stopped else 'FAIL'}] 关闭后端口释放（pid={pid}）")
    else:
        print("[WARN] 没找到监听进程，跳过关闭检查")

    if not boot_ok and log_path.exists():
        print("---- launcher.log 尾部 ----")
        print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
