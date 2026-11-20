"""Build only S2AMLOAD on ant-srv-001, with frozen sources and durable receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from s2am import container, native

SOURCES=("s2amload.c","load_observer_protocol.h")
BINARY="S2AMLOAD.EXE"


def sha(p):
    if p.is_symlink() or not p.is_file() or p.stat().st_size>1024*1024:
        raise ValueError("invalid build input/artifact")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_json(path,data):
    with path.open("x") as f:
        json.dump(data,f,indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())


def build(sources,out):
    if sys.platform!="linux" or socket.gethostname().split(".")[0]!="ant-srv-001":
        raise RuntimeError("CE builds run only on ant-srv-001; no Mac fallback")
    sources,out=Path(sources).resolve(),Path(out).resolve()
    out.mkdir(mode=0o700,exist_ok=False)
    for name in SOURCES:
        sha(sources/name); shutil.copyfile(sources/name,out/name)
    hashes={name:sha(out/name) for name in SOURCES}
    identity={"build_host":"ant-srv-001","sources":hashes,"image":native.IMAGE,
              "flags":list(native.CFLAGS)}
    write_json(out/"dispatch.json",{"state":"dispatched",**identity})
    result={"state":"failed",**identity}
    def frozen():
        if any(sha(out/n)!=digest for n,digest in hashes.items()):
            raise ValueError("frozen build source changed")
    try:
        docker=container.docker()+["run","--rm","--platform","linux/amd64","--network","none",
            "--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit=64","--memory=512m",
            "-u",f"{os.getuid()}:{os.getgid()}","-e","HOME=/tmp","-v",f"{out}:/work",
            "-w","/work",native.IMAGE]
        with (out/"build.log").open("xb") as log:
            for command in (["arm-mingw32ce-gcc",*native.CFLAGS,"-o",BINARY,"s2amload.c"],
                            ["arm-mingw32ce-strip",BINARY]):
                frozen()
                subprocess.run([*docker,*command],env=container.docker_env(),stdout=log,
                               stderr=subprocess.STDOUT,check=True,timeout=120)
        frozen()
        body=(out/BINARY).read_bytes(); native.check(body,BINARY)
        binaries={BINARY:sha(out/BINARY)}
        if hashlib.sha256(body).hexdigest()!=binaries[BINARY]:
            raise ValueError("executable changed during validation")
        with (out/"disassembly.txt").open("xb") as disasm:
            subprocess.run([*docker,"arm-mingw32ce-objdump","-d",BINARY],
                           env=container.docker_env(),stdout=disasm,stderr=subprocess.PIPE,
                           check=True,timeout=120)
        frozen()
        if sha(out/BINARY)!=binaries[BINARY]:
            raise ValueError("executable changed before publication")
        result={"state":"complete",**identity,"binaries":binaries,
                "sizes":{BINARY:len(body)}}
        write_json(out/"manifest.json",{"format":"s2am-load-artifacts-v1",**result})
    except Exception as error:
        result["error"]=type(error).__name__
        raise
    finally:
        write_json(out/"result.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sources",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(build(a.sources,a.out)))
