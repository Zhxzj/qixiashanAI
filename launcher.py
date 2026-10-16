"""打包版启动器（也是 PyInstaller 的入口）。

流程：读配置端口 → 探测已有服务（有就直接开页面）→ 选空闲端口 →
起服务（后台线程）→ 等就绪 → 按偏好打开浏览器 → 浏览器关闭后自动停服。

开发机不用它（用根目录 start.bat）；打包版 exe 就是它。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PORT_CANDIDATES = (8017, 8018, 8019, 8020, 8021, 8022)


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _healthy(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _find_free_port() -> int:
    for p in PORT_CANDIDATES:
        if not _port_busy(p):
            return p
    return 0


def _open_browser(url: str) -> tuple[subprocess.Popen | None, str]:
    """优先用 Edge/Chrome 的 --app 窗口；返回 (进程, 浏览器名)。"""
    if os.environ.get("QIXI_NO_BROWSER"):
        print(f"  （QIXI_NO_BROWSER=1，跳过打开浏览器；地址：{url}）")
        return None, "（未打开）"
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates = [
        ("Edge", Path(pf86) / "Microsoft/Edge/Application/msedge.exe"),
        ("Edge", Path(pf) / "Microsoft/Edge/Application/msedge.exe"),
        ("Chrome", Path(pf) / "Google/Chrome/Application/chrome.exe"),
        ("Chrome", Path(pf86) / "Google/Chrome/Application/chrome.exe"),
    ]
    for name, exe in candidates:
        if exe.exists():
            return subprocess.Popen([str(exe), f"--app={url}"]), name
    os.startfile(url)  # type: ignore[attr-defined]  # 默认浏览器兜底
    return None, "默认浏览器"


def _pause(msg: str) -> None:
    """交互暂停：有终端就等回车；无终端（pythonw 打包版）弹系统提示框，绝不抛异常。"""
    try:
        input(msg)
        return
    except (EOFError, KeyboardInterrupt):
        return
    except Exception:
        pass
    if os.environ.get("QIXI_NO_BROWSER"):
        return  # 测试/无头环境
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "栖霞山小向导", 0x40)
    except Exception:
        time.sleep(3)


def _init_streams() -> None:
    """pythonw（无控制台）下 stdout/stderr 是 None：重定向到日志文件，错误不再被吞。

    “双击没反应”的绝大多数情况都能靠这个日志定位。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from app.runtime import user_path

        path = user_path("launcher.log")
    except Exception:
        base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "QixiGuide"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        path = base / "launcher.log"
    try:
        f = open(path, "a", encoding="utf-8", buffering=1)
    except Exception:
        return
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f
    try:
        print(f"===== 启动于 {time.strftime('%Y-%m-%d %H:%M:%S')} · {path} =====", flush=True)
    except Exception:
        pass


def main() -> int:
    _init_streams()
    argv = sys.argv[1:]
    if "--install" in argv:
        return install_env()
    if "--server" in argv:
        from app.main import run_server

        run_server()
        return 0
    return run_app()


