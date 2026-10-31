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
DRIVE_SECONDS = 4 * 3600  # s2amdrive.exe and s2amwatch.exe stop by themselves after this
AUTOKIT_LOGS = ("hwlog.log", "hwlog.txt")  # AutoKit writes hwlog.log into its folder
# Litter that Macs and local tools leave in folders; never copied to the car. Real hidden files
# (Navitel keeps an empty Userdata\.tmp) still go.
LOCAL_JUNK = (".omc", ".DS_Store", "._*")
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


def _header(job: Job, on_replay: list[str] = ()) -> list[str]:
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
        *on_replay,
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

    The stock runner (SyncExtPack's, not Ford's) is recognised by its size (``stock_size``,
    taken from SyncExtPack at build time; the builder refuses a guard of the same size). On: the guard first runs
    its self-test on the car. The stock runner is kept as SyncAppsRunner.orig.exe, and a
    damaged keep (say a power cut mid-copy) is rebuilt from the live runner when that is
    still the stock one. Only then is the guard copied over SyncAppsRunner.exe, checked by size.
    Off: a good keep goes back. Neither runs while an app is open, since the runner's
    file is in use then.
    """
    action, stock = job.params.get("action"), job.params.get("stock_size")
    if action not in ("enable", "disable"):
        raise ValueError(f"invalid runner guard action {action!r}")
    if not isinstance(stock, int) or not 1024 <= stock <= 1024 * 1024:
        raise ValueError(f"invalid size of the stock runner {stock!r}")
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
            *_stop("backup-bad.txt", "neither the runner nor its kept copy is the stock runner; "
                   "install the app pack again", "      "),
            "    EndIf",
            f"    Delete({original})",
            "  EndIf",
            "EndIf",
            f"If (NOT FileExists({original}))",  # keep the stock runner, once
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
                   "the app pack again to get the stock runner back", "    "),
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
    window messages. With ``drive`` s2amdrive.exe runs next to the watcher, for up to four
    hours: system facts, processor load, a copy of Ford's screens and screenshots.
    """
    seconds = job.params.get("seconds", 180)
    longest = DRIVE_SECONDS if job.params.get("drive") else 900
    if not isinstance(seconds, int) or not 10 <= seconds <= longest:
        raise ValueError(f"invalid logger duration {seconds!r}")
    folder = _quote(ce_path(job.job_dir))
    lines = _header(job) + [f'Run({folder} & "\\s2amwatch.exe", "{seconds} " & out)']
    if job.params.get("drive"):
        lines += [f'Run({folder} & "\\s2amdrive.exe", "{seconds} " & out)']
    if job.params.get("native"):
        lines += [f'Run({folder} & "\\notifylog.exe", "{seconds} " & out & "\\notify.txt")']
    lines += ['WriteFile(out & "\\logger-started.txt", "leave the stick in until watch.log says end")']
    return _script(lines + _inventory() + _footer(job))


THEMES_CE = "\\8inchSkins\\Ford\\Sync\\Themes"  # the only folder a theme job writes to
THEME_FILES = ("Theme.XML", "yellow.bmp", "green.bmp", "red.bmp", "blue.bmp")


def _fetch(job: Job) -> list[str]:
    """Read-only copies of car files into the report (``fetched``), for study on the Mac."""
    paths = job.params.get("fetch") or []
    if len(paths) > 150:
        raise ValueError("too many files to fetch")
    lines = ['MkDir(out & "\\fetched")'] if paths else []
    for path in paths:
        if not path.startswith("\\") or path.lower().startswith("\\usb") or ".." in path:
            raise ValueError(f"invalid fetch path {path!r}")
        flat = path.strip("\\").replace("\\", "_")
        lines += [f"If (FileExists({_quote(path)}))",
                  f'  Copy({_quote(path)}, out & "\\fetched\\{flat}", TRUE)',
                  "EndIf"]
    return lines


APPS_MENU_CE = "\\8inchSkins\\Ford\\Sync\\Apps\\Info\\SyncApps"  # the Apps menu (SyncExtPack's)
# kind -> (the one folder the job writes to, the files it may replace there, what it is called)
SWAPS = {"theme": (THEMES_CE, THEME_FILES, "theme"),
         "appmenu": (APPS_MENU_CE, ("SyncApps.swf",), "Apps menu")}
