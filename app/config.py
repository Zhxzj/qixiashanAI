"""Atomic config writes; never probe or write the resource directory."""
import json
import os
import tempfile
from app.runtime import USER_DIR
from app.services.page_credentials import request_key
CONFIG_PATH = USER_DIR / "config" / "config.json"
DEFAULTS = {"schema_version": 1, "deepseek_api_key": "", "model": "deepseek-flash", "port": 8017,
            "amap_js_key": "", "amap_security_code": "",
            "osm_tile_url":"https://tile.openstreetmap.org/{z}/{x}/{y}.png"}

class RuntimeConfig(dict):
    def __getitem__(self, key):
        current = request_key.get()
        return current if key == "deepseek_api_key" and current is not None else super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default
def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: data[k] for k in DEFAULTS if k in data})
        except (ValueError, OSError, TypeError):
            pass
    # Migrate a legacy saved key away; never restore it into runtime state.
    legacy_key = cfg.get("deepseek_api_key")
    cfg["deepseek_api_key"] = ""
    if legacy_key:
        save_config(cfg)
    return RuntimeConfig(cfg)
def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="config-", dir=CONFIG_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({k: "" if k == "deepseek_api_key" else cfg.get(k, v) for k, v in DEFAULTS.items()}, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
def config_location():
    return "用户配置：" + str(CONFIG_PATH)
