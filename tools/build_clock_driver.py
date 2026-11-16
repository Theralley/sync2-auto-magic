"""Build the isolated clock diagnostic on ant-srv-001 into a fresh, bound bundle.

Upload this script and the five named source files to an exclusive server staging
directory, then use --sources STAGING --out NEW_DIRECTORY. This never packs or deploys.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

IMAGE = ("ghcr.io/enlyze/windows-ce-build-environment-arm"
         "@sha256:22ea23d697accaab2b98fb12d81ccc1faade90f9fe490f554ae7c5c194dfe27c")
SOURCES = ("s2amclkdrv.c", "s2amclkdrv.def", "s2amclockctl.c", "s2amclockjob.c", "clock_probe_protocol.h")
FLAGS = ("-O2", "-Wall", "-Wextra", "-Werror")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(sources: Path, out: Path):
    if socket.gethostname().split(".")[0] != "ant-srv-001" or sys.platform != "linux":
        raise RuntimeError("clock native builds run only on ant-srv-001")
    sources, out = sources.resolve(), out.resolve()
    out.mkdir(parents=False, exist_ok=False)
    for name in SOURCES:
        source = sources / name
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 1024 * 1024:
            raise ValueError(f"invalid source: {name}")
        shutil.copyfile(source, out / name)
    hashes = {name: sha(out / name) for name in SOURCES}
    receipt = {"state": "dispatched", "sources": hashes, "image": IMAGE, "flags": FLAGS}
    with (out / "dispatch.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    docker = ["docker", "run", "--rm", "--network", "none", "-u", f"{os.getuid()}:{os.getgid()}",
              "-v", f"{out}:/work", "-w", "/work", IMAGE]
    binaries = {}
    try:
        with (out / "build.log").open("xb") as log:
            commands = [
                ("s2amclkdrv.dll", ["-shared", "s2amclkdrv.c", "s2amclkdrv.def"]),
                ("s2amclockctl.exe", ["s2amclockctl.c"]),
                ("s2amclockjob.exe", ["s2amclockjob.c"]),
            ]
            for name, inputs in commands:
                if any(sha(out / source) != digest for source, digest in hashes.items()):
                    raise ValueError("source snapshot changed after dispatch")
                defines = []
                if name == "s2amclockctl.exe":
                    defines = [f'-DSCK_EXPECTED_DLL_SHA256="{binaries["s2amclkdrv.dll"]}"',
                               f'-DSCK_EXPECTED_DLL_SIZE={(out / "s2amclkdrv.dll").stat().st_size}']
                subprocess.run([*docker, "arm-mingw32ce-gcc", *FLAGS, *defines, "-o", name, *inputs],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run([*docker, "arm-mingw32ce-strip", name], stdout=log, stderr=subprocess.STDOUT, check=True)
                binaries[name] = sha(out / name)
        manifest = {"format": "s2am-clock-artifacts-v1", "sources": hashes, "binaries": binaries,
                    "image": IMAGE, "flags": FLAGS, "build_host": "ant-srv-001"}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        receipt["state"] = "complete"
    except Exception as error:
        receipt.update(state="failed", error=type(error).__name__)
        raise
    finally:
        (out / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"state": "complete", "binaries": binaries}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.sources, args.out)