ADDED = re.compile(r"Tiles\\[A-Za-z0-9_-]{1,40}\.png")  # files an Apps menu job may add
FORD_APPS_CE = "\\8inchSkins\\Ford\\Sync\\Apps"
# Ford's own screens a screen job may replace, one file each. Only screens SYNC loads when they
# are opened (never the start-up ones: the four main areas, Home and the frame).
SCREENS = ("Phone/PhoneHistory/PhoneHistory.swf",)
SWAP_KINDS = (*SWAPS, "screen")


def swap_target(kind: str, params: dict) -> tuple[str, tuple[str, ...], str]:
    """(the one folder a swap job writes to, the files it may replace there, what it is called)."""
    if kind == "screen":
        screen = params.get("screen")
        if screen not in SCREENS:
            raise ValueError(f"not a screen s2am may change: {screen!r}")
        folder, name = screen.rsplit("/", 1)
        return f"{FORD_APPS_CE}\\{folder.replace('/', chr(92))}", (name,), "screen"
    return SWAPS[kind]


def _flat(relative: str) -> str:
    return relative.replace("\\", "_")


def swap_script(job: Job) -> str:
    """Replace a few of SYNC's files (or put a swap job's originals back); SYNC restarts.
    The steps are swap_lines; a bundle runs the same steps for each of its parts."""
    return _script(_header(job) + swap_lines(job) + _fetch(job) + _inventory() + _footer(job))


