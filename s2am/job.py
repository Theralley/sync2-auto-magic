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

from . import mortscript

JOBS_DIR = "/SyncExtendedPack/_s2am/jobs"
DONE_DIR = "/SyncExtendedPack/_s2am/done"
BACKUP_DIR = "\\SyncExtendedPack\\_s2am\\backup"
PHASE_DIR = "\\SyncExtendedPack\\_s2am\\phase"
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
TOOLS_CE = "\\SyncExtendedPack\\Apps\\Tools"
GUARD_LOG = "\\SyncExtendedPack\\_s2am\\guard.log"
AUTOKIT_LOGS = ("hwlog.log", "hwlog.txt")  # AutoKit writes hwlog.log into its folder
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
    params: dict = field(default_factory=dict)           # what remove/undo jobs act on

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
            fields = {k: data[k] for k in ("serial", "kind", "id", "created_utc", "files", "params")
                      if k in data}
            if any(not isinstance(fields.get(k, ""), str)
                   for k in ("serial", "kind", "id", "created_utc")) \
                    or not isinstance(fields.get("files", {}), dict) \
                    or not isinstance(fields.get("params", {}), dict):
                raise TypeError("wrong field types")
            job = cls(**fields)
        except (TypeError, KeyError, ValueError) as error:  # JSONDecodeError is a ValueError
            raise ValueError(f"malformed job.json: {error}") from error
        return validate(job)


def _quote(text: str) -> str:
    if '"' in text:
        raise ValueError(f"MortScript string may not contain a quote: {text!r}")
    return f'"{text}"'


# Mount names a USB stick may get on SYNC 2. UpdateService itself finds install.bin on any
# of them ("%s\\SyncExtPack\\install.bin") but logs to a fixed "\\USB Disk", so the job
# looks for its own pending file to know which one is the stick.
STICK_MOUNTS = ("\\USB Disk", "\\USB Disk2", "\\USB Disk 2", "\\USB Disk1", "\\USB Disk3")


def _find_stick(job: Job) -> list[str]:
    candidates = ", ".join(_quote(m) for m in STICK_MOUNTS)
    return [
        f"stick = {_quote(STICK_MOUNTS[0])}",
        "found = 0",
        f"ForEach d in values({candidates})",
        f'  If (FileExists(d & "\\s2am\\pending\\{job.id}.json"))',
        "    stick = d",
        "    found = found + 1",
        "  EndIf",
        "EndForEach",
    ]


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
        *_find_stick(job),
        f'out = stick & "\\s2am\\reports\\{job.id}"',
        'MkDir(stick & "\\s2am")',
        'MkDir(stick & "\\s2am\\reports")',
        "MkDir(out)",
        "If (found <> 1)",
        '  WriteFile(out & "\\mount-check.txt", "pending file found on " & found & " USB mounts")',
        "EndIf",
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
        f'If (FileExists({_quote(AUTOKIT_CE + chr(92) + "screenconfig")}))',
        f'  Copy({_quote(AUTOKIT_CE + chr(92) + "screenconfig")}, out & "\\autokit-screenconfig.txt", TRUE)',
        "EndIf",
        f'If (FileExists({_quote(AUTOKIT_CE + chr(92) + "lang")}))',
        f'  Copy({_quote(AUTOKIT_CE + chr(92) + "lang")}, out & "\\autokit-lang.bin", TRUE)',
        "EndIf",
        f"If (FileExists({_quote(GUARD_LOG)}))",
        f'  Copy({_quote(GUARD_LOG)}, out & "\\guard.log", TRUE)',
        "EndIf",
        *[line for name in AUTOKIT_LOGS for line in (  # AutoKit's own log
            f'If (FileExists({_quote(AUTOKIT_CE + chr(92) + name)}))',
            f'  Copy({_quote(AUTOKIT_CE + chr(92) + name)}, out & "\\autokit-{name}", TRUE)',
            "EndIf")],
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
    """The script text, with bare keywords hardened and checked by the car's rules."""
    text = "\r\n".join(mortscript.harden(line) for line in lines) + "\r\n"
    mortscript.check(text)
    return text


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
        '  WriteFile(out & "\\busy.txt", "AutoKit is running: restart SYNC and re-prepare the stick on the Mac")',
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


def _length(value) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid menu length {value!r}")
    return value


