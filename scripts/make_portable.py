"""打包"免安装版"：把 Python 运行时 + 本程序 + 依赖装进一个文件夹，对方零依赖双击即用。

产物：dist\\枫客松-小栖-demo-free\\（≤200MB，zip 后更小）
结构：启动.bat（同 start.bat）/ app\\（我们的代码）/ runtime\\python\\（便携 Python）/ runtime\\packages\\（依赖）

用法：
    .venv\\Scripts\\python scripts\\make_portable.py
选项：
    --py-version 3.12       便携 Python 版本（默认与开发环境同版本）
    --skip-download         复用上次下载的 runtime 压缩包（离线重打）

说明：不依赖 PyInstaller（Python 3.14 上还没轮子），也不需要对方装 Python。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
STAGE = DIST / "枫客松-小栖-demo-free"
DL = ROOT / ".tmp" / "portable"

# GitHub 直连 + 常用代理镜像（直连不通时自动换）
PROXIES = ["", "https://ghproxy.net/", "https://gh-proxy.com/", "https://ghfast.top/"]
PBS_REPO = "astral-sh/python-build-standalone"
PBS_API = f"https://api.github.com/repos/{PBS_REPO}/releases/tags/{{tag}}"
PBS_LATEST = f"https://api.github.com/repos/{PBS_REPO}/releases/latest"
PBS_RELEASES_PAGE = f"https://github.com/{PBS_REPO}/releases"


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str, dest: Path, timeout: int = 120) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "qixi-pack/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return True
    except Exception as e:
        log(f"   下载失败（{type(e).__name__}）：{url[:90]}")
        return False


def latest_pbs_tag() -> str | None:
    """取 python-build-standalone 的 latest release tag（形如 2026xxxx）。"""
    for prefix in PROXIES:
        url = (prefix + PBS_LATEST) if prefix else PBS_LATEST
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "qixi-pack/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("tag_name")
        except Exception as e:
            log(f"   取 latest release 失败（{prefix or '直连'}）：{type(e).__name__}")
    return None


def download_runtime(py_version: str, skip: bool = False) -> Path | None:
    DL.mkdir(parents=True, exist_ok=True)
    out = DL / f"python-{py_version}-win64.tar.gz"
    if out.exists() and out.stat().st_size > 10_000_000:
        log(f"   复用已下载：{out.name}（{out.stat().st_size // 1048576}MB）")
        return out
    if skip:
        log(f"   --skip-download：预期 {out} 不存在，无法离线打包。")
        return None
    # 兼容用户手动下载后改名的文件
    for cand in DL.glob("*.tar.gz"):
        if cand.stat().st_size > 10_000_000:
            shutil.copy2(cand, out)
            log(f"   复用手动下载件：{cand.name}")
            return out
    # 用户下载目录里的备份（下载器默认落点）
    user_dl = Path.home() / "Downloads"
    if user_dl.exists():
        for cand in list(user_dl.glob(f"cpython-{py_version}*install_only.tar.gz")) + list(user_dl.glob(f"python-{py_version}*win64.tar.gz")):
            if cand.stat().st_size > 10_000_000:
                shutil.copy2(cand, out)
                log(f"   复用下载目录里的压缩包：{cand.name}")
                return out

    # 取 release 信息（直连 + 镜像）
    tag = None
    asset = None
    assets: list[str] = []
    for prefix in PROXIES:
        try:
            req = urllib.request.Request(
                (prefix + PBS_LATEST) if prefix else PBS_LATEST,
                headers={"User-Agent": "qixi-pack/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            tag = data.get("tag_name")
            assets = [a.get("name", "") for a in data.get("assets", [])]
            log(f"   取到 release：{tag}（{prefix or '直连'}）")
            break
        except Exception as e:
            log(f"   取 release 失败（{prefix or '直连'}）：{type(e).__name__}")
    if not tag:
        return None
    for n in assets:
        low = n.lower()
        if not n.startswith(f"cpython-{py_version}"):
            continue
        if "x86_64-pc-windows-msvc" not in n or not n.endswith("install_only.tar.gz"):
            continue
        # free-threaded（无 GIL）构建和普通依赖轮子不兼容，必须跳过；
        # 资产列表里它排在前缀更靠前的位置，不加这行会优先选中它。
        if "freethreaded" in low or "free-threaded" in low or "free_threaded" in low:
            continue
        asset = n
        break
    if not asset:
        log(f"   release {tag} 里没有 {py_version} 的 Windows x64 资产。")
        return None

    direct = f"https://github.com/{PBS_REPO}/releases/download/{tag}/{asset}"
    for prefix in PROXIES:
        target = (prefix + direct) if prefix else direct
        log(f"   下载（{prefix or '直连'}）：{asset[:64]}…")
        if fetch(target, out):
            log(f"   完成：{out.stat().st_size // 1048576}MB")
            return out
    log(f"   全部下载失败。可手动下载该资产并放到：{DL}")
    log(f"   发布页：{PBS_RELEASES_PAGE}")
    return None


def extract_runtime(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest)
    # pbs 结构：python/ 或 python-<version>/ …里面才是 python.exe
    for p in dest.rglob("python.exe"):
        return p.parent
    raise RuntimeError("解包里没找到 python.exe")


COPY_DIRS = [("app", "app"), ("web", "web")]
COPY_FILES = ["launcher.py", "requirements.txt"]


def copy_app(dest: Path) -> None:
    app_dir = dest / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    for src_rel, dst_rel in COPY_DIRS:
        src = ROOT / src_rel
        dst = dest / dst_rel
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in COPY_FILES:
        shutil.copy2(ROOT / f, dest / f)
    log(f"   已复制代码与素材：{dest}")


PIP_MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.org/simple",
]


def _runtime_probe(py_exe: Path, target: Path) -> bool:
    """用便携 Python + 目标依赖目录跑一次 import，验证依赖真的可用。"""
    env = {**os.environ, "PYTHONPATH": str(target)}
    try:
        r = subprocess.run(
            [str(py_exe), "-c", "import fastapi, uvicorn, httpx, PIL"],
            capture_output=True, env=env, timeout=60,
        )
        return r.returncode == 0
    except Exception:
        return False


def runtime_is_standard(py_exe: Path) -> bool:
    """检查便携 Python 是标准 GIL 构建（不是 free-threaded）。"""
    try:
        r = subprocess.run(
            [str(py_exe), "-c",
             "import sysconfig;print(1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0)"],
            capture_output=True, text=True, timeout=60,
        )
        return (r.stdout or "").strip() == "0"
    except Exception:
        return False


def install_deps_from_venv(py_exe: Path, target: Path) -> bool:
    """离线兜底：把开发环境 .venv 里已装好的依赖复制进 runtime\\packages。

    适合：构建机网络受限、pip 装不上，但开发 venv 是好的情况。
    跳过 pip/setuptools/wheel 这些构建工具和 __pycache__。
    """
    site = ROOT / ".venv" / "Lib" / "site-packages"
    if not site.is_dir():
        return False

    def ignore(_dir, names):
        out = []
        for n in names:
            low = n.lower()
            if n == "__pycache__" or n.endswith(".pyc") or n == "_qixi_root.pth":
                out.append(n)
            elif low.startswith(("pip", "setuptools", "wheel", "pkg_resources")):
                out.append(n)
        return out

    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(site, target, dirs_exist_ok=True, ignore=ignore)
    return _runtime_probe(py_exe, target)


def install_deps(py_exe: Path, target: Path) -> bool:
    """往 runtime\\packages 装依赖：多镜像自动重试，全失败才报错。"""
    build_tmp = ROOT / ".tmp" / "build-temp"
    build_tmp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(build_tmp), "TMP": str(build_tmp)}
    for mirror in PIP_MIRRORS:
        cmd = [
            str(py_exe), "-m", "pip", "install", "-q", "--disable-pip-version-check",
            "--no-warn-script-location", "--target", str(target),
            "-r", str(ROOT / "requirements.txt"), "-i", mirror,
        ]
        log(f"   装依赖 → {target}（{mirror.split('/')[2]}）")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if r.returncode == 0:
            if _runtime_probe(py_exe, target):
                return True
            log("   依赖装上了但 import 校验失败：便携解释器和依赖不兼容。")
            return False
        log("   失败：" + ((r.stderr or "").strip()[-400:] or "(无输出)"))
    log("   三个镜像都不通，改用离线兜底：复制开发环境 .venv 里已装好的依赖 …")
    if install_deps_from_venv(py_exe, target):
        log("   （离线兜底）依赖已就绪")
        return True
    log("   离线兜底也失败：检查网络/代理后再跑一次。")
    return False


LAUNCH_BAT = r"""@echo off
rem Portable pack launcher (ASCII only on purpose).
chcp 65001 >nul
title Qixi Guide
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0runtime\packages"
set "PYW=%~dp0runtime\python\pythonw.exe"
set "PY=%~dp0runtime\python\python.exe"

