"""源码版一键启动：找 Python → 建 venv → 装依赖 → 起服务 → 开浏览器。

start.bat / start_dev.bat 都调用它（bat 保持纯 ASCII，中文提示由本脚本输出）。
所有步骤写入日志文件（启动失败时把日志发来即可定位）。

用法：
    python scripts\\sync_bootstrap.py            # 安装 + 启动（双击 start.bat 走这里）
    python scripts\\sync_bootstrap.py --server   # 只前台起服务（start_dev.bat 用）
    python scripts\\sync_bootstrap.py --install  # 只装环境
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # 保证能 import app.*（不依赖 PYTHONPATH）


def _heal_venv_path() -> None:
    """给 venv 写一个 .pth，把仓库根目录永久加进 sys.path。

    Python 运行时只会把脚本所在目录加进 sys.path（`scripts/`），不会加仓库根；
    这个 .pth 让"从任何目录运行任何脚本"都能 import app.*，并可在文件夹搬家后自动修复。
    """
    site = ROOT / ".venv" / "Lib" / "site-packages"
    if not site.is_dir():
        return
    pth = site / "_qixi_root.pth"
    try:
        want = str(ROOT) + "\n"
        if not pth.exists() or pth.read_text(encoding="utf-8", errors="ignore").strip() != str(ROOT):
            pth.write_text(want, encoding="utf-8")
    except Exception:
        pass


_heal_venv_path()
MIN_PY = (3, 14)
PORT_CANDIDATES = (8017, 8018, 8019, 8020, 8021, 8022)
PIP_MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.org/simple",
]


def log_path() -> Path:
    """日志落点：优先程序目录，不可写时用 %LOCALAPPDATA%\\QixiGuide\\logs。"""
    for base in (ROOT, Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "QixiGuide" / "logs"):
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return base / "startup.log"
        except Exception:
            continue
    return Path.home() / "qixi-startup.log"


class Log:
    def __init__(self) -> None:
        self.path = log_path()
        try:
            self.path.write_text(
                f"=== qixi 启动日志 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n", encoding="utf-8"
            )
        except Exception:
            pass

    def __call__(self, msg: str) -> None:
        print(msg, flush=True)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass


say = Log()


def pause(msg: str = "  按回车继续…") -> None:
    """没有交互终端时（被管道/服务方式调用）静默跳过，绝不抛异常。"""
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        print("", flush=True)


def _venv_python_path() -> Path:
    return ROOT / ".venv" / "Scripts" / "python.exe"


def _run_ok(cmd: list[str], timeout: int = 25) -> bool:
    """跑一条命令，rc==0 视为成功；任何异常都当失败（绝不向上抛）。"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,cwd=ROOT)
        return r.returncode == 0
    except Exception:
        return False