def _stop(marker: str, message: str, indent: str = "") -> list[str]:
    return [f'{indent}WriteFile(out & "\\{marker}", {_quote(message)})', f"{indent}Exit"]


def _menu_files(job: Job, expected_len: int, new_len: int | None = None) -> list[str]:
    """Name the live menu and the menus shipped in the job folder; stop if a shipped one is incomplete.

    The menus are compared by content with ReadFile and string ``ne``
    (MortScript manual 7.7 and 9.12): a file size alone cannot tell two menus apart.
    """
    lines = [
        f"xml = {_quote(MENU_XML)}",
        f"jd = {_quote(ce_path(job.job_dir))}",
        'exp = jd & "\\SyncApps.xml.expected"',
        f"If (FileSize(exp) <> {_length(expected_len)})",
        *_stop("payload-bad.txt", "the job's menu files are incomplete; nothing changed", "  "),
        "EndIf",
    ]
    if new_len is not None:
        lines += [
            'new = jd & "\\SyncApps.xml.new"',
            f"If (FileSize(new) <> {_length(new_len)})",
            *_stop("payload-bad.txt", "the job's menu files are incomplete; nothing changed", "  "),
            "EndIf",
        ]
    return lines


def menu_change_script(job: Job) -> str:
    """Swap the Apps menu for the one the Mac planned; a removal then deletes what it owns.

    Used by remove (optional deletes) and install (UpdateService has already
    copied the app's files before this POST script runs). Nothing is deleted
    until the live menu provably equals the new one, so the menu can never point
    at a deleted plugin. Phase one (back up, replace, verify, or restore on
    failure) leaves a phase marker; a run interrupted after that point resumes
    instead of reporting a stale menu.
    """
    p = job.params
    phase = f"{PHASE_DIR}\\{job.id}.txt"
    lines = _header(job) + _menu_files(job, p["expected_len"], p["new_len"])
    for exe in p.get("executables", []):
        lines += [f"If (ProcExists({_quote(exe)}))",
                  *_stop("busy.txt", exe + " is running: restart SYNC and re-prepare the stick on the Mac", "  "),
                  "EndIf"]
    lines += [
        f"If (FileExists({_quote(phase)}))",
        "  If (ReadFile(xml) ne ReadFile(new))",
        *_stop("stale.txt", "SyncApps.xml changed after this job replaced it; nothing deleted", "    "),
        "  EndIf",
        "Else",
        "  If (ReadFile(xml) ne ReadFile(exp))",
        *_stop("stale.txt", "SyncApps.xml changed since the last report: run an inventory first", "    "),
        "  EndIf",
        '  MkDir("\\SyncExtendedPack\\_s2am")',
        f"  MkDir({_quote(BACKUP_DIR)})",
        f"  bk = {_quote(BACKUP_DIR + chr(92) + job.id)}",
        "  MkDir(bk)",
        '  Copy(xml, bk & "\\SyncApps.xml", TRUE)',
        '  If (ReadFile(bk & "\\SyncApps.xml") ne ReadFile(exp))',
        *_stop("backup-failed.txt", "could not back up SyncApps.xml; nothing changed", "    "),
        "  EndIf",
        "  Copy(new, xml, TRUE)",
        "  If (ReadFile(xml) ne ReadFile(new))",
        "    Copy(exp, xml, TRUE)",
        *_stop("copy-failed.txt", "could not write the new menu; old menu put back, nothing deleted", "    "),
        "  EndIf",
        f"  MkDir({_quote(PHASE_DIR)})",
        f"  WriteFile({_quote(phase)}, {_quote(job.id)})",
        "EndIf",
    ]
    for folder in p.get("delete_dirs", []):
        lines += [f"DelTree({_quote(ce_path(folder.rstrip('/')))})",
                  f"RmDir({_quote(ce_path(folder.rstrip('/')))})"]
    for path in p.get("delete_files", []):
        lines += [f"Delete({_quote(ce_path(path))})"]
    return _script(lines + _inventory() + _footer(job))