if not exist "%PY%" (
  echo [ERROR] runtime\python not found - please re-extract the whole folder.
  pause
  exit /b 1
)
if not exist "%~dp0runtime\packages" (
  echo [WARN] runtime\packages missing - dependencies may fail to load.
  pause
)

echo Starting Qixi Guide ... the browser will open automatically.
echo Closing the app window stops the service.
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0launcher.py"
) else (
  start "" "%PY%" "%~dp0launcher.py"
)
exit /b 0
"""


def write_launcher(dest: Path) -> None:
    data = LAUNCH_BAT.replace("\n", "\r\n").encode("ascii")
    (dest / "start.bat").write_bytes(data)
    (dest / "启动.bat").write_bytes(data)
    (dest / "启动说明-必读.txt").write_text(
        "双击 启动.bat（或 start.bat）启动。\r\n"
        "浏览器会自动打开；关掉应用窗口即停止服务。\r\n"
        "如果 Windows 提示“Windows 已保护你的电脑”，点“更多信息”→“仍要运行”即可。\r\n"
        "\r\n"
        "如果双击后没反应：请先手动解压到普通文件夹（不要在压缩包里直接双击），再试一次。\r\n"
        "\r\n"
        "卸载：\r\n"
        "1) 删除本文件夹即可（程序本体）；\r\n"
        "2) 用户数据在 %LOCALAPPDATA%\\QixiGuide，需要的话一并删除。\r\n"
        "3) 没有注册表项、没有系统服务、没有开机启动项。\r\n",
        encoding="utf-8-sig",
    )
    log("   start.bat / 启动.bat / 启动说明-必读.txt 已生成")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--py-version", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()

    log("=== 打包免安装版 ===")
    log(f"源目录：{ROOT}")
    log(f"目标：{STAGE}")
    t0 = time.time()

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    # 1) 运行时
    log(f"[1/4] 准备便携 Python {args.py_version} ...")
    archive = DL / f"python-{args.py_version}-win64.tar.gz"
    if args.skip_download and archive.exists():
        log("   跳过下载（--skip-download）")
    else:
        archive = download_runtime(args.py_version) or archive
    if not archive.exists():
        log("[失败] 拿不到便携 Python。手动办法：")
        log("   1) 在能访问 GitHub 的网络下载 python-build-standalone 的")
        log(f"      cpython-{args.py_version}.*x86_64-pc-windows-msvc-install_only.tar.gz")
        log(f"   2) 放到 {DL} 目录（文件名任意），再带 --skip-download 重跑")
        return 1
    py_dir = extract_runtime(archive, STAGE / "runtime" / "python")
    if not runtime_is_standard(py_dir / "python.exe"):
        log("[失败] 便携 Python 是 free-threaded 构建，和依赖不兼容；")
        log("   删掉 .tmp\\portable 里的压缩包后重跑（脚本会重新选标准构建）。")
        return 1
    log(f"   运行时就绪：{py_dir}")

    # 2) 代码与素材
    log("[2/4] 复制程序与素材 ...")
    copy_app(STAGE)

    # 3) 依赖
    log("[3/4] 安装依赖到 runtime\\packages ...")
    if not install_deps(py_dir / "python.exe", STAGE / "runtime" / "packages"):
        return 1

    # 4) 启动器与说明
    log("[4/4] 写启动器 ...")
    write_launcher(STAGE)
    for doc in ("DEMO使用说明.md", "安装与卸载说明.md"):
        src = ROOT / "docs" / doc
        if src.exists():
            shutil.copy2(src, STAGE / doc)

    size_mb = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file()) / 1048576
    log("")
    log(f"完成：{STAGE}")
    log(f"体积：{size_mb:.0f}MB · 用时 {time.time() - t0:.0f} 秒")
    log("自测：进入该文件夹双击 启动.bat（不依赖系统的 Python）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
