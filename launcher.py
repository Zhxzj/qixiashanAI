"""Owned local host. Browser child lifetime never controls the server."""
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from app.runtime import APP_ID,API_VERSION,BUILD_ID,user_path,resource_path,describe

PORT_CANDIDATES=(8017,8018,8019,8020,8021,8022)
def _healthy(port,timeout=1.0,instance_id=None,build_id=BUILD_ID):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=timeout) as response:
            data=json.load(response)
        return data.get("ok") is True and data.get("app_id")==APP_ID and data.get("api_version")==API_VERSION and data.get("build_id")==build_id and (instance_id is None or data.get("instance_id")==instance_id)
    except Exception:
        return False

def _open_browser(url):
    if os.environ.get("QIXI_NO_BROWSER"):
        return
    for pf,rel in (("ProgramFiles(x86)","Microsoft/Edge/Application/msedge.exe"),("ProgramFiles","Microsoft/Edge/Application/msedge.exe"),("ProgramFiles","Google/Chrome/Application/chrome.exe")):
        exe=Path(os.environ.get(pf,"C:/Program Files"))/rel
        if exe.exists():
            subprocess.Popen([str(exe),f"--app={url}"])
            return
    os.startfile(url)

def _ready_signal():
    name=os.environ.get("QIXI_READY_EVENT")
    if name and os.name=="nt":
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL("kernel32",use_last_error=True)
        api.OpenEventW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
        api.OpenEventW.restype=wintypes.HANDLE
        api.SetEvent.argtypes=[wintypes.HANDLE]
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenEventW(2,False,name)
        if handle:
            api.SetEvent(handle)
            api.CloseHandle(handle)

def _init_streams():
    if sys.stdout is None or sys.stderr is None:
        path=user_path("logs/launcher.log")
        if path.exists() and path.stat().st_size>2_000_000:
            path.replace(path.with_suffix(".previous.log"))
        stream=path.open("a",encoding="utf-8",buffering=1)
        sys.stdout=sys.stdout or stream
        sys.stderr=sys.stderr or stream

def run_app():
    if "--check" in sys.argv:
        import app.main
        checks=[resource_path(n).exists() for n in ("web/index.html","web/poster.html","app/data/poi.json","app/data/routes.json")]
        return 0 if all(checks) else 1
    import msvcrt
    lock=user_path("instance/host.lock").open("a+b")
    lock.seek(0)
    if os.fstat(lock.fileno()).st_size==0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        lock.close()
        for _ in range(80):
            try:
                instance=json.loads(user_path("instance/current.json").read_text(encoding="utf-8"))
                if _healthy(instance["port"],instance_id=instance["instance_id"],build_id=instance["build_id"]):
                    if instance["build_id"]!=BUILD_ID:
                        raise RuntimeError("旧版本仍在运行，请先在应用内退出，再打开新版本。")
                    _open_browser(f"http://127.0.0.1:{instance['port']}")
                    _ready_signal()
                    return 0
            except (OSError,ValueError,KeyError):
                pass
            time.sleep(.15)
        raise RuntimeError("已有实例正在启动，请稍后重试。")
    descriptor=user_path("instance/current.json")
    instance_id=secrets.token_hex(16)
    token=secrets.token_urlsafe(32)
    os.environ["QIXI_INSTANCE_ID"]=instance_id
    os.environ["QIXI_CONTROL_TOKEN"]=token
    sock=None
    try:
        preferred=int(os.environ.get("QIXI_TEST_PORT") or os.environ.get("QIXI_PORT") or 8017)
        for port in dict.fromkeys((preferred,*PORT_CANDIDATES,0)):
            sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1",port))
                sock.listen(128)
                break
            except OSError:
                sock.close()
        port=sock.getsockname()[1]
        import uvicorn
        from app.main import app
        server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,log_level="warning",timeout_graceful_shutdown=5))
        app.state.server=server
        instance={"app_id":APP_ID,"api_version":API_VERSION,"build_id":BUILD_ID,"instance_id":instance_id,"port":port,"pid":os.getpid(),"created_ts":time.time(),"executable":sys.executable,"token":token}
        temp=descriptor.with_suffix(".tmp")
        temp.write_text(json.dumps(instance),encoding="utf-8")
        os.replace(temp,descriptor)
        def on_ready():
            for _ in range(200):
                if server.should_exit:
                    return
                if _healthy(port,instance_id=instance_id):
                    try:
                        _open_browser(f"http://127.0.0.1:{port}")
                    except OSError:
                        print("浏览器未能打开，请手工打开：",f"http://127.0.0.1:{port}",flush=True)
                    _ready_signal()
                    return
                time.sleep(.1)
            server.should_exit=True
        threading.Thread(target=on_ready,daemon=True).start()
        server.run(sockets=[sock])
        return 0 if server.started else 1
    finally:
        if sock:
            sock.close()
        try:
            if descriptor.exists() and json.loads(descriptor.read_text())["instance_id"]==instance_id:
                descriptor.unlink()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            lock.close()

def main():
    _init_streams()
    try:
        return run_app()
    except Exception as e:
        import traceback
        traceback.print_exc()
        if not os.environ.get("QIXI_NO_BROWSER") and "--check" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(e)+"\n诊断日志："+str(user_path("logs/launcher.log")),"栖霞山小向导 · 启动失败",0x10)
        return 1
if __name__=="__main__":
    sys.exit(main())