def undo_script(job: Job) -> str:
    """Put back the menu a remove job backed up (deleted files are not restored).

    Runs only if the live menu is exactly the one that remove job left behind.
    """
    p = job.params
    if not JOB_ID.fullmatch(p.get("target", "")):
        raise ValueError(f"invalid undo target {p.get('target')!r}")
    backup = f"{BACKUP_DIR}\\{p['target']}\\SyncApps.xml"
    lines = _header(job) + _menu_files(job, p["expected_len"]) + [
        f"bk = {_quote(backup)}",
        "If (ReadFile(xml) ne ReadFile(exp))",
        *_stop("stale.txt", "SyncApps.xml changed after that removal: undo the later change first", "  "),
        "EndIf",
        "If (NOT FileExists(bk))",
        *_stop("backup-missing.txt", "no backup for that job on the car; nothing changed", "  "),
        "EndIf",
        "Copy(bk, xml, TRUE)",
        "If (ReadFile(xml) ne ReadFile(bk))",
        "  Copy(exp, xml, TRUE)",
        *_stop("copy-failed.txt", "could not write the old menu; current menu put back", "  "),
        "EndIf",
    ]
    return _script(lines + _inventory() + _footer(job))


removal_script = menu_change_script

SCREEN = re.compile(r"\d{3,4},\d{3,4},\d{1,2}")
# AutoKit's ``lang`` file is a little-endian LCID; PAL2.dll maps it to \Temp\riddlebox\<x>.lng
# (0x0409 English.lng, 0x0804 Chinese_chs.lng, ...). The stock folder ships 0x0804.
AUTOKIT_LANGS = {"english": 0x0409, "german": 0x0407, "french": 0x040C, "spanish": 0x040A,
                 "russian": 0x0419, "chinese": 0x0804}


def autokit_lang_file(lcid: int) -> bytes:
    return lcid.to_bytes(4, "little")


def autokit_config_script(job: Job) -> str:
    """Set AutoKit's video size and decoder (or restore them), backing up what was there.

    AutoKit reads ``screenconfig`` ("width,height,fps") and the empty flag file
    ``usehwdec`` (present = hardware decoding) from its folder at start (Codex,
    AutoKit.exe+0x47a48). Any Auto_Box_Update.img is removed: AutoKit would flash it
    to the dongle, and a wrong image kills the dongle.
    """
    p = job.params
    ak = AUTOKIT_CE
    lines = _header(job) + [
        f"ak = {_quote(ak)}",
        "If (NOT DirExists(ak))",
        *_stop("missing.txt", "AutoKit is not installed; nothing changed", "  "),
        "EndIf",
        'If (ProcExists("AutoKit.exe"))',
        *_stop("busy.txt", "AutoKit is running: restart SYNC and re-prepare the stick on the Mac", "  "),
        "EndIf",
    ]
    if p.get("restore"):
        if not JOB_ID.fullmatch(p["restore"]):
            raise ValueError(f"invalid restore target {p['restore']!r}")
        lines += [
            f"src = {_quote(BACKUP_DIR + chr(92) + p['restore'])}",
            "If (NOT DirExists(src))",
            *_stop("backup-missing.txt", "no backup for that job on the car; nothing changed", "  "),
            "EndIf",
            'If (FileExists(src & "\\screenconfig"))',
            '  Copy(src & "\\screenconfig", ak & "\\screenconfig", TRUE)',
            "EndIf",
            'If (FileExists(src & "\\screenconfig.absent"))',
            '  Delete(ak & "\\screenconfig")',
            "EndIf",
            'If (FileExists(src & "\\usehwdec.present"))',
            '  WriteFile(ak & "\\usehwdec", "")',
            "EndIf",
            'If (FileExists(src & "\\usehwdec.absent"))',
            '  Delete(ak & "\\usehwdec")',
            "EndIf",
            'If (FileExists(src & "\\lang"))',
            '  Copy(src & "\\lang", ak & "\\lang", TRUE)',
            "EndIf",
            'If (FileExists(src & "\\lang.absent"))',
            '  Delete(ak & "\\lang")',
            "EndIf",
        ]
    else:
        screen, decoder, lang = p.get("screen"), p.get("decoder"), p.get("lang")
        video = screen is not None or decoder is not None
        if video and (not SCREEN.fullmatch(str(screen)) or decoder not in ("software", "hardware")):
            raise ValueError(f"invalid AutoKit settings {screen!r}/{decoder!r}")
        if lang is not None and lang not in AUTOKIT_LANGS:
            raise ValueError(f"invalid AutoKit language {lang!r}")
        if not video and lang is None:
            raise ValueError("nothing to set")
        lines += [
            'MkDir("\\SyncExtendedPack\\_s2am")',
            f"MkDir({_quote(BACKUP_DIR)})",
            f"bk = {_quote(BACKUP_DIR + chr(92) + job.id)}",
            "MkDir(bk)",
        ]
        if video:
            lines += [
                'If (FileExists(ak & "\\screenconfig"))',
                '  Copy(ak & "\\screenconfig", bk & "\\screenconfig", TRUE)',
                "Else",
                '  WriteFile(bk & "\\screenconfig.absent", "")',
                "EndIf",
                'If (FileExists(ak & "\\usehwdec"))',
                '  WriteFile(bk & "\\usehwdec.present", "")',
                "Else",
                '  WriteFile(bk & "\\usehwdec.absent", "")',
                "EndIf",
                'If (NOT FileExists(bk & "\\screenconfig"))',
                '  If (NOT FileExists(bk & "\\screenconfig.absent"))',
                *_stop("backup-failed.txt", "could not back up the AutoKit video settings; nothing changed", "    "),
                "  EndIf",
                "EndIf",
                f'WriteFile(ak & "\\screenconfig", {_quote(screen)})',
                'Delete(ak & "\\usehwdec")' if decoder == "software" else 'WriteFile(ak & "\\usehwdec", "")',
            ]
        if lang is not None:  # four binary bytes: shipped in the job folder, then copied over
            lines += [
                'If (FileExists(ak & "\\lang"))',
                '  Copy(ak & "\\lang", bk & "\\lang", TRUE)',
                "Else",
                '  WriteFile(bk & "\\lang.absent", "")',
                "EndIf",
                'If (NOT FileExists(bk & "\\lang"))',
                '  If (NOT FileExists(bk & "\\lang.absent"))',
                *_stop("backup-failed.txt", "could not back up the AutoKit language; nothing changed", "    "),
                "  EndIf",
                "EndIf",
                f'Copy({_quote(ce_path(job.job_dir))} & "\\lang", ak & "\\lang", TRUE)',
            ]
    lines += [
        'If (FileExists(ak & "\\Auto_Box_Update.img"))',
        '  Delete(ak & "\\Auto_Box_Update.img")',
        '  WriteFile(out & "\\firmware-image-removed.txt", "a dongle firmware image was removed")',
        "EndIf",
    ]
    return _script(lines + _inventory() + _footer(job))


