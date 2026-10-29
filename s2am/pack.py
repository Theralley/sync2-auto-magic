"""Turn a staged job into install.bin with SyncExtPack's own crypto_pack (in the container).

The source folder is passed with a trailing slash, exactly as upstream's packer
does ("TempPack/"). Without it crypto_pack stores the paths differently and its
own unpacker extracts nothing. Every pack is therefore unpacked again with the
official tool and compared file by file with what was staged before it is used.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import container, window
from .job import Job

SOURCE = "payload/"  # the trailing slash matters (see above)
CHECK_DIR = "roundtrip"


class PackError(Exception):
    pass


def _tree(root: Path) -> dict[str, str]:
    """Relative path -> sha256 for every file under ``root``."""
    return {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}


def build(job: Job, workdir: Path, upstream: Path, now: datetime | None = None,
          force: bool = False) -> Path:
    """Pack ``workdir/payload`` into ``workdir/install.bin``; refuse near a window boundary."""
    safe, end = window.check(now or datetime.now(timezone.utc))
    if not safe and not force:
        raise PackError(f"too close to a key window boundary (window closes {end:%Y-%m-%d %H:%M} "
                        "UTC); wait, or force it and install promptly")
    tool = workdir / "crypto_pack"
    shutil.copy2(upstream / "crypto_pack", tool)
    tool.chmod(0o755)
    output = workdir / "install.bin"
    output.unlink(missing_ok=True)
    check = workdir / CHECK_DIR
    if check.exists():
        shutil.rmtree(check)
    try:
        container.ensure_image()
        container.run(workdir, "./crypto_pack", "-p", SOURCE, "install.bin",
                      job.serial, "0", "meta.txt", quiet=True)
        # crypto_pack's exit status is not trustworthy, so judge it by its output.
        if not output.is_file() or output.stat().st_size == 0:
            raise PackError("crypto_pack produced no install.bin")
        container.run(workdir, "./crypto_pack", "-u", "install.bin", CHECK_DIR,
                      job.serial, "0", quiet=True)
        expected, unpacked = _tree(workdir / "payload"), _tree(check) if check.is_dir() else {}
        if unpacked != expected:
            missing = sorted(expected.keys() - unpacked.keys())[:5]
            different = sorted(k for k in expected.keys() & unpacked.keys()
                               if expected[k] != unpacked[k])[:5]
            raise PackError(f"install.bin does not unpack to the staged files "
                            f"(missing {missing}, different {different}, "
                            f"unexpected {sorted(unpacked.keys() - expected.keys())[:5]})")
    finally:
        tool.unlink(missing_ok=True)
        if check.exists():
            shutil.rmtree(check)
    return output


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
