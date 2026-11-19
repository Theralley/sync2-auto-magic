"""Build just the manual observation app, with an offline compiler; no USB access."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from s2am import container, native


def build(out: Path):
    out.mkdir(exist_ok=False)
    src = native.SOURCES / "s2ampair.c"
    snapshot = out / src.name
    shutil.copyfile(src, snapshot)
    exe = "S2AMPAIR.EXE"
    container.run(out, "sh", "-ec", """
arm-mingw32ce-gcc "$@" -o S2AMPAIR.EXE s2ampair.c
arm-mingw32ce-objdump -d S2AMPAIR.EXE > disasm
arm-mingw32ce-strip S2AMPAIR.EXE
arm-mingw32ce-objdump -p S2AMPAIR.EXE > imports
""", "sh", *native.CFLAGS, image=native.IMAGE)
    binary = (out / exe).read_bytes()
    native.check(binary, exe)
    if src.read_bytes() != snapshot.read_bytes():
        raise ValueError("source changed while building")
    receipt = {"image": native.IMAGE, "flags": native.CFLAGS, "exe": exe,
               "sha256": hashlib.sha256(binary).hexdigest(), "bytes": len(binary),
               "source_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("new_output_directory", type=Path)
    print(json.dumps(build(p.parse_args().new_output_directory)))