def swap_lines(job: Job) -> list[str]:
    """A swap job's own steps, between the script's header and the inventory.

    Theme jobs swap the five files in THEMES_CE, Apps menu jobs SyncApps.swf in APPS_MENU_CE and
    add tile pictures under it, screen jobs one of Ford's screens listed in SCREENS. The job
    first checks that the car still has the files the Mac planned against (Theme.XML by content,
    the rest by size), backs them up on the car and copies that backup onto the stick, copies
    the new ones in and checks their sizes, copying the backup back if one did not copy whole.
    What it applied goes back to the stick, so the Mac can compare every byte after import. The
    restore carries the originals itself.
    """
    p = job.params
    folder, allowed, what = swap_target(job.kind, p)
    files, added = p.get("files") or {}, p.get("added") or {}
    if not files or any(name not in allowed for name in files):
        raise ValueError(f"invalid {what} files {sorted(files)!r}")
    if any(not ADDED.fullmatch(name) for name in added) or (added and job.kind != "appmenu"):
        raise ValueError(f"invalid added files {sorted(added)!r}")
    lines = [
        f"th = {_quote(folder)}",
        f"jd = {_quote(ce_path(job.job_dir))}",
        "If (NOT DirExists(th))",
        *_stop("missing.txt", f"the car has no {what} folder; nothing changed", "  "),
        "EndIf",
    ]
    if p.get("restore"):
        if not JOB_ID.fullmatch(p["restore"]) or added:
            raise ValueError(f"invalid restore target {p['restore']!r}")
        # The originals travel in the job folder (checked against the job's record on the Mac),
        # so the undo works even if the car's own backup is gone or damaged.
        for name, size in files.items():
            lines += [f'If (FileSize(jd & "\\orig-{name}") <> {_length(size)})',
                      *_stop("payload-bad.txt", f"the job's original {what} files are incomplete; nothing changed",
                             "  "),
                      "EndIf"]
        lines += [f'Copy(jd & "\\orig-{name}", th & "\\{name}", TRUE)' for name in files]
        lines.append("ok = 1")
        for name, size in files.items():
            lines += [f'If (FileSize(th & "\\{name}") <> {size})', "  ok = 0", "EndIf"]
        lines += ["If (ok = 0)",
                  *_stop("copy-failed.txt", "a file did not copy back whole; run the restore stick again",
                         "  "),
                  "EndIf"]
        done = f"{job.kind}-restored.txt"
    else:
        if "Theme.XML" in files:
            lines += ['If (ReadFile(th & "\\Theme.XML") ne ReadFile(jd & "\\old-Theme.XML"))',
                      *_stop("stale.txt", "the car's theme is not the one the Mac planned against; nothing changed",
                             "  "),
                      "EndIf"]
        for name, f in files.items():
            lines += [f'If (FileSize(th & "\\{name}") <> {_length(f["old"])})',
                      *_stop("stale.txt", f"{name} is not the one the Mac planned against; nothing changed",
                             "  "),
                      "EndIf",
                      f'If (FileSize(jd & "\\new-{name}") <> {_length(f["new"])})',
                      *_stop("payload-bad.txt", f"the job's {what} files are incomplete; nothing changed", "  "),
                      "EndIf"]
        for name, f in added.items():
            lines += [f'If (FileSize(jd & "\\add-{_flat(name)}") <> {_length(f["new"])})',
                      *_stop("payload-bad.txt", f"the job's {what} files are incomplete; nothing changed", "  "),
                      "EndIf"]
        lines += ['MkDir("\\SyncExtendedPack\\_s2am")',
                  f"MkDir({_quote(BACKUP_DIR)})",
                  f"bk = {_quote(BACKUP_DIR + chr(92) + job.id)}",
                  "If (DirExists(bk))",  # a run that was cut short: its backup may hold a mixed state
                  *_stop("stale.txt", "this job started once before; use its restore stick; nothing changed", "  "),
                  "EndIf",
                  "MkDir(bk)",
                  'MkDir(out & "\\backup")']
        for name in files:  # the stick gets the car's backup, so the Mac checks what a restore would use
            lines += [f'Copy(th & "\\{name}", bk & "\\{name}", TRUE)',
                      f'Copy(bk & "\\{name}", out & "\\backup\\{name}", TRUE)']
        for name, f in files.items():  # both copies whole, the car's and the stick's, before any change
            for copy in (f'bk & "\\{name}"', f'out & "\\backup\\{name}"'):
                lines += [f'If (FileSize({copy}) <> {f["old"]})',
                          *_stop("backup-failed.txt", f"could not back up the {what}; nothing changed", "  "),
                          "EndIf"]
        for sub in sorted({name.rsplit("\\", 1)[0] for name in added}):
            lines.append(f'MkDir(th & "\\{sub}")')
        lines += [f'Copy(jd & "\\add-{_flat(name)}", th & "\\{name}", TRUE)' for name in added]
        lines += [f'Copy(jd & "\\new-{name}", th & "\\{name}", TRUE)' for name in files]
        lines.append("ok = 1")
        for name, f in [*files.items(), *added.items()]:
            lines += [f'If (FileSize(th & "\\{name}") <> {f["new"]})', "  ok = 0", "EndIf"]
        lines += ["If (ok = 0)",
                  *[f'  Copy(bk & "\\{name}", th & "\\{name}", TRUE)' for name in files],
                  *_stop("copy-failed.txt", f"a new {what} file did not copy whole; the backup was copied back, "
                         "but run the restore stick to be sure",
                         "  "),
                  "EndIf"]
        done = f"{job.kind}-applied.txt"
    lines += ['MkDir(out & "\\applied")',
              *[f'Copy(th & "\\{name}", out & "\\applied\\{name}", TRUE)' for name in files],
              *[f'Copy(th & "\\{name}", out & "\\applied\\{_flat(name)}", TRUE)' for name in added],
              f'WriteFile(out & "\\{done}", {_quote(job.id)})']
    return lines


theme_script = swap_script


def cleanup_script(job: Job) -> str:
    return _script(_header(job) + cleanup_lines(job) + _inventory() + _footer(job))


def cleanup_lines(job: Job, home: str | None = None) -> list[str]:
    """Remove s2am's own finished job folders (\\SyncExtendedPack\\_s2am\\jobs\\<id>).

    Every job leaves its folder behind (MortScript and the runner, about 0.17 MB). This job
    first marks its own folder, then deletes every other folder under jobs: only s2am's
    folder is touched; backups, done markers and everything else stay. cleanup.txt lists each
    folder and whether it is gone.
    """
    jobs = ce_path(JOBS_DIR)
    keep = f"keep-{job.id}"
    lines = [
        f"jd = {_quote(ce_path(home or job.job_dir))}",  # in a bundle: the bundle's folder, where it runs
        f'WriteFile(jd & "\\{keep}", {_quote(job.id)})',
        'cl = out & "\\cleanup.txt"',
        'WriteFile(cl, "")',
        f"ForEach d in directories({_quote(jobs + chr(92) + '*')})",
        f'  If (FileExists(d & "\\{keep}"))',
        '    WriteFile(cl, "K|" & d & "^NL^", TRUE)',
        "  Else",
        "    DelTree(d)",
        "    RmDir(d)",
        "    If (DirExists(d))",
        '      WriteFile(cl, "S|" & d & "^NL^", TRUE)',
        "    Else",
        '      WriteFile(cl, "D|" & d & "^NL^", TRUE)',
        "    EndIf",
        "  EndIf",
        "EndForEach",
    ]
    return lines


