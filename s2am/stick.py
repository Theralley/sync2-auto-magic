"""Prepare a USB stick with a job, and read back what the car wrote to it.

UpdateService renames install.bin to installed.bin after a run, but the rename
fails when installed.bin already exists, and the same install.bin then runs
again on the next insertion. So preparing a stick moves every earlier
UpdateService file out of the way first. A job that measures uses that on purpose:
its stick gets a stand-in installed.bin (STAY), so it runs again when it is inserted
again, and that second run only fetches the logs.

Everything read back from a stick is untrusted: job ids and serials are
validated, and symlinks anywhere in what we read are refused.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import diskcheck, hostos
from .job import Job, bundle_parts
from .state import VERDICTS, Store, outcome

UPDATER_DIR = "SyncExtPack"
# Earlier runs' files, plus the bootstrap's stage-one files: leaving Installer.jpg
# on a job stick would let the wallpaper picker reinstall the base pack by accident.
UPDATER_FILES = ("install.bin", "installed.bin", "install_log.txt", "pack_install.bin",
                 "Installer.jpg", "UpdateInstaller.dll", "update.bin")
# Stands in for installed.bin on the stick of a job that measures (read from UpdateService's
# code, see docs/TOOLKIT-PLAN.md; not yet seen in the car).
STAY = b"s2am: this file keeps install.bin in place, so the same stick runs again and fetches the logs\r\n"
# What the script's markers say, the most severe first: the import reads the first one present
# (_status). One run writes one stop, but a report can hold more: a marker an earlier run left
# that the car could not delete (a run that finds one stops first of all, job.OLD_REPORT, so only
# a job built before that check runs on with it), or a progress marker (CHANGING, a bundle's
# started.txt) that a later stop of the same run supersedes. Conflicting markers read as the worst.
STOPPED = {# the car may hold a damaged file, or a mix of old and new ones, or files a rollback put
           # back that only the Mac's byte check confirms
           "rollback-failed.txt": "rollback-failed", "copy-failed.txt": "failed",
           # a swap cut short: it found its own backup on the car, or it began changing the car and
           # reached neither a stop nor done.txt (job.CHANGING; after it a run writes only the two above)
           "started-before.txt": "interrupted", "changing.txt": "interrupted",
           # this run changed nothing, because an earlier run's files would not go: above the plain
           # "nothing changed" stops, so an earlier one of those does not speak for it
           "old-report.txt": "failed",
           # stopped before changing anything (the guard's, its own business)
           "stale.txt": "stale", "busy.txt": "busy", "backup-failed.txt": "failed",
           "backup-missing.txt": "failed", "payload-bad.txt": "failed", "missing.txt": "failed",
           "selftest-failed.txt": "failed", "backup-bad.txt": "failed", "unknown-runner.txt": "failed",
           "neon-failed.txt": "failed",
           # a bundle: its part that stopped says why; parts after it never ran (checked last)
           "part.txt": "stopped", "started.txt": "interrupted", "queued.txt": "not-run"}


class StickError(Exception):
    pass


REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a Windows junction or symlink


def _linked(path: Path) -> bool:
    """A symlink, or on Windows any reparse point: a junction is no symlink to Python 3.9."""
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT)
    except OSError:
        return False


def _check_volume(stick: Path, require_volume: bool, info: diskcheck.DiskInfo = diskcheck.diskutil_info) -> None:
    if not stick.is_dir() or _linked(stick):
        raise StickError(f"{stick} is not a mounted folder")
    if require_volume and not hostos.is_volume(stick):
        raise StickError(f"{stick} is not a removable volume: a stick is {hostos.places()}")
    if require_volume:  # the top folder of any drive, C:\ on Windows too, looks like a volume: ask the disk
        try:
            volume = info(str(stick))
        except Exception as error:  # diskutil, lsblk or PowerShell: whatever failed, nothing is written
            raise StickError(f"the disk behind {stick} could not be read: {error}") from error
        if not diskcheck.external(volume):
            held = f", it holds {', '.join(volume['SystemMounts'])}" if volume.get("SystemMounts") else ""
            raise StickError(f"{stick} is not on an external USB stick ({volume.get('BusProtocol', '?')}{held}); "
                             "refusing to use it")
        if volume.get("FilesystemName") != "MS-DOS FAT32":  # all SYNC reads; it has no links of any kind
            raise StickError(f"{stick} is not FAT32 ({volume.get('FilesystemName', '?')}); refusing to use it")
    for folder in (stick / UPDATER_DIR, stick / "s2am"):
        if _linked(folder):
            raise StickError(f"{folder} is a symlink; refusing to use this stick")


def _has_symlink(path: Path) -> bool:
    if _linked(path):
        return True
    return path.is_dir() and any(_linked(p) for p in path.rglob("*"))


def prepare(stick: Path, install_bin: Path, job: Job, require_volume: bool = True,
            info: diskcheck.DiskInfo = diskcheck.diskutil_info) -> Path:
    """Put one job on the stick; returns the archive folder that holds earlier files."""
    _check_volume(stick, require_volume, info)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = stick / "s2am" / "history" / stamp
    updater = stick / UPDATER_DIR
    updater.mkdir(exist_ok=True)
    for name in UPDATER_FILES:
        old = updater / name
        if old.exists() or _linked(old):
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(archive / name))
    shutil.copy2(install_bin, updater / "install.bin")
    if runs_again(job):
        (updater / "installed.bin").write_bytes(STAY)
    pending = stick / "s2am" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    # Only one job fits on a stick; an older one that never ran is superseded.
    for old in pending.glob("*.json"):
        (archive / "superseded").mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(archive / "superseded" / old.name))
    (pending / f"{job.id}.json").write_bytes(job.to_json().encode())  # \n line ends from every computer
    if job.kind == "bundle":  # each part reports on its own, so the Mac verifies each one
        for part in bundle_parts(job):
            (pending / f"{part.id}.json").write_bytes(part.to_json().encode())
    return archive


def runs_again(job: Job) -> bool:
    """A job that measures: its second run on the car fetches what the first one started."""
    return job.kind in ("akcfg", "guard") and job.params.get("measure") is not None


def _used(updater: Path) -> bool:
    """UpdateService renamed install.bin after a run (the stand-in is ours, not a run's)."""
    used = updater / "installed.bin"
    return used.exists() and not (used.is_file() and used.read_bytes() == STAY)


def differences(stick: Path, install_bin: Path, job: Job) -> list[str]:
    """What on the stick does not read back as prepare wrote it: install.bin and the job records."""
    wrong = []
    stand_in = stick / UPDATER_DIR / "installed.bin"
    if runs_again(job) and not (stand_in.is_file() and stand_in.read_bytes() == STAY):
        wrong.append("installed.bin")
    if not (stick / UPDATER_DIR / "install.bin").is_file() or \
            (stick / UPDATER_DIR / "install.bin").read_bytes() != install_bin.read_bytes():
        wrong.append("install.bin")
    jobs = [job, *(bundle_parts(job) if job.kind == "bundle" else [])]
    for one in jobs:
        record = stick / "s2am" / "pending" / f"{one.id}.json"
        if not record.is_file() or record.read_bytes() != one.to_json().encode():
            wrong.append(f"s2am/pending/{one.id}.json")
    return wrong


def _status(report: Path, updater: Path) -> tuple[str, bool]:
    """(status, replayed) for one job from what is on the stick."""
    done = report / "done.txt"
    replayed = (report / "replayed.txt").is_file()
    if done.is_file():
        return "applied", replayed
    if replayed:
        return "already-applied", True  # its first run reported somewhere else
    # The script stopped on purpose; its marker says what state it left behind.
    for marker, status in STOPPED.items():
        if (report / marker).is_file():
            return status, False
    stand_in = updater / "installed.bin"
    if _used(updater) or (stand_in.is_file() and (updater / "install_log.txt").exists()):
        return "processed-no-report", False  # with the stand-in, UpdateService's log shows the run
    if (updater / "install.bin").exists():
        return "pending", False
    return "unknown", False


def import_reports(stick: Path, store: Store, require_volume: bool = True,
                   info: diskcheck.DiskInfo = diskcheck.diskutil_info) -> list[dict]:
    """Move every pending job's outcome from the stick into the store."""
    _check_volume(stick, require_volume, info)
    pending = stick / "s2am" / "pending"
    imported = stick / "s2am" / "imported"
    rejected = stick / "s2am" / "rejected"
    updater = stick / UPDATER_DIR
    log = updater / "install_log.txt"
    results = []
    for path in sorted(pending.glob("*.json")) if pending.is_dir() else []:
        try:
            if _linked(path):
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
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        try:
            stored = store.job(job.serial, job.id)
        except (OSError, ValueError):
            stored = {}
        # A diagnostic's expected decoder hashes are host evidence, never USB input.
        # Also inspect the ID and stored kind so changing the returned kind cannot bypass this.
        if job.kind == "decdiag" or job.id.split("-")[2] == "decdiag" or stored.get("kind") == "decdiag":
            try:
                trusted = Job.from_json(json.dumps(stored))
                if json.loads(trusted.to_json()) != json.loads(job.to_json()):
                    raise ValueError("decoder inspection identity differs from its local job")
            except ValueError:
                rejected.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(rejected / path.name))
                results.append({"id": job.id, "status": "rejected",
                                "reason": "decoder inspection has no matching trusted local job"})
                continue
        # A replayed job ran nothing: its report is the first run's, so it keeps that run's
        # place in time instead of looking like fresh evidence.
        record = {**json.loads(job.to_json()), "status": status, "replayed": replayed,
                  "imported_utc": (stored.get("imported_utc") if replayed else None) or now}
        known = stored.get("status")
        record.update({key: stored[key] for key in VERDICTS if key in stored})  # whatever this import says
        if status == "pending":  # the car has not run it: its last outcome, and when, stay as they were
            record.update(outcome(stored))
        if known == "applied" and status not in ("applied", "already-applied"):
            # it ran from another stick; this one (a bundle that stopped before it) did not run it
            results.append({**record, "status": status, "reason": "it is applied already, from another run"})
            imported.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(imported / path.name))
            continue
        if report.exists() and _has_symlink(report):
            record["status"] = "rejected"
            record["reason"] = "report contains a symlink"
        elif report.is_dir():
            store.save_report(job.serial, job.id, report)
        if status != "pending" and log.is_file() and not _linked(log):
            store.save_log(job.serial, job.id, log)
        if status != "pending":
            record["outcome"] = record["status"]
        store.save_job(job.serial, job.id, record)
        results.append(record)
        if status != "pending":
            imported.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(imported / path.name))
            if runs_again(job) and not _used(updater) and (updater / "install.bin").is_file():
                # Its record has left the stick, so the stick must not run again: it could no
                # longer tell which stick it is, and nothing it did would be imported.
                (updater / "installed.bin").unlink(missing_ok=True)
                (updater / "install.bin").rename(updater / "installed.bin")
    return results
