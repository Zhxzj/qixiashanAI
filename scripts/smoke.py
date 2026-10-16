"""Required project smoke gate: behavior regressions, without real cloud credentials."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
def main():
    env=dict(os.environ)
    env["QIXI_USER_DIR"]=str(ROOT/".tmp"/("smoke-"+uuid.uuid4().hex))
    env["PYTHONIOENCODING"]="utf-8"
    return subprocess.run([sys.executable,"-B","-m","unittest","discover","-s","tests","-v"],cwd=ROOT,env=env).returncode
if __name__=="__main__":
    sys.exit(main())