def guard_script(job: Job) -> str:
    """Turn the runner guard on (s2amrun.exe takes SyncAppsRunner.exe's place) or off.

    Ford's runner is recognised by its size (``stock_size``, taken from SyncExtPack at
    build time; the builder refuses a guard of the same size). On: the guard first runs
    its self-test on the car. Ford's runner is kept as SyncAppsRunner.orig.exe, and a
    damaged keep (say a power cut mid-copy) is rebuilt from the live runner when that is
    still Ford's. Only then is the guard copied over SyncAppsRunner.exe, checked by size.
    Off: a good keep goes back. Neither runs while an app is open, since the runner's
    file is in use then.
    """
    action, stock = job.params.get("action"), job.params.get("stock_size")
    if action not in ("enable", "disable"):
        raise ValueError(f"invalid runner guard action {action!r}")
    if not isinstance(stock, int) or not 1024 <= stock <= 1024 * 1024:
        raise ValueError(f"invalid size of Ford's runner {stock!r}")
    runner, original = "tools & \"\\SyncAppsRunner.exe\"", "tools & \"\\SyncAppsRunner.orig.exe\""
    guard = f'{_quote(ce_path(job.job_dir))} & "\\s2amrun.exe"'
    lines = _header(job) + [
        f"tools = {_quote(TOOLS_CE)}",
        'If (ProcExists("SyncAppsRunner.exe"))',
        *_stop("busy.txt", "an app is open: restart SYNC, then prepare the stick again", "  "),
        "EndIf",
        'If (ProcExists("SyncAppsRunner.orig.exe"))',
        *_stop("busy.txt", "an app is open: restart SYNC, then prepare the stick again", "  "),
        "EndIf",
        f"If (NOT FileExists({runner}))",
        *_stop("missing.txt", "SyncAppsRunner.exe is not on the car; install the app pack first", "  "),
        "EndIf",
    ]
    if action == "enable":
        lines += [
            f'RunWait({guard}, "--s2am-selftest " & out & "\\guard-selftest.txt")',
            'If (NOT FileExists(out & "\\guard-selftest.txt"))',
            *_stop("selftest-failed.txt", "the guard did not run on this SYNC; nothing changed", "  "),
            "EndIf",
            f"If (FileExists({original}))",
            f"  If (FileSize({original}) <> {stock})",  # a damaged keep
            f"    If (FileSize({runner}) <> {stock})",
            *_stop("backup-bad.txt", "neither the runner nor its kept copy is Ford's runner; "
                   "install the app pack again", "      "),
            "    EndIf",
            f"    Delete({original})",
            "  EndIf",
            "EndIf",
            f"If (NOT FileExists({original}))",  # keep Ford's runner, once
            f"  If (FileSize({runner}) <> {stock})",
            *_stop("unknown-runner.txt", "SyncAppsRunner.exe is not the runner s2am knows; "
                   "nothing changed", "    "),
            "  EndIf",
            f"  Copy({runner}, {original}, FALSE)",
            f"  If (FileSize({original}) <> {stock})",
            f"    Delete({original})",
            *_stop("backup-failed.txt", "could not keep a copy of the original runner; nothing changed", "    "),
            "  EndIf",
            "EndIf",
            f"Copy({guard}, {runner}, TRUE)",
            f"If (FileSize({runner}) <> FileSize({guard}))",
            f"  Copy({original}, {runner}, TRUE)",
            f"  If (FileSize({runner}) <> {stock})",
            *_stop("copy-failed.txt", "the guard did not copy and the original runner could not be "
                   "put back: run the runner-guard --off stick", "    "),
            "  EndIf",
            f"  Delete({original})",
            *_stop("copy-failed.txt", "the guard did not copy; the original runner was put back", "  "),
            "EndIf",
        ]
    else:
        lines += [
            f"If (FileExists({original}))",
            f"  If (FileSize({original}) <> {stock})",
            *_stop("backup-bad.txt", "the kept runner is damaged, so the guard stays on; install "
                   "the app pack again to get Ford's runner back", "    "),
            "  EndIf",
            f"  Copy({original}, {runner}, TRUE)",
            f"  If (FileSize({runner}) <> {stock})",
            *_stop("copy-failed.txt", "could not put the original runner back; the guard stays on", "    "),
            "  EndIf",
            f"  Delete({original})",
            "Else",
            '  WriteFile(out & "\\guard-was-off.txt", "the runner guard was not on")',
            "EndIf",
        ]
    return _script(lines + _inventory() + _footer(job))


