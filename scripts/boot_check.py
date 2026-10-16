"""Real HTTP boot check with owned socket, identity and meaningful exit status."""
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("QIXI_USER_DIR",str(ROOT/".tmp"/("boot-"+uuid.uuid4().hex)))
import uvicorn
from app.main import app,INSTANCE_ID
def main():
    sock=socket.socket();sock.bind(("127.0.0.1",int(os.environ.get("QIXI_TEST_PORT","0"))));sock.listen(128)
    base=f"http://127.0.0.1:{sock.getsockname()[1]}"
    server=uvicorn.Server(uvicorn.Config(app,log_level="warning"))
    result=[]
    def probe():
        deadline=time.monotonic()+15
        while not server.started and time.monotonic()<deadline:
            time.sleep(.05)
        try:
            for path in ("/api/health","/","/js/app.js","/js/session.js","/poster.html","/poster/poster-app.js","/poster/skill/renderer/render.js","/vendor/html-to-image.js","/poster/skill/motifs/maple_leaf_line.svg"):
                ok=False
                try:
                    with urllib.request.urlopen(base+path,timeout=3) as response:
                        data=response.read();ok=response.status==200 and len(data)>80
                        if path=="/api/health":
                            body=json.loads(data);ok=body.get("app_id")=="qixi-guide" and body.get("instance_id")==INSTANCE_ID
                except Exception:
                    pass
                result.append(ok)
                print(f"[{'PASS' if ok else 'FAIL'}] {path}",flush=True)
        finally:
            server.should_exit=True
    worker=threading.Thread(target=probe,daemon=True);worker.start()
    try:
        server.run(sockets=[sock])
        worker.join(timeout=5)
    finally:
        sock.close()
    return 0 if len(result)==9 and all(result) else 1
if __name__=="__main__":
    sys.exit(main())
