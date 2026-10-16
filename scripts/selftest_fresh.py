"""模拟“新电脑首次运行”：系统 Python → 自动建 venv → 切换解释器 → 服务起得来。

用法（开发机）：
    .venv\\Scripts\\python scripts\\selftest_fresh.py [--port 8050]
    .venv\\Scripts\\python scripts\\selftest_fresh.py --in-repo [--port 8053]
        （--in-repo：不复制，直接在仓库里用系统 Python 跑一次，专门测“切换解释器”）

原理：在 .tmp\\fresh-sim 里复制一份最小工程（app/web/scripts/requirements.txt），
用“系统 Python”（不是仓库 .venv）跑 sync_bootstrap.py，验证：
    1) 能自动创建 sim\\.venv 并装依赖；
    2) 日志出现“切换到专用环境重启”（防止用系统 Python import 依赖失败）；
    3) /api/health 能通。
全过程隔离在 .tmp\\fresh-sim，不碰仓库现有 .venv。
退出码 0 = 通过。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / ".tmp" / "fresh-sim"


def _system_python() -> str | None:
    """找一个“非本仓库 venv”的 Python（模拟别人电脑上的系统 Python）。"""
    cands: list[str] = []
    which = shutil.which("python")
    if which:
        cands.append(which)
    for p in (Path("C:/Python314/python.exe"), Path("C:/Python313/python.exe"), Path("C:/Python312/python.exe")):
        cands.append(str(p))
    try:
        repo_venv = str((ROOT / ".venv" / "Scripts" / "python.exe").resolve()).lower()
    except Exception:
        repo_venv = ""
    for c in cands:
        try:
            if "windowsapps" in c.lower():
                continue
            if not Path(c).exists():
                continue
            if str(Path(c).resolve()).lower() == repo_venv:
                continue
            return c
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--in-repo", action="store_true",
                    help="不复制：直接在仓库里用系统 Python 跑同步脚本（测切换解释器）")
    args = ap.parse_args()

    sys_py = _system_python()
    if not sys_py:
        print("[FAIL] 找不到可用的“系统 Python”来做模拟（需要 3.10+，且不是仓库 .venv）。")
        return 1
    print(f"[info] 用系统 Python：{sys_py}")

    SIM.mkdir(parents=True, exist_ok=True)
    if args.in_repo:
        target = ROOT
        log_file = SIM / "sim-inrepo.log"
    else:
        if SIM.exists():
            try:
                shutil.rmtree(SIM)
            except Exception:
                pass
        SIM.mkdir(parents=True)
        (SIM / ".tmp").mkdir(exist_ok=True)  # 给 venv/ensurepip/pip 用的可写临时目录
        for d in ("app", "web", "scripts"):
            shutil.copytree(ROOT / d, SIM / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "requirements.txt", SIM / "requirements.txt")
        target = SIM
        log_file = SIM / "sim.log"

    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["QIXI_TEST_PORT"] = str(args.port)
    env["QIXI_NO_BROWSER"] = "1"
    env["TEMP"] = str(target / ".tmp")
    env["PYTHONIOENCODING"] = "utf-8"
    (target / ".tmp").mkdir(parents=True, exist_ok=True)

    print("[info] 起一个“新电脑首次运行”的 sync_bootstrap（建 venv / 装依赖可能 1-3 分钟）…")
    with open(log_file, "wb") as lf:
        proc = subprocess.Popen(
            [sys_py, str(target / "scripts" / "sync_bootstrap.py")],
            cwd=str(target), env=env, stdin=subprocess.PIPE, stdout=lf, stderr=subprocess.STDOUT,
        )
    ok = False
    deadline = time.time() + args.timeout
    while time.time() < deadline and proc.poll() is None:
        time.sleep(1.0)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=1) as r:
                if json.loads(r.read().decode("utf-8", "ignore")).get("ok"):
                    ok = True
                    break
        except Exception:
            pass
    # 连子进程树一起收掉（首次运行会“切换解释器”再起一个子进程）
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=20)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    time.sleep(0.5)

    text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    switched = "切换到专用环境重启" in text
    booted = "服务已就绪" in text
    venv_ok = (target / ".venv" / "Scripts" / "python.exe").exists()
    label = "已有 .venv（仓库模式，复用）" if args.in_repo else "自动创建了 .venv"
    print(f"[{'PASS' if venv_ok else 'FAIL'}] {label}")
    print(f"[{'PASS' if switched else 'FAIL'}] 首次运行时切换到了 venv 解释器")
    print(f"[{'PASS' if ok or booted else 'FAIL'}] 服务能起来（health={ok}, 日志就绪={booted}）")
    if not (venv_ok and switched and (ok or booted)):
        print("---- 日志尾部 ----")
        print("\n".join(text.strip().splitlines()[-15:]))
        print(f"（完整日志：{log_file}）")
        return 1
    print(f"[PASS] 首次运行路径全通（{'仓库' if args.in_repo else '模拟'}目录：{target}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
