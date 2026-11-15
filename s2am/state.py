"""What the Mac knows about each car, keyed by APIM serial.

Layout under $S2AM_HOME (default ~/.s2am):
    <serial>/jobs/<id>.json        job plus status: pending, applied, already-applied,
                                   processed-no-report, unknown
    <serial>/reports/<id>/...      the report files exactly as the car wrote them
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("S2AM_HOME", Path.home() / ".s2am"))


@dataclass
class Entry:
    kind: str  # "F" or "D"
    path: str
    size: int | None = None


def parse_inventory(text: str) -> list[Entry]:
    entries = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if parts[0] == "D" and len(parts) == 2:
            entries.append(Entry("D", parts[1]))
        elif parts[0] == "F" and len(parts) == 3:
            entries.append(Entry("F", parts[1], int(parts[2]) if parts[2].isdigit() else None))
    return entries


def parse_info(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


SUCCESS = ("applied", "already-applied")
# A job that ran to the end but whose files on the car failed the Mac's byte check: not a success,
# but its inventory is still the car as it was read then, so it counts as the newest inventory.
INVENTORIED = (*SUCCESS, "not-verified")
# The Mac's byte check of a swap job's files on the car, kept in the job's record from the import
# that made it until a later one succeeds (cli._byte_check): a stick prepared again, an import of a
# pending stick or a replay must not lose it.
VERDICTS = ("verified", "not_verified")
# The status the last import found (any but "pending": the car had run the job) and when it was
# imported. A stick prepared again ("on-stick") or imported before the car ran it ("pending") keeps
# both, so the job keeps its place among the inventories (successful) whatever its status says now.
OUTCOME = ("outcome", "imported_utc")
# Statuses no import gives a job that ran (built, put on a stick, imported before it ran, set aside)
NOT_RUN = ("built", "on-stick", "pending", "withdrawn")


def outcome(record: dict) -> dict:
    """The OUTCOME fields to carry into a record that replaces this one. A record saved before
    they were kept has only its status: if an import gave it (it has imported_utc and is not one
    of NOT_RUN), that status was its outcome."""
    if "outcome" in record:
        return {key: record[key] for key in OUTCOME if key in record}
    if record.get("status") not in (None, *NOT_RUN) and record.get("imported_utc"):
        return {"outcome": record["status"], "imported_utc": record["imported_utc"]}
    return {}


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or home()

    def _inside(self, *parts: str) -> Path:
        """A path under the store root; ids and serials must not escape it."""
        if any(not part or part in (".", "..") or "/" in part or "\\" in part for part in parts):
            raise ValueError(f"unsafe store path {parts!r}")
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError(f"unsafe store path {parts!r}")
        return path

    def car(self, serial: str) -> Path:
        return self._inside(serial)

    def save_job(self, serial: str, job_id: str, record: dict) -> None:
        path = self._inside(serial, "jobs", f"{job_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2) + "\n")

    def job(self, serial: str, job_id: str) -> dict:
        return json.loads(self._inside(serial, "jobs", f"{job_id}.json").read_text())

    def jobs(self, serial: str) -> list[dict]:
        folder = self.car(serial) / "jobs"
        if not folder.is_dir():
            return []
        return sorted((json.loads(p.read_text()) for p in folder.glob("*.json")),
                      key=lambda record: (record.get("created_utc", ""), record["id"]))

    def save_report(self, serial: str, job_id: str, source: Path) -> Path:
        """Copy a report's regular files (callers reject symlinked reports first).

        Contents only: files fetched from the car keep CE's read-only and hidden attributes on
        the FAT stick, which macOS shows as flags (uchg, arch) and refuses to copy.
        """
        target = self._inside(serial, "reports", job_id)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for path in sorted(source.rglob("*")):
            destination = target / path.relative_to(source)
            if path.is_symlink():
                continue
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        return target

    def save_log(self, serial: str, job_id: str, log: Path) -> None:
        target = self._inside(serial, "reports", job_id)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log, target / "install_log.txt", follow_symlinks=False)

    def report(self, serial: str, job_id: str) -> Path | None:
        path = self._inside(serial, "reports", job_id)
        return path if path.is_dir() else None

    def successful(self, serial: str) -> list[dict]:
        """Jobs whose inventory reached the Mac, in the order the Mac imported them (a job that
        ran to the end but failed the byte check included: its inventory is still the car's), by
        their last outcome (OUTCOME; a record from before it was kept has only its status)."""
        records = [r for r in self.jobs(serial) if r.get("outcome", r.get("status")) in INVENTORIED
                   and (report := self.report(serial, r["id"]))
                   and (report / "inventory.txt").is_file()]
        return sorted(records, key=lambda r: (r.get("imported_utc", ""), r.get("created_utc", "")))

    def latest_inventory(self, serial: str) -> tuple[str, list[Entry], dict[str, str]] | None:
        """(job id, entries, info) of the inventory imported most recently."""
        for record in reversed(self.successful(serial)):
            report = self.report(serial, record["id"])
            if report:
                info = report / "info.txt"
                return (record["id"],
                        parse_inventory((report / "inventory.txt").read_text(errors="replace")),
                        parse_info(info.read_text(errors="replace")) if info.exists() else {})
        return None


def diff(old: list[Entry], new: list[Entry]) -> list[str]:
    """Human-readable changes between two inventories (paths compared case-insensitively)."""
    before = {e.path.lower(): e for e in old}
    after = {e.path.lower(): e for e in new}
    lines = []
    for key in sorted(after.keys() - before.keys()):
        lines.append(f"+ {after[key].path}" + (f" ({after[key].size} B)" if after[key].size is not None else ""))
    for key in sorted(before.keys() - after.keys()):
        lines.append(f"- {before[key].path}")
    for key in sorted(before.keys() & after.keys()):
        if before[key].size != after[key].size:
            lines.append(f"~ {after[key].path} ({before[key].size} -> {after[key].size} B)")
    return lines