def install_env() -> int:
    """给源码版用：找 Python → 建 venv → 装依赖（中文提示都从这里出）。"""
    import shutil
    import subprocess

    from app.runtime import IS_FROZEN

    root = Path(__file__).resolve().parent
    print("=" * 46)
    print("  栖霞山小向导 · 安装")
    print("=" * 46)

    def _valid(cmd: list[str]) -> bool:
        probe = cmd + [
            "-c",
            "import sys;raise SystemExit(0 if sys.version_info.major==3 and sys.version_info.minor>=10 or sys.version_info.major>3 else 1)",
        ]
        try:
            return subprocess.run(probe, capture_output=True, timeout=20).returncode == 0
        except Exception:
            return False

    candidates: list[list[str]] = []
    p = shutil.which("python")
    if p and "WindowsApps" not in p:  # 跳过“微软应用商店”假 python
        candidates.append([p])
    p2 = shutil.which("py")
    if p2:
        candidates.append([p2, "-3"])
    py_cmd = next((c for c in candidates if _valid(c)), None)
    if py_cmd is None:
        print("[错误] 没有找到 Python 3.10 以上。")
        print("  请到 https://www.python.org/downloads/ 安装 Python 3.10 以上，")
        print("  安装时务必勾选 “Add python.exe to PATH”，然后重新双击。")
        return 1
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        print(f"[1/2] 运行环境已存在：{venv_py}")
    else:
        print("[1/2] 首次运行：创建运行环境（约 1 分钟）…")
        r = subprocess.run(py_cmd + ["-m", "venv", str(root / ".venv")], cwd=str(root))
        if r.returncode != 0:
            print("[错误] 创建 venv 失败。公司电脑常见原因是 Python 没装全，试试重装并勾选 Add to PATH。")
            return 1
    print("[2/2] 检查依赖…")
    r = subprocess.run(
        [str(venv_py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-r", str(root / "requirements.txt"), "-i", "https://pypi.org/simple"],
        cwd=str(root),
    )
    if r.returncode != 0:
        print("[错误] 依赖安装失败（多半是网络）。可以：")
        print("  1) 确认能访问 pypi.org 后重试；")
        print("  2) 或在能联网的机器上先跑一次，把整个文件夹（含 .venv）拷过来。")
        return 1
    print("安装完成。")
    return 0


def run_app() -> int:
    """默认入口：保活式启动（打包版与源码版通用）。"""
    from app.config import load_config
    from app.main import run_server
    from app.runtime import describe

    if "--check" in sys.argv:
        # 打包后的布局自检：只报路径与资源可达性，不启动服务
        import app.main as m

        env = describe()
        checks = {
            "web/index.html": (m.WEB_DIR / "index.html").exists(),
            "web/poster.html": (m.WEB_DIR / "poster.html").exists(),
            "app/data/poi.json": (m.DATA_DIR / "poi.json").exists(),
            "app/audio/poi": (m.AUDIO_DIR / "poi").exists(),
        }
        print("布局自检：")
        for k, v in env.items():
            print(f"  {k:14s} {v}")
        for k, v in checks.items():
            print(f"  [{'OK' if v else '缺'}] {k}")
        return 0 if all(checks.values()) else 1

    env = describe()
    cfg = load_config()
    print("栖霞山小向导 · 打包版启动器")
    print(f"  程序目录： {env['app_dir']}")
    print(f"  数据目录： {env['user_dir']}")

    # 1) 已有服务在跑？直接开页面
    for p in PORT_CANDIDATES:
        if _healthy(p):
            url = f"http://127.0.0.1:{p}"
            print(f"  检测到服务已在运行：{url}")
            proc, name = _open_browser(url)
            if proc is None:
                _pause("  已用默认浏览器打开，按回车退出本窗口（服务仍在运行，可在任务管理器结束 QixiGuide.exe）…")
            else:
                proc.wait()
                print(f"  {name} 窗口已关闭。服务保持运行（数据目录里没有遗留进程管理）。")
            return 0

    # 2) 选端口并起服务
    preferred = int(cfg.get("port") or 8017)
    port = preferred if not _port_busy(preferred) else _find_free_port()
    if port == 0:
        _pause("8017–8022 都被占用，请先关闭占用程序，然后重新打开。按回车退出…")
        return 1

    os.environ["QIXI_PORT"] = str(port)
    threading.Thread(target=run_server, args=(port,), daemon=True).start()

    deadline = time.time() + 40
    while time.time() < deadline:
        if _healthy(port):
            break
        time.sleep(0.7)
    else:
        _pause("服务 40 秒内没有起来。把本窗口截图发给开发者。按回车退出…")
        return 1

    url = f"http://127.0.0.1:{port}"
    print(f"  服务已就绪，浏览器即将打开：{url}")
    proc, name = _open_browser(url)
    if proc is None:
        if os.environ.get("QIXI_NO_BROWSER"):
            print("  服务在跑，进入等待；Ctrl+C 结束。")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return 0
        _pause("  已用默认浏览器打开。关闭浏览器后按回车停止服务…")
        return 0
    print(f"  已用 {name} 打开。关闭应用窗口即停止服务。")
    proc.wait()
    print("  应用窗口已关闭，服务停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
