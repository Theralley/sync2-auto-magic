"""Native WinCE ARM helpers for SYNC 2, built from s2am/native/*.c with CeGCC in Docker.

The compiler is ENLYZE's CeGCC 9.3.0 image (github.com/enlyze/ghcr-windows-ce-build-environment,
MIT), pinned by digest. Builds are cached under build/native and redone when a source
changes. Every binary is checked before use: ARM machine type, Windows CE subsystem,
and COREDLL.dll as its only import, so nothing else has to exist on the car.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

from . import container
from .container import REPO

sys.path.insert(0, str(REPO / "tools"))
import patch_waveout  # noqa: E402

IMAGE = ("ghcr.io/enlyze/windows-ce-build-environment-arm"
         "@sha256:22ea23d697accaab2b98fb12d81ccc1faade90f9fe490f554ae7c5c194dfe27c")
SOURCES = Path(__file__).resolve().parent / "native"
PROGRAMS = {"hello.exe": "hello.c", "notifylog.exe": "notifylog.c", "s2amrun.exe": "s2amrun.c",
            "s2amwatch.exe": "s2amwatch.c"}
CFLAGS = ("-O2", "-Wall", "-Wextra", "-Werror")
SUBSYSTEM_WINDOWS_CE_GUI = 9


class NativeError(Exception):
    pass


def check(binary: bytes, name: str = "binary") -> None:
    """Refuse anything that is not a CE ARM program needing only COREDLL."""
    try:
        image = patch_waveout.PEImage(binary)
    except patch_waveout.PatchError as error:
        raise NativeError(f"{name}: {error}") from error
    subsystem = image.u16(image.opt + 68)
    if subsystem != SUBSYSTEM_WINDOWS_CE_GUI:
        raise NativeError(f"{name}: subsystem {subsystem}, not Windows CE GUI")
    libraries = sorted({lib.upper() for _, lib, _, _ in image.import_descriptors()})
    if libraries != ["COREDLL.DLL"]:
        raise NativeError(f"{name}: imports {libraries}; only COREDLL.dll exists everywhere")


def _source_hash(source: Path) -> str:
    return hashlib.sha256(source.read_bytes() + " ".join(CFLAGS).encode() + IMAGE.encode()).hexdigest()


def build(out: Path | None = None) -> dict[str, Path]:
    """Build every program whose source changed; returns name -> checked binary."""
    out = (out or REPO / "build" / "native").resolve()
    out.mkdir(parents=True, exist_ok=True)
    stale = [name for name, source in PROGRAMS.items()
             if not (out / name).is_file() or not (out / f"{name}.sha256").is_file()
             or (out / f"{name}.sha256").read_text() != _source_hash(SOURCES / source)]
    if stale:
        for name in stale:
            shutil.copy2(SOURCES / PROGRAMS[name], out / PROGRAMS[name])
        script = " && ".join(
            f"arm-mingw32ce-gcc {' '.join(CFLAGS)} -o {name} {PROGRAMS[name]} && arm-mingw32ce-strip {name}"
            for name in stale)
        container.run(out, "sh", "-c", script, quiet=True, image=IMAGE)
        for name in stale:
            if not (out / name).is_file():
                raise NativeError(f"{name} was not built")
            check((out / name).read_bytes(), name)
            (out / f"{name}.sha256").write_text(_source_hash(SOURCES / PROGRAMS[name]))
    for name in PROGRAMS:
        check((out / name).read_bytes(), name)
    return {name: out / name for name in PROGRAMS}


def binary(name: str) -> bytes:
    return build()[name].read_bytes()
