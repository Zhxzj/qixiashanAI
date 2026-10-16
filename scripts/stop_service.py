"""停止本程序的服务（找监听 8017/8018/8019 的 python 进程并结束）。

中文提示由本脚本输出（.bat 保持纯 ASCII，避免编码问题）。
用法：scripts\\stop.bat  →  python scripts\\stop_service.py
"""

from __future__ import annotations

import re
import subprocess
import sys

PORTS = (8017, 8018, 8019, 8020, 8021, 8022)


def listening_pids() -> dict[str, int]:
    """{pid: port}，来自 netstat 的 LISTENING 行。"""
    found: dict[str, int] = {}
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        for line in (r.stdout or "").splitlines():
            if "LISTENING" not in line:
                continue
            m = re.search(r"127\.0\.0\.1:(\d+)\s+.*LISTENING\s+(\d+)", line)
            if not m:
                continue
            port, pid = int(m.group(1)), m.group(2)
            if port in PORTS:
                found[pid] = port
    except Exception as e:
        print(f"查询端口占用失败：{type(e).__name__} {e}")
    return found


def process_name(pid: str) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        )
        return (r.stdout or "").strip().lower()
    except Exception:
        return ""


def main() -> int:
    pids = listening_pids()
    if not pids:
        print("没有发现正在运行的小向导服务（端口 8017-8022）。")
        return 0
    killed = 0
    for pid, port in pids.items():
        name = process_name(pid)
        if name and not name.startswith("python"):
            print(f"端口 {port} 被 {name}（PID {pid}）占用，不是小向导的进程，跳过。")
            continue
        r = subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        if r.returncode == 0:
            print(f"已停止 PID {pid}（端口 {port}）")
            killed += 1
        else:
            print(f"PID {pid} 停止失败：{(r.stderr or r.stdout or '').strip()[:120]}")
    if killed == 0:
        print("没有停掉任何进程（可能服务本来就没跑）。")
    else:
        print(f"共停止 {killed} 个进程。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
