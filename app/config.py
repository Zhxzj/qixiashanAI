"""配置读写：config.json（DeepSeek API Key、模型、端口）。"""

from __future__ import annotations

import json

import app.runtime as rt
from app.runtime import USER_DIR, user_path


def _pick_config_path():
    """优先把配置放在程序目录（绿色包可随身带走）；目录不可写时退回用户目录。

    - 开发环境：仓库根目录；
    - 免安装包：包内目录（可写时）；
    - 装在只读位置（如 Program Files）：%LOCALAPPDATA%\\QixiGuide。
    """
    preferred = USER_DIR / "config.json"
    if rt.IS_FROZEN:
        return user_path("config.json")
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        probe = preferred.parent / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return preferred
    except Exception:
        return user_path("config.json")


CONFIG_PATH = _pick_config_path()

DEFAULTS: dict = {
    "deepseek_api_key": "",
    "model": "deepseek-flash",
    "port": 8017,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def config_location() -> str:
    return ("用户目录（打包版）：" if rt.IS_FROZEN else "程序目录：") + str(CONFIG_PATH)