BUNDLE_PARTS = (*SWAP_KINDS, "clean")  # jobs a bundle may run; a cleanup only last
BUNDLE_LIMIT = 8


def bundle_parts(job: Job) -> list[Job]:
    """A bundle's parts as jobs of their own, checked like any job read back from a stick."""
    parts = job.params.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= BUNDLE_LIMIT:
        raise ValueError("a bundle holds 1 to 8 parts")
    jobs = [validate(Job(job.serial, p["kind"], id=p["id"], created_utc=p["created_utc"], params=p["params"]))
            for p in parts]
    if any(part.kind not in BUNDLE_PARTS for part in jobs):
        raise ValueError(f"a bundle runs only {', '.join(BUNDLE_PARTS)} jobs")
    if len({part.id for part in jobs}) != len(jobs):
        raise ValueError("a part appears twice")
    if any(part.kind == "clean" for part in jobs[:-1]):
        raise ValueError("a cleanup can only be the last part")
    return jobs


def bundle_script(job: Job) -> str:
    """Several prepared jobs in one run, in order, each with its own steps, report folder and
    done marker, as if it had run alone, so the Mac verifies each part on import. Each part
    is first marked queued; the first part that stops ends the run (its own Exit), so a later
    part never meets a car it was not planned against, and parts that did not run say so."""
    parts = bundle_parts(job)
    reports = 'stick & "\\s2am\\reports\\'
    replayed = []  # the whole bundle ran before: so did each part
    for part in parts:
        replayed += [f'  MkDir({reports}{part.id}")',
                     f'  WriteFile({reports}{part.id}\\replayed.txt", {_quote(part.id)})']
    lines = _header(job, replayed) + ["bout = out"]
    for part in parts:
        lines += [f'MkDir({reports}{part.id}")',
                  f'WriteFile({reports}{part.id}\\queued.txt", {_quote(job.id)})']
    for part in parts:
        steps = (swap_lines(part) + _fetch(part)) if part.kind in SWAP_KINDS \
            else cleanup_lines(part, home=job.job_dir)
        lines += [f'WriteFile(bout & "\\part.txt", {_quote(part.id)})',
                  f'out = {reports}{part.id}"',
                  f"If (FileExists({_quote(ce_path(part.done_marker))}))",
                  f'  WriteFile(out & "\\replayed.txt", {_quote(part.id)})',
                  "Else",
                  f'  WriteFile(out & "\\started.txt", {_quote(job.id)})',  # a cut from here on: interrupted
                  *[f"  {line}" for line in steps],
                  '  MkDir("\\SyncExtendedPack\\_s2am")',
                  f"  MkDir({_quote(ce_path(DONE_DIR))})",
                  f"  WriteFile({_quote(ce_path(part.done_marker))}, {_quote(part.id)})",
                  f'  WriteFile(out & "\\done.txt", {_quote(part.id + " applied")})',
                  "EndIf"]
    return _script(lines + ["out = bout"] + _inventory() + _footer(job))


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
    "theme": swap_script,
    "appmenu": swap_script,
    "screen": swap_script,
    "clean": cleanup_script,
    "bundle": bundle_script,
}
MENU_CHANGING = ("rm", "undo", "inst")  # SYNC reads SyncApps.xml at start, so these restart it
RESTARTING = MENU_CHANGING + SWAP_KINDS + ("bundle",)  # and its theme, Apps menu and screens


def meta(job: Job) -> bytes:
    """The META UpdateService reads: UTF-16LE KEY=VALUE lines, as upstream packer.py writes."""
    entries = {
        "HEADER": f"s2am {job.kind} job",
        "VERSION": f"s2am {job.id} for: {job.serial}",
        "POST_APP": f"{job.job_dir}/{RUNNER_NAME}.exe",
    }
    if job.kind in RESTARTING:
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
            shutil.copytree(source, destination, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*LOCAL_JUNK))
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
