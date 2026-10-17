"""Reproducible Windows x64 portable build: pinned inputs -> clean payload -> native EXE.

Requires build-machine Python 3.14 x64 and MinGW-w64 GCC on PATH.
Recipients need none of those. No source asset generation and no venv-copy fallback.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/"dist/QixiGuide-portable"
MAGIC=b"QIXIPK02"
def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()

def download(url,dest,digest,offline=False):
    if dest.exists() and sha(dest)==digest:
        return
    if offline:
        raise RuntimeError(f"离线输入缺失或摘要不符：{dest}")
    dest.parent.mkdir(parents=True,exist_ok=True)
    part=dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(url,timeout=120) as src, part.open("wb") as dst:
            shutil.copyfileobj(src,dst)
        if sha(part)!=digest:
            raise RuntimeError("下载摘要不符："+url)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)

def run(args,**kwargs):
    subprocess.run([str(a) for a in args],check=True,**kwargs)

def pack(stage,bootstrap,output,build_id):
    dll=ctypes.WinDLL("cabinet",use_last_error=True)
    handle=ctypes.c_void_p()
    dll.CreateCompressor.argtypes=[ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    dll.Compress.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
    dll.CloseCompressor.argtypes=[ctypes.c_void_p]
    if not dll.CreateCompressor(4,None,ctypes.byref(handle)):
        raise ctypes.WinError(ctypes.get_last_error())
    files=sorted(p for p in stage.rglob("*") if p.is_file())
    shutil.copyfile(bootstrap,output)
    payload_hash=hashlib.sha256()
    try:
        with output.open("ab") as out:
            offset=out.tell()
            for path in files:
                raw=path.read_bytes()
                name=path.relative_to(stage).as_posix().encode("utf-8")
                packed=b""
                if raw:
                    needed=ctypes.c_size_t()
                    dll.Compress(handle,raw,len(raw),None,0,ctypes.byref(needed))
                    buffer=ctypes.create_string_buffer(needed.value)
                    if not dll.Compress(handle,raw,len(raw),buffer,len(buffer),ctypes.byref(needed)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    packed=buffer.raw[:needed.value]
                header=struct.pack("<IQQ32s",len(name),len(raw),len(packed),hashlib.sha256(raw).digest())
                for chunk in (header,name,packed):
                    out.write(chunk)
                    payload_hash.update(chunk)
            out.write(struct.pack("<8sQI64s32s",MAGIC,offset,len(files),build_id.encode(),payload_hash.digest()))
    finally:
        dll.CloseCompressor(handle)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache",type=Path,default=ROOT/".tmp/portable-v2")
    ap.add_argument("--skip-download",action="store_true")
    ap.add_argument("--no-zip",action="store_true")
    ap.add_argument("--source-commit",default=None)
    args=ap.parse_args()
    if os.name!="nt" or sys.version_info[:2]!=(3,14) or struct.calcsize("P")!=8:
        raise RuntimeError("构建机需要 Windows + Python 3.14 x64")
    inputs=json.loads((ROOT/"build-inputs.lock.json").read_text(encoding="utf-8"))
    runtime=inputs["runtime"]
    archive=args.cache/runtime["filename"]
    download(runtime["url"],archive,runtime["sha256"],args.skip_download)
    wheel_dir=args.cache/"wheels"
    for wheel in inputs["wheels"]:
        download(wheel["url"],wheel_dir/wheel["filename"],wheel["sha256"],args.skip_download)
    # Only delete the fixed build directory after checking its fully resolved location.
    if STAGE.resolve().parent != (ROOT/"dist").resolve():
        raise RuntimeError("非法构建目标")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    py_dir=STAGE/"runtime/python"
    py_dir.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            target=(py_dir/member.filename).resolve()
            if not target.is_relative_to(py_dir.resolve()):
                raise RuntimeError("非法运行时路径")
        z.extractall(py_dir)
    (py_dir/"python314._pth").write_text("python314.zip\n.\n..\\packages\n..\\..\nimport site\n",encoding="ascii")
    for name in ("app","web"):
        shutil.copytree(ROOT/name,STAGE/name,ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
    for name in ("launcher.py","requirements.lock"):
        shutil.copy2(ROOT/name,STAGE/name)
    for name in ("stop_service.py",):
        (STAGE/"scripts").mkdir(exist_ok=True)
        shutil.copy2(ROOT/"scripts"/name,STAGE/"scripts"/name)
    packages=STAGE/"runtime/packages"
    packages.mkdir()
    # Locked wheels are ZIP containers. No pip bootstrap or build-host venv fallback.
    for wheel in inputs["wheels"]:
        with zipfile.ZipFile(wheel_dir/wheel["filename"]) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                destination=name
                if ".data/" in name:
                    prefix,tail=name.split(".data/",1)
                    area,relative=tail.split("/",1)
                    if area in ("purelib","platlib"):
                        destination=relative
                    else:
                        continue  # CLI entrypoints/headers are not used by the embedded host.
                target=(packages/destination).resolve()
                if not target.is_relative_to(packages.resolve()):
                    raise RuntimeError("非法依赖路径")
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(z.read(name))
    # Embedded Python reads only its explicit _pth. No dependence on build-machine PYTHONPATH.
    env={k:v for k,v in os.environ.items() if not k.startswith("PYTHON")}
    env["QIXI_USER_DIR"]=str(args.cache/"probe-user")
    env["QIXI_NO_BROWSER"]="1"
    run([py_dir/"python.exe","-B",STAGE/"launcher.py","--check"],env=env,cwd=STAGE)
    native=ROOT/"dist/bootstrap.exe"
    compiler=shutil.which("gcc")
    if not compiler:
        raise RuntimeError("构建机未找到 MinGW-w64 GCC")
    windres=shutil.which("windres")
    if not windres:
        raise RuntimeError("构建机未找到 MinGW-w64 windres")
    resource=ROOT/"dist/guide-resource.o"
    run([windres,"guide.rc","-O","coff","-o",resource],cwd=ROOT/"native")
    run([compiler,"-municode","-mwindows","-Os","-static","-Wall","-Wextra","-Werror","-Wl,--no-insert-timestamp",ROOT/"native/portable.c",resource,"-o",native,"-lbcrypt","-lcabinet","-lshell32"])
    (STAGE/"使用说明.txt").write_text("双击启动.bat；主交付请使用同目录外的栖霞山小向导.exe。\n首次启动自动准备用户缓存；无需管理员、Python或命令行。\n应用会保持运行，请点击页面右上角‘退出应用’；关闭浏览器不会停止服务。\n默认Leaflet＋OpenStreetMap地图无需地图Key；在线底图需要联网，本地道路、景点和步行规划不依赖付费接口。\n对话另需模型Key；模拟游览、照片手工选点和模板日记可不配置模型。\n电脑定位以精度和采样时间为准，不保证米级；手动起点不代表实际位置。厕所位置待用户提供。\nOSM道路和照片参考未完成现场通行核实；路线不保证实时开放。公开厕所候选默认隐藏，等待核实。\n诊断：页面右上角‘诊断’。配置、行程和日志在 %LOCALAPPDATA%/QixiGuide。\n照片不保存到该目录；开启云识别时压缩照片会发往 DeepSeek。\n新版本运行前请先退出旧版本。删除 EXE 不会清除用户数据。\n缓存管理：退出全部实例后运行 EXE --clean-cache，仅清理版本及未完成展开，保留 config/state/logs。\n旧讲解资料和演示路线为草稿，正式出行请核对园区信息。\n",encoding="utf-8-sig")
    bat='@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0runtime\\python\\pythonw.exe" -B "%~dp0launcher.py"\r\n'
    (STAGE/"start.bat").write_bytes(bat.encode("ascii"))
    (STAGE/"启动.bat").write_bytes(bat.encode("ascii"))
    commit=args.source_commit
    if not commit:
        proc=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True)
        commit=proc.stdout.strip() if proc.returncode==0 else "unversioned"
    files={p.relative_to(STAGE).as_posix():sha(p) for p in sorted(STAGE.rglob("*")) if p.is_file()}
    manifest={"schema_version":1,"source_commit":commit,"native_sources":{name:sha(ROOT/"native"/name) for name in ("portable.c","guide.rc","guide.ico")},"runtime":runtime,"dependency_lock_sha256":sha(ROOT/"requirements.lock"),"inputs_lock_sha256":sha(ROOT/"build-inputs.lock.json"),"compiler":subprocess.check_output([compiler,"--version"],text=True).splitlines()[0],"files":files}
    build_id=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    manifest["build_id"]=build_id
    (STAGE/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2),encoding="utf-8")
    exe=ROOT/"dist/栖霞山小向导.exe"
    pack(STAGE,native,exe,build_id)
    if not args.no_zip:
        shutil.make_archive(str(STAGE),"zip",root_dir=STAGE)
    artifacts=[exe]+([] if args.no_zip else [STAGE.with_suffix(".zip")])
    (ROOT/"dist/SHA256SUMS.txt").write_text("".join(sha(p)+"  "+p.name+"\n" for p in artifacts),encoding="utf-8")
    print(json.dumps({"exe":str(exe),"build_id":build_id,"bytes":exe.stat().st_size,"sha256":sha(exe)},ensure_ascii=False))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
