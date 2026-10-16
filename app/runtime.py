"""运行时路径解析：源码运行 / PyInstaller 打包版两套环境统一入口。

- RESOURCE_DIR：只读资源（web/、app/data/、app/audio/）——打包后指向解包目录
- USER_DIR：可写数据（config.json、日志、导出）——打包后放 %LOCALAPPDATA%\\QixiGuide
- APP_DIR：程序所在目录（源码版=仓库根；打包版=exe 所在文件夹）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    _meipass = getattr(sys, "_MEIPASS", None)
    # PyInstaller onedir/onefile 都会给 _MEIPASS；万一没有就退回程序目录
    RESOURCE_DIR = Path(_meipass).resolve() if _meipass else APP_DIR
    USER_DIR = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "QixiGuide"
    USER_DIR.mkdir(parents=True, exist_ok=True)
else:
    APP_DIR = Path(__file__).resolve().parents[1]
    RESOURCE_DIR = APP_DIR
    USER_DIR = APP_DIR


def resource_path(rel: str | Path) -> Path:
    """取只读资源路径：resource_path("web") / resource_path("app/data/poi.json")。"""
    rel = Path(rel)
    if rel.is_absolute():
        return rel
    p = RESOURCE_DIR / rel
    if p.exists():
        return p
    # 兼容打包时目录摆放不同（app 整个打进去）
    alt = APP_DIR / rel
    return alt if alt.exists() else p


def user_path(rel: str | Path) -> Path:
    """取可写数据路径：user_path("config.json")。"""
    rel = Path(rel)
    p = USER_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def describe() -> dict:
    return {
        "frozen": IS_FROZEN,
        "app_dir": str(APP_DIR),
        "resource_dir": str(RESOURCE_DIR),
        "user_dir": str(USER_DIR),
    }