def snapshot_script(job: Job) -> str:
    """Read-only: write HKLM\\Services, HKLM\\Init and HKLM\\Drivers\\Active to registry.txt.

    ``ForEach k in regSubKeys(root, path)`` gives subkey names and
    ``ForEach n, v in regValues(root, path)`` value names and values
    (MortScript Interpreter.cpp); lines are K|key and V|key|name|value.
    """
    lines = _header(job) + ['reg = out & "\\registry.txt"', 'WriteFile(reg, "")']
    for path in ("Services", "Drivers\\Active"):
        lines += [
            f'ForEach k in regSubKeys("HKLM", {_quote(path)})',
            f'  WriteFile(reg, "K|HKLM\\{path}\\" & k & "^NL^", TRUE)',
            f'  ForEach n, v in regValues("HKLM", {_quote(path + chr(92))} & k)',
            f'    WriteFile(reg, "V|HKLM\\{path}\\" & k & "|" & n & "|" & v & "^NL^", TRUE)',
            "  EndForEach",
            "EndForEach",
        ]
    lines += [
        'WriteFile(reg, "K|HKLM\\Init^NL^", TRUE)',
        'ForEach n, v in regValues("HKLM", "Init")',
        '  WriteFile(reg, "V|HKLM\\Init|" & n & "|" & v & "^NL^", TRUE)',
        "EndForEach",
        'WriteFile(reg, "S|system|" & SystemVersion() & "^NL^", TRUE)',
    ]
    return _script(lines + _inventory() + _footer(job))


