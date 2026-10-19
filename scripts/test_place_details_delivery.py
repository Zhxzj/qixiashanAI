"""Run the map browser contracts against the actual EXE, with isolated user data."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import uuid
from selftest_portable import wait_instance, shutdown

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--exe",type=Path,default=ROOT/"dist/栖霞山小向导.exe")
    exe=ap.parse_args().exe
    reports=Path(os.environ.get("QIXI_MAP_REPORTS",str(ROOT/"dist/details-reports")))
    reports.mkdir(parents=True,exist_ok=True)
    user=ROOT/".tmp"/("地图成品 测试-"+uuid.uuid4().hex)
    user.mkdir(parents=True)
    env=dict(os.environ)
    env.update(QIXI_USER_DIR=str(user),QIXI_NO_BROWSER="1",QIXI_TEST_PORT="0")
    node=shutil.which("node")
    if not node: raise RuntimeError("浏览器测试机需要Node.js")
    process=subprocess.Popen([str(exe)],env=env,stdin=subprocess.DEVNULL)
    instance=None
    try:
        instance,health=wait_instance(user/"instance/current.json",process)
        base=f"http://127.0.0.1:{instance['port']}"
        for name in ("js/map-osm.js","js/app.js","css/map.css","vendor/leaflet/leaflet.js","vendor/leaflet/leaflet.css","assets/places/qixiasi-gate.jpg","assets/places/qianfoyan-statue.jpg"):
            with urllib.request.urlopen(base+"/"+name,timeout=15) as response:
                if response.read()!=(ROOT/"web"/name).read_bytes(): raise AssertionError("成品资源与源码不一致："+name)
        env.update(QIXI_TEST_BASE=base,QIXI_MAP_REPORTS=str(reports))
        result=subprocess.run([node,"tools/test_osm_browser.cjs"],cwd=ROOT,env=env,timeout=180)
        if result.returncode: return result.returncode
        detail_result=subprocess.run([node,"tools/test_place_details_browser.cjs"],cwd=ROOT,env=env,timeout=180)
        if detail_result.returncode: return detail_result.returncode
        annotations_result=subprocess.run([node,"tools/test_annotations_browser.cjs"],cwd=ROOT,env=env,timeout=180)
        if annotations_result.returncode: return annotations_result.returncode
        visibility_result=subprocess.run([node,"tools/test_facility_visibility.cjs"],cwd=ROOT,env=env,timeout=180)
        if visibility_result.returncode:return visibility_result.returncode
        def request_json(path, body=None):
            payload=None if body is None else json.dumps(body).encode()
            request=urllib.request.Request(base+path,data=payload,headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)
        # Explicitly verify persistence through a real EXE stop/start, not only reload.
        snapshot=request_json('/api/map/annotations')
        fixture=snapshot['items'][0]['coord']
        preview=request_json('/api/map/annotations/preview',{'id':'gate_marked_west','coord':fixture,'revision':snapshot['revision']})
        request_json('/api/map/annotations/save',preview)
        shutdown(instance);process.wait(timeout=15);instance=None
        process=subprocess.Popen([str(exe)],env=env,stdin=subprocess.DEVNULL)
        instance,health=wait_instance(user/'instance/current.json',process)
        base=f"http://127.0.0.1:{instance['port']}"
        restored=request_json('/api/map/annotations')
        if next(p for p in restored['items'] if p['id']=='gate_marked_west')['coord']!=fixture:
            raise AssertionError('实际EXE重启未保留设施位置')
        request_json('/api/map/annotations/reset',{'id':'gate_marked_west','revision':restored['revision']})
        report={"exe_sha256":hashlib.sha256(exe.read_bytes()).hexdigest(),"build_id":health["build_id"],
                "resource_equality":True,"browser_reports":["browser-osm-results.json","browser-details-results.json","browser-annotations-results.json","browser-visibility-results.json"],"real_leaflet":True,"real_local_graph":True,"mock_raster_tiles":True,"mock_location":True,
                "real_amap_requests":0,"user_cache":str(user),"annotation_exe_restart_persistence":True,"passed":True}
        (reports/"packaged-details-verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print("实际EXE地图资源一致，浏览器地图合约通过；真实Leaflet与本地OSM图通过，定位与底图瓦片使用测试替身。")
        return 0
    finally:
        if instance and process.poll() is None:
            try: shutdown(instance);process.wait(timeout=15)
            except Exception:
                process.terminate();process.wait(timeout=5)


if __name__=="__main__": raise SystemExit(main())
