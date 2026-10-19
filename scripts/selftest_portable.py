"""Test the actual EXE in an isolated user cache; fail on skipped/unknown checks."""
import argparse
import hashlib
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def get_json(url):
    with urllib.request.urlopen(url,timeout=2) as response:
        return json.load(response)

def wait_instance(path,process,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise AssertionError(f"成品提前退出：{process.returncode}")
        try:
            instance=json.loads(path.read_text(encoding="utf-8"))
            health=get_json(f"http://127.0.0.1:{instance['port']}/api/health")
            if health.get("instance_id")==instance["instance_id"] and health.get("app_id")=="qixi-guide":
                return instance,health
        except (OSError,ValueError):
            pass
        time.sleep(.1)
    raise AssertionError("等待成品就绪超时")

def shutdown(instance):
    request=urllib.request.Request(f"http://127.0.0.1:{instance['port']}/api/app/control",data=json.dumps({"token":instance["token"],"action":"exit"}).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(request,timeout=3) as response:
        assert json.load(response)["stopping"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--exe",type=Path,default=ROOT/"dist/栖霞山小向导.exe")
    args=ap.parse_args()
    assert args.exe.is_file(),"成品不存在，不能跳过"
    user=ROOT/".tmp"/("成品验证 路径-"+uuid.uuid4().hex)
    user.mkdir(parents=True)
    env={k:v for k,v in os.environ.items() if not k.startswith("PYTHON")}
    env.update(QIXI_USER_DIR=str(user),QIXI_NO_BROWSER="1",PYTHONPATH="Z:/not-installed",PYTHONHOME="Z:/not-installed",PATH=os.environ.get("SystemRoot","C:/Windows")+"/System32")
    passed=[]
    def check(name,condition):
        assert condition,name
        passed.append(name)
        print("[PASS]",name,flush=True)
    run=lambda *flags:subprocess.run([str(args.exe.resolve()),*flags],env=env,timeout=60).returncode
    check("实际 EXE 在隔离 Python 环境中 --check",run("--check")==0)
    folders=list((user/"versions").iterdir())
    check("只创建一个完整版本",len(folders)==1)
    version=folders[0]
    marker=version/"web/index.html"
    original=marker.read_bytes()
    stamp=marker.stat().st_mtime_ns
    check("热启动检查通过",run("--check")==0)
    check("热启动复用文件，未重新展开",marker.stat().st_mtime_ns==stamp)
    # Occupy a requested port with an unrelated HTTP 200 service. It must survive.
    class Foreign(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
        def log_message(self,*args): pass
    foreign=http.server.ThreadingHTTPServer(("127.0.0.1",0),Foreign)
    threading.Thread(target=foreign.serve_forever,daemon=True).start()
    occupied=foreign.server_port
    env["QIXI_TEST_PORT"]=str(occupied)
    process=subprocess.Popen([str(args.exe.resolve())],env=env,stdin=subprocess.DEVNULL)
    instance=None
    try:
        started=time.monotonic()
        instance,health=wait_instance(user/"instance/current.json",process)
        startup_ms=round((time.monotonic()-started)*1000)
        check("端口占用时启动自己的实例",instance["port"]!=occupied)
        check("健康身份和构建一致",health["build_id"]==version.name)
        time.sleep(.4)
        check("无 stdin、无浏览器时宿主持久保活",process.poll() is None)
        check("二次双击返回已有实例",run()==0 and get_json(f"http://127.0.0.1:{instance['port']}/api/health")["instance_id"]==instance["instance_id"])
        check("活动实例阻止清理缓存",run("--clean-cache")!=0)
        check("不停止无关 HTTP 200 服务",get_json(f"http://127.0.0.1:{occupied}/api/health")["ok"] is True)
        with urllib.request.urlopen(f"http://127.0.0.1:{instance['port']}/poster.html") as page:
            check("实际成品提供海报工作台",b"poster-app.js" in page.read())
        for relative in ("js/map-osm.js","css/map.css","data/toilets-template.json","vendor/leaflet/leaflet.js","vendor/leaflet/leaflet.css","vendor/leaflet/LICENSE","assets/places/qixiasi-gate.jpg","assets/places/qianfoyan-statue.jpg"):
            with urllib.request.urlopen(f"http://127.0.0.1:{instance['port']}/"+relative) as response:
                check("成品包含当前地图资源 "+relative,response.read()==(ROOT/"web"/relative).read_bytes())
        map_config=get_json(f"http://127.0.0.1:{instance['port']}/api/map/config")
        check("成品无用户地图Key和安全密钥",map_config.get("configured") is False and not map_config.get("js_key") and "security_code" not in map_config)
        osm=get_json(f"http://127.0.0.1:{instance['port']}/api/map/osm/data")
        check("成品提供真实本地OSM道路",len(osm.get("roads",[]))>100)
        place=get_json(f"http://127.0.0.1:{instance['port']}/api/map/place?place_id=qxs-qixiasi")
        check("成品提供两层已核实景点介绍",place["status"]=="reviewed" and len(place["detail"])<=200)
        check("成品照片有作者及许可",place["photo"]["author"]=="Farm" and place["photo"]["license"]=="CC BY-SA 3.0")
        review=get_json(f"http://127.0.0.1:{instance['port']}/api/map/review")
        check("成品不将图片候选当新核准厕所",review["approved_new_toilets"]==0 and all(p["coord"] is None for p in review["toilets"]))
        shutdown(instance)
        check("实例凭证退出，EXE 返回零",process.wait(timeout=15)==0)
        check("退出移除本实例描述",not (user/"instance/current.json").exists())
        marker.write_bytes(b"corrupted-test")
        check("损坏缓存自动修复",run("--check")==0 and marker.read_bytes()==original)
        (user/"config").mkdir(exist_ok=True)
        keep=user/"config/keep.txt";keep.write_text("keep",encoding="ascii")
        check("清理无活动实例缓存",run("--clean-cache")==0)
        check("清理保留配置与行程",keep.exists() and (user/"state/sessions.sqlite3").exists() and not (user/"versions").exists())
        bad=user/"损坏包.exe"
        data=bytearray(args.exe.read_bytes());data[-1]^=1;bad.write_bytes(data)
        bad_proc=subprocess.run([str(bad)],env=env,timeout=20)
        check("损坏成品明确失败",bad_proc.returncode!=0)
    finally:
        if instance and process.poll() is None:
            try:
                shutdown(instance)
                process.wait(timeout=12)
            except Exception:
                # Only a process handle created by this test may be terminated.
                process.terminate()
                process.wait(timeout=5)
        foreign.shutdown();foreign.server_close()
    report={"passed":passed,"exe_sha256":hashlib.sha256(args.exe.read_bytes()).hexdigest(),"warm_host_startup_ms_one_sample":startup_ms,"user_cache":str(user),"limitations":["本机无头验证，不代替干净 Win10/Win11 与浏览器已有窗口实测","单次启动数据不是 P95"]}
    target=ROOT/"dist/portable-test-results.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"成品验证 {len(passed)}/{len(passed)}；单次热宿主启动 {startup_ms}ms")
    return 0
if __name__=="__main__":
    sys.exit(main())
