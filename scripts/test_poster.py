"""海报端到端自测（可选，需本机装有 agent-browser + Chrome）：起服务 → 打开 /poster.html
→ 示例照片 → 生成候选 → 截图。

注意：Codex 沙箱内 Chrome 起不来（mojo 权限），请在自己的终端跑；沙箱里用
`node tools/test_poster_dom.mjs` 做无头校验。

用法（沙箱或本机均可）：
    python scripts/test_poster.py
产物：.tmp/poster_test/ 下若干 PNG + result.txt
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8021
OUT = ROOT / ".tmp" / "poster_test"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")


def sh(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / ".support")
    env["TEMP"] = str(ROOT / ".tmp")
    print("$", " ".join(args[:4]) + (" …" if len(args) > 4 else ""))
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace")


def wait_health() -> bool:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # 1) 起服务（独立进程，detached）；若端口已占用则直接复用
    if not wait_health():
        DETACHED = 0x00000008 | 0x00000200
        proc = subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
            cwd=str(ROOT), creationflags=DETACHED,
            env={**os.environ, "PYTHONPATH": str(ROOT / ".support"), "TEMP": str(ROOT / ".tmp")},
        )
        print(f"[0] 服务 PID={proc.pid}")
        if not wait_health():
            print("[FAIL] 服务没起来")
            return 1
    print("[0] 服务就绪 http://127.0.0.1:%d" % PORT)

    log: list[str] = []

    def step(*args: str, timeout: int = 180) -> str:
        r = sh(list(args), timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        log.append(out)
        return out

    results: list[str] = []
    try:
        step("agent-browser", "open", f"http://127.0.0.1:{PORT}/poster.html")
        snap = step("agent-browser", "snapshot", "-i", "-c")
        for line in snap.splitlines():
            if "button" in line or "link" in line:
                print("   ", line.strip()[:100])

        step("agent-browser", "click", "#samplesBtn")
        step("agent-browser", "wait", "--timeout", "3000")
        n = step("agent-browser", "get", "count", ".thumb").strip()
        results.append(f"示例照片：{n} 张")

        step("agent-browser", "click", "#genBtn")
        step("agent-browser", "wait", "--timeout", "12000")
        n_cand = step("agent-browser", "get", "count", ".cand").strip()
        results.append(f"候选数：{n_cand}")
        cand_text = step("agent-browser", "get", "text", "#candRow")
        results.append("候选构成：" + cand_text.replace("\n", " / ")[:160])
        qa = step("agent-browser", "get", "text", "#qaBox")
        results.append("质检：" + qa.replace("\n", " | ")[:400])

        step("agent-browser", "screenshot", "--selector", "#stage", str(OUT / "cand_0.png"))
        step("agent-browser", "click", ".cand:nth-child(2)")
        step("agent-browser", "wait", "--timeout", "4000")
        step("agent-browser", "screenshot", "--selector", "#stage", str(OUT / "cand_1.png"))
        step("agent-browser", "screenshot", str(OUT / "page.png"))

        # 顺手测向导页（到点播报卡片存在）
        step("agent-browser", "open", f"http://127.0.0.1:{PORT}/")
        step("agent-browser", "wait", "--timeout", "2500")
        guide = step("agent-browser", "snapshot", "-i", "-c")
        has_script = "#scriptBtn" in guide or "剧本" in guide
        results.append(f"向导页剧本按钮：{'有' if has_script else '没找到'}")
        step("agent-browser", "screenshot", str(OUT / "guide.png"))
    except Exception as e:
        results.append(f"异常：{type(e).__name__} {e}")
    finally:
        try:
            step("agent-browser", "close")
        except Exception:
            pass  # 没装 agent-browser 时忽略

    text = "\n".join(results)
    (OUT / "result.txt").write_text(text, encoding="utf-8")
    (OUT / "raw_log.txt").write_text("\n---\n".join(log), encoding="utf-8")
    print("-" * 52)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
