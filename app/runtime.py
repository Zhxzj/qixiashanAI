"""Read-only resources and per-user writable data, in source and portable Python."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parents[1]
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
USER_DIR = Path(os.environ.get("QIXI_USER_DIR") or str(Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "QixiGuide"))
APP_ID = "qixi-guide"
API_VERSION = 2
_manifest = RESOURCE_DIR / "manifest.json"
BUILD_ID = os.environ.get("QIXI_BUILD_ID") or (json.loads(_manifest.read_text(encoding="utf-8"))["build_id"] if _manifest.exists() else "source-v4-osm")
def resource_path(rel):
    return RESOURCE_DIR / rel
def user_path(rel):
    p = USER_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
def describe():
    return {"frozen": IS_FROZEN, "app_dir": str(APP_DIR), "resource_dir": str(RESOURCE_DIR), "user_dir": str(USER_DIR)}
