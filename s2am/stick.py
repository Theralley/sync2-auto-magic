"""Prepare a USB stick with a job, and read back what the car wrote to it.

UpdateService renames install.bin to installed.bin after a run, but the rename
fails when installed.bin already exists, and the same install.bin then runs
again on the next insertion. So preparing a stick moves every earlier
UpdateService file out of the way first.

Everything read back from a stick is untrusted: job ids and serials are
validated, and symlinks anywhere in what we read are refused.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .job import Job
from .state import Store

UPDATER_DIR = "SyncExtPack"
UPDATER_FILES = ("install.bin", "installed.bin", "install_log.txt", "pack_install.bin")


class StickError(Exception):
    pass


def _check_volume(stick: Path, require_volume: bool) -> None:
    if not stick.is_dir() or stick.is_symlink():
        raise StickError(f"{stick} is not a mounted folder")
    if require_volume and stick.resolve().parent != Path("/Volumes"):
        raise StickError(f"{stick} is not a removable volume under /Volumes")
    for folder in (stick / UPDATER_DIR, stick / "s2am"):
        if folder.is_symlink():
            raise StickError(f"{folder} is a symlink; refusing to use this stick")


def _has_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    return path.is_dir() and any(p.is_symlink() for p in path.rglob("*"))


def prepare(stick: Path, install_bin: Path, job: Job, require_volume: bool = True) -> Path:
    """Put one job on the stick; returns the archive folder that holds earlier files."""
    _check_volume(stick, require_volume)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = stick / "s2am" / "history" / stamp
    updater = stick / UPDATER_DIR
    updater.mkdir(exist_ok=True)
    for name in UPDATER_FILES:
        old = updater / name
        if old.exists() or old.is_symlink():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(archive / name))
    shutil.copy2(install_bin, updater / "install.bin")
    pending = stick / "s2am" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    # Only one job fits on a stick; an older one that never ran is superseded.
    for old in pending.glob("*.json"):
        (archive / "superseded").mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(archive / "superseded" / old.name))
    (pending / f"{job.id}.json").write_text(job.to_json())
    return archive


def _status(report: Path, updater: Path) -> tuple[str, bool]:
    """(status, replayed) for one job from what is on the stick."""
    done = report / "done.txt"
    replayed = (report / "replayed.txt").is_file()
    if done.is_file():
        return "applied", replayed
    if replayed:
        return "already-applied", True  # its first run reported somewhere else
    if (updater / "installed.bin").exists():
        return "processed-no-report", False
    if (updater / "install.bin").exists():
        return "pending", False
    return "unknown", False


def import_reports(stick: Path, store: Store, require_volume: bool = True) -> list[dict]:
    """Move every pending job's outcome from the stick into the store."""
    _check_volume(stick, require_volume)
    pending = stick / "s2am" / "pending"
    imported = stick / "s2am" / "imported"
    rejected = stick / "s2am" / "rejected"
    updater = stick / UPDATER_DIR
    log = updater / "install_log.txt"
    results = []
    for path in sorted(pending.glob("*.json")) if pending.is_dir() else []:
        try:
            if path.is_symlink():
                raise ValueError("job file is a symlink")
            job = Job.from_json(path.read_text(errors="replace"))
            if path.stem != job.id:
                raise ValueError("file name does not match the job id")
        except ValueError as error:
            rejected.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(rejected / path.name))
            results.append({"id": path.stem, "status": "rejected", "reason": str(error)})
            continue

        report = stick / "s2am" / "reports" / job.id
        status, replayed = _status(report, updater)
        record = {**json.loads(job.to_json()), "status": status, "replayed": replayed,
                  "imported_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
        if report.exists() and _has_symlink(report):
            record["status"] = "rejected"
            record["reason"] = "report contains a symlink"
        elif report.is_dir():
            store.save_report(job.serial, job.id, report)
        if status != "pending" and log.is_file() and not log.is_symlink():
            store.save_log(job.serial, job.id, log)
        store.save_job(job.serial, job.id, record)
        results.append(record)
        if status != "pending":
            imported.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(imported / path.name))
    return results