def logger_script(job: Job) -> str:
    """Start the watcher in the background, then report as usual (UpdateService waits for this).

    s2amwatch.exe records processes, windows in Z order, SYNC's DESKTOP, whether AutoKit
    answers, and the driver list, and copies the guard's and AutoKit's logs when they
    change. It replaced a MortScript loop that stopped after its first line in the car.
    With ``native`` notifylog.exe runs too: it receives AutoKit's registered _UIGEAR_*
    window messages.
    """
    seconds = job.params.get("seconds", 180)
    if not isinstance(seconds, int) or not 10 <= seconds <= 900:
        raise ValueError(f"invalid logger duration {seconds!r}")
    folder = _quote(ce_path(job.job_dir))
    lines = _header(job) + [f'Run({folder} & "\\s2amwatch.exe", "{seconds} " & out)']
    if job.params.get("native"):
        lines += [f'Run({folder} & "\\notifylog.exe", "{seconds} " & out & "\\notify.txt")']
    lines += ['WriteFile(out & "\\logger-started.txt", "leave the stick in until watch.log says end")']
    return _script(lines + _inventory() + _footer(job))


def hello_script(job: Job) -> str:
    """Prove compiled code runs on this SYNC 2: hello.exe writes the CE version and exits."""
    lines = _header(job) + [
        f'RunWait({_quote(ce_path(job.job_dir))} & "\\hello.exe", out & "\\native-hello.txt")',
    ]
    return _script(lines + _inventory() + _footer(job))


SCRIPTS = {
    "inv": inventory_script,
    "akstock": lambda job: autokit_script(job, "orig"),
    "akpatch": lambda job: autokit_script(job, "patched"),
    "rm": menu_change_script,
    "inst": menu_change_script,
    "undo": undo_script,
    "akcfg": autokit_config_script,
    "snap": snapshot_script,
    "log": logger_script,
    "hello": hello_script,
    "guard": guard_script,
}
MENU_CHANGING = ("rm", "undo", "inst")  # SYNC reads SyncApps.xml at start, so these restart it


def meta(job: Job) -> bytes:
    """The META UpdateService reads: UTF-16LE KEY=VALUE lines, as upstream packer.py writes."""
    entries = {
        "HEADER": f"s2am {job.kind} job",
        "VERSION": f"s2am {job.id} for: {job.serial}",
        "POST_APP": f"{job.job_dir}/{RUNNER_NAME}.exe",
    }
    if job.kind in MENU_CHANGING:
        entries["NEED_REBOOT"] = "True"
    return "".join(f"{k}={v}\n" for k, v in entries.items()).encode("utf-16-le")


def stage(job: Job, upstream: Path, workdir: Path, extra: dict[str, bytes] | None = None,
          payload: list[tuple[Path, str]] | None = None) -> Path:
    """Write payload/ and meta.txt for crypto_pack into a fresh ``workdir``.

    ``extra`` files go into the job folder on the car (e.g. a new SyncApps.xml).
    ``payload`` copies files or folders to car paths (an install's app files);
    UpdateService writes them before the job's script runs.
    """
    if job.kind not in SCRIPTS:
        raise ValueError(f"unknown job kind {job.kind!r}")
    script = SCRIPTS[job.kind](job).encode("ascii")  # fails before anything is written
    if workdir.exists():
        shutil.rmtree(workdir)
    target = workdir / "payload" / job.job_dir.lstrip("/")
    target.mkdir(parents=True)
    shutil.copy2(upstream / MORTSCRIPT_SOURCE, target / "MortScript.exe")
    shutil.copy2(upstream / MORTRUNNER_SOURCE, target / f"{RUNNER_NAME}.exe")
    (target / f"{RUNNER_NAME}.mscr").write_bytes(script)
    for name, data in (extra or {}).items():
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"invalid extra file name {name!r}")
        (target / name).write_bytes(data)
    for source, car_path in payload or []:
        if not car_path.startswith("/") or ".." in car_path.split("/"):
            raise ValueError(f"invalid car path {car_path!r}")
        destination = workdir / "payload" / car_path.strip("/")
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    job.files = {
        "/" + str(path.relative_to(workdir / "payload")): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(target.iterdir())
    }
    (target / "job.json").write_text(job.to_json())
    (workdir / "meta.txt").write_bytes(meta(job))
    (workdir / "job.json").write_text(job.to_json())
    return workdir
