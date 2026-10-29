"""Turn a staged job into install.bin with SyncExtPack's own crypto_pack (in the container)."""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import container, window
from .job import Job


class PackError(Exception):
    pass


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
    try:
        container.ensure_image()
        container.run(workdir, "./crypto_pack", "-p", "payload", "install.bin",
                      job.serial, "0", "meta.txt", quiet=True)
    finally:
        tool.unlink(missing_ok=True)
    # crypto_pack's exit status is not trustworthy, so judge it by its output.
    if not output.is_file() or output.stat().st_size == 0:
        raise PackError("crypto_pack produced no install.bin")
    return output


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
