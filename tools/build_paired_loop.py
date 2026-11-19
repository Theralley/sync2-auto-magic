"""Build just the manual observation app, with an offline compiler; no USB access."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from s2am import container, native


def build(out: Path, *, ram_buffered=False):
    out.mkdir(exist_ok=False)
    src = native.SOURCES / "s2ampair.c"
    snapshot = out / src.name
    shutil.copyfile(src, snapshot)
    exe = "S2AMRAM.EXE" if ram_buffered else "S2AMPAIR.EXE"
    flags = [*native.CFLAGS, *(["-DS2AM_PAIR_V2"] if ram_buffered else [])]
    container.run(out, "sh", "-ec", """
exe=$1; shift
arm-mingw32ce-gcc "$@" -o "$exe" s2ampair.c
arm-mingw32ce-objdump -d "$exe" > disasm
arm-mingw32ce-strip "$exe"
arm-mingw32ce-objdump -p "$exe" > imports
""", "sh", exe, *flags, image=native.IMAGE)
    binary = (out / exe).read_bytes()
    native.check(binary, exe)
    if src.read_bytes() != snapshot.read_bytes():
        raise ValueError("source changed while building")
    receipt = {"image": native.IMAGE, "flags": flags, "exe": exe,
               "sha256": hashlib.sha256(binary).hexdigest(), "bytes": len(binary),
               "source_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("new_output_directory", type=Path)
    p.add_argument("--ram-buffered", action="store_true", help="build the separate v2 app")
    args = p.parse_args()
    print(json.dumps(build(args.new_output_directory, ram_buffered=args.ram_buffered)))
