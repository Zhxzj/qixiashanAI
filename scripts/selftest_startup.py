"""Source launcher lifecycle test; stdin EOF must not end the owned host."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from selftest_portable import wait_instance,shutdown
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--port",type=int,default=8022);args=ap.parse_args()
    user=ROOT/".tmp"/("source-test-"+uuid.uuid4().hex)
    env={**os.environ,"QIXI_USER_DIR":str(user),"QIXI_TEST_PORT":str(args.port),"QIXI_NO_BROWSER":"1"}
    process=subprocess.Popen([sys.executable,"-B",str(ROOT/"launcher.py")],env=env,stdin=subprocess.DEVNULL)
    instance=None
    try:
        instance,health=wait_instance(user/"instance/current.json",process)
        time.sleep(.3)
        assert process.poll() is None,"stdin EOF 导致宿主退出"
        shutdown(instance)
        assert process.wait(timeout=12)==0,"宿主退出失败"
        print("[PASS] 源码宿主启动、EOF 保活、实例退出")
        return 0
    finally:
        if process.poll() is None:
            process.terminate();process.wait(timeout=5)
if __name__=="__main__":
    sys.exit(main())
