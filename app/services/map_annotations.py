"""Screenshot annotations and per-user position overrides; never edit the road graph."""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from app.services import map_navigation as nav
from app.services.location import dist_m


class AnnotationConflict(ValueError):
    pass


class AnnotationStore:
    def __init__(self, baseline, path, bounds):
        self.baseline = json.loads(Path(baseline).read_text(encoding="utf-8"))
        self.items = {p["id"]: p for p in self.baseline["items"]}
        if len(self.items) != len(self.baseline["items"]):
            raise ValueError("标注基线ID重复")
        self.path, self.bounds = Path(path), bounds
        self.lock = threading.RLock()
        self.secret = secrets.token_bytes(32)
        for p in self.items.values():
            if p["coord"] is not None:
                nav.coordinate(p["coord"], bounds)

    def _load(self):
        if not self.path.exists():
            return {"schema_version": 1, "revision": 0, "overrides": {}}, []
        raw = None
        try:
            raw = self.path.read_bytes()
            if len(raw) > 1_000_000:
                raise ValueError()
            data = json.loads(raw)
            if (data.get("schema_version") != 1 or type(data.get("revision")) is not int
                    or data["revision"] < 0 or not isinstance(data.get("overrides"), dict)):
                raise ValueError()
            return data, []
        except (ValueError, OSError, AttributeError):
            # Never silently replace an unreadable user file.
            if raw is not None and len(raw) <= 1_000_000:
                backup = self.path.with_name(self.path.name + ".invalid-" + hashlib.sha256(raw).hexdigest()[:12] + ".bak")
                try:
                    with backup.open("xb") as f:
                        f.write(raw)
                except OSError:
                    pass  # Original always stays intact, even when backup is unwritable.
            raise AnnotationConflict("本机标注文件损坏或无法读取，已保留原文件；请备份后检查，当前禁止保存")

    def _snapshot(self, data):
        items, warnings = [], []
        for key in data["overrides"]:
            if key not in self.items:
                warnings.append("未识别的设施记录已保留：" + str(key)[:96])
        for key, base in self.items.items():
            p = copy.deepcopy(base)
            override = data["overrides"].get(key)
            if override is not None:
                try:
                    coord = nav.coordinate(override["coord"], self.bounds)
                    if not isinstance(override["updated_at"], str):
                        raise ValueError()
                    p.update(coord=coord, position_status="user_confirmed", updated_at=override["updated_at"])
                except (ValueError, KeyError, TypeError):
                    warnings.append(key + "的本机位置无效，显示基线，原记录仍保留")
            p["coordinate_system"] = "WGS84"
            p["access_verified"] = False
            p["position_revision"] = hashlib.sha256(json.dumps(
                [self.baseline["baseline_version"], key, p["coord"], p["position_status"]],
                sort_keys=True).encode()).hexdigest()
            items.append(p)
        return {"schema_version": 1, "baseline_version": self.baseline["baseline_version"],
                "revision": data["revision"], "items": items, "warnings": warnings, "writable": True}

    def snapshot(self):
        with self.lock:
            try:
                data, _ = self._load()
                return self._snapshot(data)
            except AnnotationConflict as e:
                result = self._snapshot({"revision": 0, "overrides": {}})
                result.update(writable=False, warnings=[str(e)])
                return result

    def _validate(self, key, coord, revision):
        if key not in self.items:
            raise ValueError("未知设施ID")
        coord = nav.coordinate(coord, self.bounds)
        data, _ = self._load()
        if revision != data["revision"]:
            raise AnnotationConflict("位置已被其他窗口更新，请刷新后重新预览")
        return coord, data

    def _token(self, key, coord, revision, expires):
        payload = json.dumps([key, coord, revision, expires], separators=(",", ":")).encode()
        return hmac.new(self.secret, payload, "sha256").hexdigest()

    def preview(self, key, coord, revision):
        with self.lock:
            coord, _ = self._validate(key, coord, revision)
            expires = int(time.time()) + 300
            return {"id": key, "coord": coord, "revision": revision, "expires": expires,
                    "preview_token": self._token(key, coord, revision, expires)}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix="annotations-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def save(self, key, coord, revision, expires, token):
        with self.lock:
            coord, data = self._validate(key, coord, revision)
            if not int(time.time()) <= expires <= int(time.time()) + 301 or not hmac.compare_digest(
                    token, self._token(key, coord, revision, expires)):
                raise AnnotationConflict("预览已失效或内容已改变，请重新点选预览")
            current = next(p for p in self._snapshot(data)["items"] if p["id"] == key)
            if current["coord"] != coord or current["position_status"] != "user_confirmed":
                data["overrides"][key] = {"coord": coord, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                data["revision"] += 1
                self._write(data)
            return self._snapshot(data)

    def reset(self, key, revision):
        with self.lock:
            if key not in self.items:
                raise ValueError("未知设施ID")
            data, _ = self._load()
            if data["revision"] != revision:
                raise AnnotationConflict("位置已更新，请刷新后重试")
            if key in data["overrides"]:
                del data["overrides"][key]
                data["revision"] += 1
                self._write(data)
            return self._snapshot(data)

    def export(self):
        with self.lock:
            data, _ = self._load()
            return {"schema_version": 1, "baseline": self.baseline, "user_data": data,
                    "effective": self._snapshot(data)}

    def targets(self, entries, coords):
        snapshot = self.snapshot()
        if not snapshot["writable"] and entries:
            raise AnnotationConflict(snapshot["warnings"][0])
        by_id = {p["id"]: p for p in snapshot["items"]}
        result, roles = [], set()
        for entry in entries:
            role = entry["role"]
            p = by_id.get(entry["id"])
            if role in roles or role not in coords or not p or p["coord"] is None:
                raise ValueError("设施目标或角色无效")
            if p["position_revision"] != entry["position_revision"]:
                raise AnnotationConflict("设施位置已更新，请重新选择并规划")
            if dist_m(coords[role], p["coord"]) > .2:
                raise ValueError("设施目标坐标与记录不一致")
            roles.add(role)
            result.append({"role": role, "id": p["id"], "name": p["name"],
                           "position_revision": p["position_revision"], "coord": p["coord"], "access_verified": False})
        return result

    def ensure_route_version(self, state):
        route = state.get("route") or {}
        targets = route.get("annotation_targets") or []
        if route.get("status") != "ready" or not targets:
            return True
        snapshot = self.snapshot()
        by_id = {p["id"]: p for p in snapshot["items"]}
        if not snapshot["writable"] or any(by_id.get(p["id"], {}).get("position_revision") != p["position_revision"] for p in targets):
            nav.stop(state)
            route.update(status="no_path", error={"code": "stale_annotation", "message": "设施位置已更新或无法读取，请重新规划"})
            return False
        return True