def _py_version_of(exe: str) -> str:
    try:
        r = subprocess.run(
            [exe, "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
        )
        return (r.stdout or "").strip() or "?"
    except Exception:
        return "?"


def _deps_probe(venv_py: str) -> bool:
    """核心依赖能不能 import（离线兜底与跳过联网检查都靠它）。"""
    code="import importlib.metadata as m; from pathlib import Path; import fastapi,uvicorn,httpx,PIL; rows=[r.split()[0].split('==') for r in Path('requirements.lock').read_text().splitlines() if '==' in r]; assert all(m.version(n)==v for n,v in rows)"
    return _run_ok([venv_py,"-c",code])


def _stamp_path() -> Path:
    return ROOT / ".venv" / ".qixi_deps.json"


def _req_sha() -> str:
    try:
        return hashlib.sha256((ROOT / "requirements.txt").read_bytes()+(ROOT / "requirements.lock").read_bytes()).hexdigest()[:16]
    except Exception:
        return "no-req"


def _stamp_match() -> bool:
    try:
        have = json.loads(_stamp_path().read_text(encoding="utf-8"))
        return have.get("req") == _req_sha()
    except Exception:
        return False


def _stamp_write(venv_py: str) -> None:
    try:
        _stamp_path().write_text(
            json.dumps({"req": _req_sha(), "py": _py_version_of(venv_py)}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _maybe_reexec(venv_py: str) -> int | None:
    """当前解释器不是 venv 里的 Python 时，切换过去重跑本脚本。

    首次安装（别人电脑、没有 .venv）时，start.bat 会用“系统 Python”跑本脚本；
    如果不切换，后面 `from app.main import run_server` 会去系统环境找依赖 → 直接崩。
    返回 None 表示无需切换（或切换失败，按当前环境继续）；否则返回子进程退出码。
    """
    try:
        cur = os.path.normcase(str(Path(sys.executable).resolve()))
        want = os.path.normcase(str(Path(venv_py).resolve()))
        if cur == want:
            return None
    except Exception:
        return None
    say(f"  切换到专用环境重启：{venv_py}")
    try:
        return subprocess.call([venv_py, str(Path(__file__).resolve()), *sys.argv[1:]])
    except Exception as e:
        say(f"  切换失败（{type(e).__name__}），按当前环境继续。")
        return None


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _is_our_service(port: int, timeout: float = 1.5) -> bool:
    """只有 /api/health 返回 ok=true 才认为是我们自己的服务。"""
    import json

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            from app.runtime import APP_ID,API_VERSION,BUILD_ID
            return data.get("ok") is True and data.get("app_id")==APP_ID and data.get("api_version")==API_VERSION and data.get("build_id")==BUILD_ID and bool(data.get("instance_id"))
    except Exception:
        return False


def _find_python() -> str | None:
    """找 Python 3.14；返回调用参数。"""
    candidates: list[list[str]] = []
    p = shutil.which("python")
    if p and "WindowsApps" not in p:  # 跳过“微软应用商店”假 python（会弹商店）
        candidates.append([p])
    if shutil.which("py"):
        candidates.append([shutil.which("py"), "-3"])  # type: ignore[list-item]
    for common in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python",
        Path("C:/Python314"), Path("C:/Python313"), Path("C:/Python312"), Path("C:/Python311"),
    ):
        if common.is_dir():
            for exe in sorted(common.glob("Python*/python.exe"), reverse=True):
                candidates.append([str(exe)])
    for cmd in candidates:
        try:
            r = subprocess.run(
                cmd + ["-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
                capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                continue
            ver = tuple(int(x) for x in (r.stdout or "").strip().split(".")[:2])
            if ver == MIN_PY:
                say(f"  找到 Python {' '.join(cmd)} → {r.stdout.strip()}")
                return cmd  # type: ignore[return-value]
            say(f"  跳过过旧版本：{' '.join(cmd)} → {r.stdout.strip()}")
        except Exception as e:
            say(f"  检测 {' '.join(cmd)} 失败：{type(e).__name__}")
    return None


def ensure_env() -> str | None:
    """保证 .venv 与依赖就绪；返回 venv 里的 python.exe。"""
    venv_py_path = _venv_python_path()
    venv_py = str(venv_py_path)

    if venv_py_path.exists() and not _run_ok([venv_py, "-c", "import sys"]):
        # venv 坏了（文件夹搬过家 / 杀软清了一半）：改名让路，下面重建一个
        broken = ROOT / f".venv-broken-{time.strftime('%Y%m%d%H%M%S')}"
        say(f"[1/2] 旧环境损坏，改名让路：{broken.name}")
        try:
            venv_py_path.parent.parent.rename(broken)
        except Exception as e:
            say(f"  改名失败（{type(e).__name__}），继续尝试修复…")

    if venv_py_path.exists():
        say(f"[1/2] 运行环境已存在：{venv_py_path}")
    else:
        py = _find_python()
        if not py:
            say("[错误] 源码开发需要 Python 3.14 x64；普通收件人请使用便携 EXE。")
            say("  请到 https://www.python.org/downloads/ 安装，安装时勾选 “Add python.exe to PATH”。")
            say("  装好后重新双击 start.bat。")
            return None
        say("[1/2] 首次运行：创建运行环境（约 1 分钟）…")
        r = subprocess.run(py + ["-m", "venv", str(ROOT / ".venv")], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            say("[错误] 创建 venv 失败：")
            say("  " + ((r.stderr or r.stdout or "").strip()[-500:] or "(无输出)"))
            say("  常见原因：Python 没装全 / 公司电脑限制。可截图发我。")
            return None
        say(f"  环境创建完成：{venv_py_path}")

    if not _run_ok([venv_py,"-c","import sys,struct; assert sys.version_info[:2]==(3,14) and struct.calcsize('P')==8"]):
        say("[错误] 当前 .venv 与锁定依赖不匹配，需要 Python 3.14 x64。请使用便携 EXE，或另建符合版本的开发环境。")
        return None
    # 精确版本与哈希；离线只接受同一锁定版本。
    if _stamp_match() and _deps_probe(venv_py):
        say("[2/2] 依赖已就绪（本地校验通过，跳过联网检查）")
        return venv_py

    # 有的机器建 venv 时 ensurepip 失败，会留下“没有 pip 的环境”，这里先自修复
    if not _run_ok([venv_py, "-m", "pip", "--version"]):
        say("  环境里缺少 pip，尝试自动修复 …")
        _run_ok([venv_py, "-m", "ensurepip", "--upgrade"], timeout=180)
    if not _run_ok([venv_py, "-m", "pip", "--version"]):
        say("[错误] 运行环境缺失 pip 且无法自动修复（常见于 Python 安装不完整）。")
        say("  办法：跑 scripts\\fix_startup.bat 重建环境，或重装 Python（安装时勾选 Add to PATH）。")
        return None

    say("[2/2] 检查依赖（首次可能要下载，多个镜像自动重试）…")
    req = ROOT / "requirements.txt"
    for mirror in PIP_MIRRORS:
        cmd = [venv_py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
               "-r", str(req), "-i", mirror]
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            _stamp_write(venv_py)
            say(f"  依赖就绪（{mirror.split('/')[2]}）")
            return venv_py
        say(f"  镜像 {mirror.split('/')[2]} 失败：{((r.stderr or '').strip().splitlines() or [''])[-1][:120]}")

    if _deps_probe(venv_py):
        _stamp_write(venv_py)
        say("  网络镜像都不通，但依赖已经在本地 —— 离线模式继续启动")
        return venv_py
    say("[错误] 依赖安装失败：所有镜像都不通，且本地校验没通过。")
    say("  1) 检查网络/代理后重试；")
    say("  2) 或在能联网的机器上先跑一次，把整个文件夹（含 .venv）拷过来。")
    return None


def find_our_service() -> int | None:
    for p in PORT_CANDIDATES:
        if _is_our_service(p):
            return p
    return None


def open_browser(url: str) -> subprocess.Popen | None:
    """Edge/Chrome 的 --app 窗口；返回进程（浏览器关了就能停服务）。"""
    if os.environ.get("QIXI_NO_BROWSER"):
        say("  （QIXI_NO_BROWSER=1，跳过打开浏览器）")
        return None
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for exe in (
        Path(pf86) / "Microsoft/Edge/Application/msedge.exe",
        Path(pf) / "Microsoft/Edge/Application/msedge.exe",
        Path(pf) / "Google/Chrome/Application/chrome.exe",
        Path(pf86) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ):
        if exe.exists():
            say(f"  用 {exe.name} 打开应用窗口…")
            try:
                return subprocess.Popen([str(exe), f"--app={url}"])
            except Exception as e:
                say(f"  启动浏览器失败：{type(e).__name__}，改用默认浏览器")
    try:
        os.startfile(url)  # type: ignore[attr-defined]
        say("  已用默认浏览器打开（关网页不会自动停服务，用 stop.bat 停）")
    except Exception as e:
        say(f"  打不开浏览器：{type(e).__name__}。请手动访问：{url}")
    return None


def cmd_install_only() -> int:
    return 0 if ensure_env() else 1


def cmd_server() -> int:
    if not _venv_python_path().exists():
        say("[错误] 还没有 .venv，先跑一次 start.bat。")
        return 1
    rc = _maybe_reexec(str(_venv_python_path()))
    if rc is not None:
        return rc
    from app.main import run_server

    say("开发模式：前台运行，Ctrl+C 停止。地址 http://127.0.0.1:8017")
    run_server(8017)
    return 0


def cmd_run() -> int:
    venv_py=ensure_env()
    if not venv_py:
        return 1
    rc=_maybe_reexec(venv_py)
    if rc is not None:
        return rc
    from launcher import main as launch
    return launch()


def main() -> int:
    try:
        argv = sys.argv[1:]
        if "--server" in argv:
            return cmd_server()
        if "--install" in argv:
            return cmd_install_only()
        return cmd_run()
    except Exception:
        say("[异常] 启动过程出错：")
        say("  " + traceback.format_exc().replace("\n", "\n  "))
        pause("  按回车关闭窗口（把日志发我即可）…")
        return 2


if __name__ == "__main__":
    sys.exit(main())
