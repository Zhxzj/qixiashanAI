"""Graceful authenticated shutdown of the recorded instance; never kill by port/PID."""
import json
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.runtime import user_path
from launcher import _healthy
def main():
    path=user_path("instance/current.json")
    if not path.exists():
        print("没有记录到运行中的实例。")
        return 0
    instance=json.loads(path.read_text(encoding="utf-8"))
    if not _healthy(instance["port"],instance_id=instance["instance_id"],build_id=instance["build_id"]):
        print("实例身份无法确认；未停止任何进程。")
        return 1
    req=urllib.request.Request(f"http://127.0.0.1:{instance['port']}/api/app/control",data=json.dumps({"token":instance["token"],"action":"exit"}).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=5) as response:
        result=json.load(response)
    return 0 if result.get("stopping") else 1
if __name__=="__main__":
    sys.exit(main())
