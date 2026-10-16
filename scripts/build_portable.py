"""一键构建"免安装版"：素材 → 便携 Python → 组装 → 打 zip。

用法：
    scripts\\build_portable.bat            （推荐）
    .venv\\Scripts\\python scripts\\build_portable.py
选项：
    --py-version 3.12     便携 Python 版本（默认与开发环境同版本）
    --skip-download       复用 .tmp\\portable 里已下载的压缩包（离线重打）
    --no-zip              只组装文件夹，不压缩

产物：dist\\枫客松-小栖-demo-free\\ 与同名 .zip
说明：不需要 PyInstaller；对方机器零依赖（自带解释器与依赖）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_portable import (  # noqa: E402  （复用下载/组装逻辑）
    LAUNCH_BAT,
    STAGE,
    copy_app,
    download_runtime,
    extract_runtime,
    install_deps,
    runtime_is_standard,
    write_launcher,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def run_step(title: str, args: list[str]) -> bool:
    log(title)
    r = subprocess.run([sys.executable, *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    if not ok:
        tail = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-6:]
        for line in tail:
            log("    " + line)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--py-version", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    if getattr(sys, "frozen", False):
        log("请在源码目录跑这个脚本（.venv\\Scripts\\python scripts\\build_portable.py）。")
        return 1

    t0 = time.time()
    log("=" * 52)
    log("  栖霞山小向导 · 免安装版构建")
    log("=" * 52)
    log("  (build_portable: assembling portable Python pack)")
    log("")
    log("[1/5] 准备素材（示例照片 / 播报语音）…")
    if not run_step("    · 示例照片", ["scripts/make_samples.py"]):
        log("    （示例照片跳过，不影响打包）")
    if not run_step("    · 播报语音", ["scripts/make_audio.py"]):
        log("    （语音跳过：页面会回退浏览器 TTS，建议联网后重跑一次）")

    log(f"[2/5] 准备便携 Python {args.py_version} …")
    archive = download_runtime(args.py_version, skip=args.skip_download)
    if archive is None:
        log("")
        log("[失败] 拿不到便携 Python 压缩包。备选办法（三选一）：")
        log("  A) 开代理/VPN 后重跑本脚本；")
        log(f"  B) 手动下载 python-build-standalone 的 cpython-{args.py_version}.*-x86_64-pc-windows-msvc-install_only.tar.gz")
        log(f"     放到 {ROOT / '.tmp' / 'portable'}（文件名无所谓），再跑：")
        log("     scripts\\build_portable.bat --skip-download")
        log("  C) 换用官方 embeddable python（体积更小，但需要手工配 site-packages），")
        log("     具体做法见 docs\\打包与分发调研.md")
        return 1
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    log("[3/5] 解包运行时并复制程序 …")
    py_dir = extract_runtime(archive, STAGE / "runtime")
    if not runtime_is_standard(py_dir / "python.exe"):
        log("[失败] 解出来的便携 Python 是 free-threaded（无 GIL）构建，和依赖轮子不兼容。")
        log("   处理：删掉 .tmp\\portable 里的压缩包，重跑本脚本（已修正为固定选标准构建）。")
        return 1
    copy_app(STAGE)

    log("[4/5] 安装依赖到 runtime\\packages …（约 1 分钟）")
    if not install_deps(py_dir / "python.exe", STAGE / "runtime" / "packages"):
        log("[失败] 依赖安装失败，多半是网络问题；确认能访问 pypi.org 后重试。")
        return 1

    log("[5/5] 写启动器与说明 …")
    write_launcher(STAGE)
    for doc in ("DEMO使用说明.md", "安装与卸载说明.md", "打包与分发调研.md"):
        src = ROOT / "docs" / doc
        if src.exists():
            shutil.copy2(src, STAGE / doc)

    zip_path = None
    if not args.no_zip:
        log("      压缩 zip …")
        zip_path = shutil.make_archive(str(STAGE), "zip", root_dir=str(STAGE.parent), base_dir=STAGE.name)

    size_mb = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file()) / 1048576
    log("")
    log(f"[完成] 成品文件夹：{STAGE}")
    if zip_path:
        log(f"[完成] 发放包（zip）：{zip_path}")
    log(f"   体积：文件夹 {size_mb:.0f}MB · 用时 {time.time() - t0:.0f} 秒")
    log("")
    log("自测（重要）：")
    log("   1) 进 dist\\枫客松-小栖-demo-free\\ 双击 启动.bat（或 start.bat），确认浏览器打开、对话能用；")
    log("   2) 有条件的话，拷到一台没装 Python 的电脑上再试一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
