"""Build only S2AMLOAD on ant-srv-001 or an explicit own-branch Actions run."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from s2am import container, native

SOURCES=("s2amload.c","load_observer_protocol.h")
BINARY="S2AMLOAD.EXE"


def checked_read(path):
    flags=os.O_RDONLY|os.O_NONBLOCK|getattr(os,"O_NOFOLLOW",0)
    fd=os.open(path,flags)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>1024*1024:
            raise ValueError("invalid build input/artifact")
        with os.fdopen(fd,"rb",closefd=False) as stream:
            body=stream.read(1024*1024+1)
        after=os.fstat(fd)
        if (len(body)!=before.st_size or len(body)>1024*1024 or
                (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)):
            raise ValueError("build input/artifact changed during read")
        return body
    finally:
        os.close(fd)


def sha(p):
    return hashlib.sha256(checked_read(p)).hexdigest()


def write_json(path,data):
    with path.open("x") as f:
        json.dump(data,f,indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())


def build(sources,out,*,github_actions=False):
    if github_actions:
        env=os.environ
        if (sys.platform!="linux" or env.get("GITHUB_ACTIONS")!="true" or
                env.get("GITHUB_REPOSITORY")!="Theralley/sync2-auto-magic" or
                env.get("GITHUB_REF")!="refs/heads/build/raw-load-20261120" or
                env.get("GITHUB_EVENT_NAME") not in ("push","workflow_dispatch") or
                not re.fullmatch(r"[0-9a-f]{40}",env.get("GITHUB_SHA","")) or
                not re.fullmatch(r"[1-9][0-9]*",env.get("GITHUB_RUN_ID",""))):
            raise RuntimeError("Actions requires the explicit owned Linux build-branch context")
        location={"build_host":"github-actions","ci":{
            "repository":env["GITHUB_REPOSITORY"],"ref":env["GITHUB_REF"],
            "sha":env["GITHUB_SHA"],"run_id":env["GITHUB_RUN_ID"]}}
    else:
        if sys.platform!="linux" or socket.gethostname().split(".")[0]!="ant-srv-001":
            raise RuntimeError("CE builds require ant-srv-001 or explicit GitHub Actions; no Mac fallback")
        location={"build_host":"ant-srv-001"}
    sources,out=Path(sources).resolve(),Path(out).resolve()
    out.mkdir(mode=0o700,exist_ok=False)
    for name in SOURCES:
        sha(sources/name); shutil.copyfile(sources/name,out/name)
    hashes={name:sha(out/name) for name in SOURCES}
    identity={**location,"sources":hashes,"image":native.IMAGE,
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
        body=checked_read(out/BINARY); native.check(body,BINARY)
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
    p.add_argument("--github-actions",action="store_true",help="require exact owned Actions build-branch context")
    a=p.parse_args()
    print(json.dumps(build(a.sources,a.out,github_actions=a.github_actions)))
