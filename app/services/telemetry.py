"""Bounded redacted latency traces; no prompts, Keys or image payloads."""
import json
import time
from app.runtime import user_path
def record(request_id, kind, status, metrics):
    path = user_path("logs/requests.jsonl")
    if path.exists() and path.stat().st_size > 2_000_000:
        path.replace(path.with_suffix(".previous.jsonl"))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "request_id": request_id, "kind": kind, "status": status, "metrics": metrics}, ensure_ascii=False) + "\n")
