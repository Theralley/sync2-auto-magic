"""Jobs: one install.bin that SYNC 2's UpdateService runs, plus the report it leaves on the stick.

A job stages its files under \\SyncExtendedPack\\_s2am\\jobs\\<id>\\ together with
MortScript and MortRunner. MortRunner renamed to s2amjob.exe runs s2amjob.mscr
from its own folder, the same way SyncExtPack's RemoveExtPack runs its script.
UpdateService starts it as POST_APP after copying the files and waits for it.

The script writes its report to \\USB Disk\\s2am\\reports\\<id>\\ and leaves a done
marker on the car, so a stick that is inserted again cannot apply a job twice.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

JOBS_DIR = "/SyncExtendedPack/_s2am/jobs"
DONE_DIR = "/SyncExtendedPack/_s2am/done"
REPORTS_DIR = "/USB Disk/s2am/reports"
RUNNER_NAME = "s2amjob"
MORTSCRIPT_SOURCE = Path("FullPack/RemoveExtPack/MortScript.exe")
MORTRUNNER_SOURCE = Path("FullPack/RemoveExtPack/RemoveExtPack.exe")

# Inventory covers what sideloading touches. Three levels under Apps reaches
# every app's own files (Apps/<Category>/<App>/<files>, plus one subfolder).
INVENTORY_ROOT = "\\SyncExtendedPack\\Apps"
PLUGINS_MASK = "\\windows\\*Plugin.dll"
MENU_XML = "\\8inchSkins\\Ford\\Sync\\Apps\\Info\\SyncApps\\SyncApps.xml"
AUTOKIT_CE = "\\SyncExtendedPack\\Apps\\Media\\AutoKit"
# The modules tools/patch_waveout.py patches (tools/make_pack.py PATCH_TARGETS).
AUTOKIT_MODULES = ("AutoKit.exe", "libgstwaveoutsink.dll", "libgstwaveform.dll")


JOB_ID = re.compile(r"\d{8}-\d{6}-[a-z]{2,8}-[0-9a-f]{4}")
SERIAL = re.compile(r"[0-9A-NP-Z]{8}")  # upstream validateSerial: 8 characters, no letter O


def ce_path(path: str) -> str:
    """Car paths are written with forward slashes in code, backslashes on the car."""
    return path.replace("/", "\\")


def validate(job: "Job") -> "Job":
    """Refuse a job whose id or serial could name a path outside s2am's folders.

    job.json comes back from a USB stick, so it is untrusted input.
    """
    if not JOB_ID.fullmatch(job.id):
        raise ValueError(f"invalid job id {job.id!r}")
    if not SERIAL.fullmatch(job.serial):
        raise ValueError(f"invalid serial {job.serial!r}")
    return job


@dataclass
class Job:
    serial: str
    kind: str
    id: str = ""
    created_utc: str = ""
    files: dict[str, str] = field(default_factory=dict)  # staged path -> sha256

    def __post_init__(self):
        if not self.created_utc:
            # Microseconds order jobs made within the same second (ids end in random hex).
            self.created_utc = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        if not self.id:
            stamp = datetime.fromisoformat(self.created_utc).strftime("%Y%m%d-%H%M%S")
            self.id = f"{stamp}-{self.kind}-{secrets.token_hex(2)}"

    @property
    def job_dir(self) -> str:
        return f"{JOBS_DIR}/{self.id}"

    @property
    def report_dir(self) -> str:
        return f"{REPORTS_DIR}/{self.id}"

    @property
    def done_marker(self) -> str:
        return f"{DONE_DIR}/{self.id}.txt"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Job":
        """Parse and validate; raises ValueError for anything malformed."""
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise TypeError("not an object")
            fields = {k: data[k] for k in ("serial", "kind", "id", "created_utc", "files")
                      if k in data}
            if any(not isinstance(fields.get(k, ""), str)
                   for k in ("serial", "kind", "id", "created_utc")) \
                    or not isinstance(fields.get("files", {}), dict):
                raise TypeError("wrong field types")
            job = cls(**fields)
        except (TypeError, KeyError, ValueError) as error:  # JSONDecodeError is a ValueError
            raise ValueError(f"malformed job.json: {error}") from error
        return validate(job)


def _quote(text: str) -> str:
    if '"' in text:
        raise ValueError(f"MortScript string may not contain a quote: {text!r}")
    return f'"{text}"'


def _header(job: Job) -> list[str]:
    """Silence error dialogs, create the report folder, and stop if this job already ran.

    UpdateService waits for the script without a timeout, so an error dialog
    would stall the car until someone taps OK. ErrorLevel("off") makes runtime
    errors silent (MortScript manual 9.1); completion is proven instead by
    done.txt, which is written only once the inventory exists.
    """
    return [
        f"# s2am {job.kind} job {job.id}",
        'ErrorLevel("off")',
        f"out = {_quote(ce_path(job.report_dir))}",
        'MkDir("\\USB Disk\\s2am")',
        'MkDir("\\USB Disk\\s2am\\reports")',
        "MkDir(out)",
        f"If (FileExists({_quote(ce_path(job.done_marker))}))",
        f'  WriteFile(out & "\\replayed.txt", {_quote(job.id)})',
        "  Exit",
        "EndIf",
    ]


def _inventory() -> list[str]:
    """List sideloaded files with sizes and copy the Apps menu.

    ForEach over files()/directories() yields full paths (MortScript Interpreter.cpp).
    """
    return [
        'inv = out & "\\inventory.txt"',
        'WriteFile(inv, "")',
        f"ForEach a in directories({_quote(INVENTORY_ROOT + chr(92) + '*')})",
        '  WriteFile(inv, "D|" & a & "^NL^", TRUE)',
        '  ForEach f in files(a & "\\*.*")',
        '    WriteFile(inv, "F|" & f & "|" & FileSize(f) & "^NL^", TRUE)',
        "  EndForEach",
        '  ForEach b in directories(a & "\\*")',
        '    WriteFile(inv, "D|" & b & "^NL^", TRUE)',
        '    ForEach f in files(b & "\\*.*")',
        '      WriteFile(inv, "F|" & f & "|" & FileSize(f) & "^NL^", TRUE)',
        "    EndForEach",
        '    ForEach c in directories(b & "\\*")',
        '      WriteFile(inv, "D|" & c & "^NL^", TRUE)',
        '      ForEach f in files(c & "\\*.*")',
        '        WriteFile(inv, "F|" & f & "|" & FileSize(f) & "^NL^", TRUE)',
        "      EndForEach",
        "    EndForEach",
        "  EndForEach",
        "EndForEach",
        f"ForEach f in files({_quote(PLUGINS_MASK)})",
        '  WriteFile(inv, "F|" & f & "|" & FileSize(f) & "^NL^", TRUE)',
        "EndForEach",
        f'Copy({_quote(MENU_XML)}, out & "\\SyncApps.xml", TRUE)',
    ]


def _footer(job: Job) -> list[str]:
    """Mark the job done only if the inventory exists; the riskiest calls come last."""
    return [
        "If (FileExists(inv))",
        '  MkDir("\\SyncExtendedPack\\_s2am")',
        f"  MkDir({_quote(ce_path(DONE_DIR))})",
        f"  WriteFile({_quote(ce_path(job.done_marker))}, {_quote(job.id)})",
        f'  WriteFile(out & "\\done.txt", {_quote(job.id + " applied")})',
        "EndIf",
        'info = "job=" & ' + _quote(job.id) + ' & "^NL^"',
        'info = info & "time=" & FormatTime("Y-m-d H:i:s") & "^NL^"',
        'info = info & "mortscript=" & MortScriptVersion() & "^NL^"',
        'info = info & "free=" & FreeDiskSpace("\\") & "^NL^"',
        'WriteFile(out & "\\info.txt", info)',
    ]


def _script(lines: list[str]) -> str:
    return "\r\n".join(lines) + "\r\n"


def inventory_script(job: Job) -> str:
    """MortScript that lists sideloaded files and copies the menu to the stick."""
    return _script(_header(job) + _inventory() + _footer(job))


def autokit_script(job: Job, variant: str) -> str:
    """Swap AutoKit's three audio modules to their *.orig or *.patched copies, then inventory.

    make_pack ships both copies beside each module. AutoKit must not be running
    while its files are replaced; if it is, the job reports busy.txt, leaves no
    done marker, and runs again on the next insertion after a restart.
    """
    if variant not in ("orig", "patched"):
        raise ValueError(f"unknown AutoKit variant {variant!r}")
    swap = [
        'If (ProcExists("AutoKit.exe"))',
        '  WriteFile(out & "\\busy.txt", "AutoKit is running: restart SYNC, insert the stick again")',
        "  Exit",
        "EndIf",
        f"ak = {_quote(AUTOKIT_CE)}",
    ]
    for module in AUTOKIT_MODULES:
        source = f'ak & "\\{module}.{variant}"'
        swap += [f"If (FileExists({source}))",
                 f'  Copy({source}, ak & "\\{module}", TRUE)',
                 "EndIf"]
    return _script(_header(job) + swap + _inventory() + _footer(job))


SCRIPTS = {
    "inv": inventory_script,
    "akstock": lambda job: autokit_script(job, "orig"),
    "akpatch": lambda job: autokit_script(job, "patched"),
}


def meta(job: Job) -> bytes:
    """The META UpdateService reads: UTF-16LE KEY=VALUE lines, as upstream packer.py writes."""
    entries = {
        "HEADER": f"s2am {job.kind} job",
        "VERSION": f"s2am {job.id} for: {job.serial}",
        "POST_APP": f"{job.job_dir}/{RUNNER_NAME}.exe",
    }
    return "".join(f"{k}={v}\n" for k, v in entries.items()).encode("utf-16-le")


def stage(job: Job, upstream: Path, workdir: Path) -> Path:
    """Write payload/ and meta.txt for crypto_pack into a fresh ``workdir``."""
    if job.kind not in SCRIPTS:
        raise ValueError(f"unknown job kind {job.kind!r}")
    if workdir.exists():
        shutil.rmtree(workdir)
    target = workdir / "payload" / job.job_dir.lstrip("/")
    target.mkdir(parents=True)
    shutil.copy2(upstream / MORTSCRIPT_SOURCE, target / "MortScript.exe")
    shutil.copy2(upstream / MORTRUNNER_SOURCE, target / f"{RUNNER_NAME}.exe")
    (target / f"{RUNNER_NAME}.mscr").write_bytes(SCRIPTS[job.kind](job).encode("ascii"))

    job.files = {
        "/" + str(path.relative_to(workdir / "payload")): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(target.iterdir())
    }
    (target / "job.json").write_text(job.to_json())
    (workdir / "meta.txt").write_bytes(meta(job))
    (workdir / "job.json").write_text(job.to_json())
    return workdir
