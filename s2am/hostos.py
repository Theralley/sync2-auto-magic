"""What differs between the computers s2am runs on: where a USB stick is mounted, what kind of
disk it is, and how to eject and remount it.

macOS is the tested system. Linux is new (issue #5): the answers come from ``lsblk``, ``findmnt``
and ``udisksctl``, which need no root. Windows is newer still (issue #6): a stick is a drive letter,
the answers come from PowerShell's ``Get-Volume``, ``Get-Partition`` and ``Get-Disk``, which need no
administrator rights, and eject is Explorer's own. The disk facts are given in the shape
``diskutil info`` uses, so ``diskcheck.check`` reads all three the same way.
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import time
from pathlib import Path, PureWindowsPath
from typing import Callable

SYSTEM = platform.system()  # "Darwin", "Linux" or "Windows"
MBR = "FDisk_partition_scheme"
LSBLK_COLUMNS = "NAME,PATH,PKNAME,TYPE,FSTYPE,FSVER,SIZE,RM,HOTPLUG,TRAN,RO,PTTYPE,MOUNTPOINT"
LINUX_TOOLS = ("lsblk", "findmnt", "udisksctl")
TOO_OLD = ("this computer's lsblk is too old to tell FAT32 from other FAT versions: s2am needs util-linux "
           "2.35 or newer (Ubuntu 22.04, Debian 11, Fedora 32 or later)")
GPT = "GUID_partition_scheme"
DRIVE = re.compile(r"([A-Za-z]):[\\/]")  # a drive's top folder: E:\ or E:/ (a bare E: is E's current folder)
# PowerShell prints enum names; these are the numbers, should an older one print those instead.
WINDOWS_BUS = {"7": "USB"}
WINDOWS_STYLES = {"0": "RAW", "1": "MBR", "2": "GPT"}

Run = Callable[[list], subprocess.CompletedProcess]


class HostError(Exception):
    pass


def _run(command: list) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _unsupported() -> HostError:
    return HostError(f"{SYSTEM or 'this system'} is not supported: s2am runs on macOS, Linux and Windows")


def _powershell(script: str, run: Run) -> subprocess.CompletedProcess:
    """Windows PowerShell 5.1, which every Windows 10 and 11 has. Its answer comes back as UTF-8."""
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference = 'Stop'\n"
                "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n" + script])


def _letter(stick) -> str:
    """The drive letter of a drive's top folder, or HostError."""
    found = DRIVE.fullmatch(str(stick))
    if not found:
        raise HostError(f"{stick} is not a drive's top folder such as E:\\")
    return found.group(1).upper()


# ---- where sticks are -------------------------------------------------------------------------

def volume_roots(system: str = SYSTEM, user: str | None = None) -> list[Path]:
    """The folders removable volumes are mounted in. Windows has none: each volume is a drive."""
    if system == "Darwin":
        return [Path("/Volumes")]
    if system == "Linux":
        user = user or getpass.getuser()
        return [Path("/media") / user, Path("/run/media") / user]
    if system == "Windows":
        return []
    raise _unsupported()


WINDOWS_VOLUMES = """@(Get-Volume | Where-Object { $_.DriveLetter -and [string]$_.DriveType -ne 'CD-ROM' } |
  ForEach-Object { [string]$_.DriveLetter }) -join ','"""


def volumes(system: str = SYSTEM, run: Run = _run) -> list[Path]:
    """Every mounted volume that could be a stick; the stick checks sort out which ones are."""
    if system == "Windows":
        result = _powershell(WINDOWS_VOLUMES, run)
        if result.returncode:
            raise HostError(f"Windows could not list its drives: {result.stderr.strip()}")
        letters = [part.strip() for part in result.stdout.lstrip("\ufeff").strip().split(",")]
        return [Path(f"{letter}:\\") for letter in letters if len(letter) == 1 and letter.isalpha()]
    return sorted(volume for root in volume_roots(system) if root.is_dir() for volume in root.iterdir())


def stick_hint(system: str = SYSTEM) -> str:
    """How a stick's path looks, for messages."""
    return {"Darwin": "/Volumes/<STICK>", "Windows": "E:\\"}.get(system, "/media/<you>/<STICK>")


def places(system: str = SYSTEM) -> str:
    """Where sticks are, in words, for messages."""
    if system == "Windows":
        return "a drive's top folder such as E:\\"
    return "a folder under " + " or ".join(str(root) for root in volume_roots(system))


def is_volume(stick: Path, system: str = SYSTEM, user: str | None = None) -> bool:
    """Is ``stick`` the top folder of a removable volume, not a folder somewhere inside one?"""
    if system == "Windows":  # as typed: a bare E: would become E's current folder, wherever that is
        return DRIVE.fullmatch(str(stick)) is not None
    parent = stick.resolve().parent
    return any(parent == root for root in volume_roots(system, user))


def volume_id(stick: Path, system: str | None = None) -> str | None:
    """Windows: the volume's serial number, set when it was formatted. A drive letter can go to
    another drive while the stick is in the car; this tells the stick when it comes back. None
    elsewhere, and when the drive cannot be read (a stick keeps its name on macOS and Linux)."""
    if (system or SYSTEM) != "Windows":
        return None
    import ctypes
    windll = getattr(ctypes, "windll", None)  # only Windows' Python has it
    serial = ctypes.c_uint32()
    if windll is None or not windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(str(stick)), None, 0, ctypes.byref(serial), None, None, None, 0):
        return None
    return f"{serial.value:08X}"


def python_command(system: str = SYSTEM) -> str:
    """How the user starts Python 3 here, for commands shown to them."""
    return "py -3" if system == "Windows" else "python3"


def display(stick: Path, system: str | None = None) -> str:
    """A stick's name for the user: SYNC on macOS and Linux, E: on Windows."""
    if (system or SYSTEM) == "Windows":
        return PureWindowsPath(str(stick)).drive or str(stick)
    return stick.name or str(stick)


# ---- what kind of disk ------------------------------------------------------------------------

def _mac_info(target: str) -> dict:
    return plistlib.loads(subprocess.run(["diskutil", "info", "-plist", target],
                                         check=True, capture_output=True).stdout)


def _true(value) -> bool:  # lsblk prints true/false, or "1"/"0" in older versions
    return value is True or value in ("1", 1)


def _lsblk_rows(arguments: list, device: str, run: Run) -> list:
    result = run(["lsblk", "--json", *arguments, device])
    if result.returncode:
        if "unknown column" in result.stderr.lower():
            raise HostError(TOO_OLD)
        raise HostError(f"lsblk could not read {device}: {result.stderr.strip()}")
    try:
        rows = json.loads(result.stdout)["blockdevices"]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TypeError("not a list of devices")
    except (ValueError, KeyError, TypeError) as error:
        raise HostError(f"lsblk gave no usable answer for {device}: {error}") from error
    return rows


def _lsblk(device: str, run: Run) -> dict:
    rows = _lsblk_rows(["--bytes", "--nodeps", "-o", LSBLK_COLUMNS], device, run)
    if len(rows) != 1:
        raise HostError(f"lsblk listed {len(rows)} devices for {device}, not one")
    return rows[0]


def _all_mounts(run: Run) -> list[dict]:
    """Every mount on this computer, each one on its own: lsblk's MOUNTPOINT shows only one per
    device, so a partition mounted at /boot/efi and again under /media would look like a stick."""
    result = run(["findmnt", "--json", "--list", "--output", "SOURCE,TARGET,MAJ:MIN"])
    try:
        rows = json.loads(result.stdout)["filesystems"] if result.returncode == 0 else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TypeError("not a list of mounts")
    except (ValueError, KeyError, TypeError) as error:
        raise HostError(f"findmnt could not list the mounts: {result.stderr.strip() or error}") from error
    return rows


def _system_mounts(whole: str, run: Run, user: str | None) -> list[str]:
    """What on the whole disk is not a stick's volume: swap, or a mount outside the folders sticks
    are mounted in (/, /boot, /home, a file system on LVM or encryption on that disk...)."""
    rows = _lsblk_rows(["--list", "-o", "NAME,PATH,MAJ:MIN,MOUNTPOINT"], f"/dev/{whole}", run)
    paths = {row.get("path") for row in rows if row.get("path")}
    numbers = {row.get("maj:min") for row in rows if row.get("maj:min")}
    found = {"[SWAP]" for row in rows if row.get("mountpoint") == "[SWAP]"}
    roots = volume_roots("Linux", user)
    for mount in _all_mounts(run):
        source = (mount.get("source") or "").split("[", 1)[0]  # a bind mount reads /dev/sdb1[/folder]
        if source not in paths and mount.get("maj:min") not in numbers:
            continue
        target = mount.get("target") or "?"
        if not any(Path(target).parent == root for root in roots):
            found.add(target)
    return sorted(found)


def _linux_info(target: str, run: Run = _run, free: Callable[[str], int] | None = None,
                access: Callable[[str], bool] = lambda path: os.access(path, os.W_OK),
                user: str | None = None) -> dict:
    """``target`` is a mounted folder, or the name of a whole disk as ``ParentWholeDisk`` gave it.

    Only a disk on the USB bus that holds nothing of the running system counts as external: a
    hot-pluggable SATA or NVMe disk, or a USB disk with swap or / on it, is never taken for a stick."""
    if not target.startswith("/"):  # a whole disk, asked for its partition table
        disk = _lsblk(f"/dev/{target}", run)
        return {"DeviceIdentifier": disk.get("name"),
                "Content": MBR if disk.get("pttype") == "dos" else disk.get("pttype") or "none (no partition table)"}
    found = run(["findmnt", "--noheadings", "--output", "SOURCE", "--mountpoint", target])
    device = found.stdout.strip()
    if found.returncode or not device.startswith("/dev/"):
        raise HostError(f"{target} is not where a disk is mounted")
    part = _lsblk(device, run)
    whole = part.get("pkname")
    disk = _lsblk(f"/dev/{whole}", run) if whole else part
    bus = (disk.get("tran") or "?").upper()
    system = _system_mounts(disk.get("name") or part.get("name"), run, user)
    external = bus == "USB" and not system
    kind, version = part.get("fstype") or "?", part.get("fsver") or ""
    if free is None:
        def free(path: str) -> int:
            stats = os.statvfs(path)
            return stats.f_bavail * stats.f_frsize
    return {
        "DeviceIdentifier": part.get("name"),
        "DeviceNode": device,
        "ParentWholeDisk": whole,
        "FilesystemName": "MS-DOS FAT32" if (kind, version) == ("vfat", "FAT32") else f"{kind} {version}".strip(),
        "TotalSize": int(part.get("size") or 0),
        "Internal": not external,
        "Ejectable": external,
        "BusProtocol": bus,
        "SystemMounts": system,
        "WritableVolume": not _true(part.get("ro")) and access(target),
        "FreeSpace": free(target),
    }


WINDOWS_FACTS = """$volume = Get-Volume -DriveLetter @L@
$partition = Get-Partition -DriveLetter @L@
$disk = Get-Disk -Number $partition.DiskNumber
[ordered]@{ FileSystem = [string]$volume.FileSystem; FileSystemType = [string]$volume.FileSystemType;
  Size = [uint64]$volume.Size; SizeRemaining = [uint64]$volume.SizeRemaining; DiskNumber = [int]$disk.Number;
  BusType = [string]$disk.BusType; PartitionStyle = [string]$disk.PartitionStyle; IsBoot = [bool]$disk.IsBoot;
  IsSystem = [bool]$disk.IsSystem; IsReadOnly = [bool]$disk.IsReadOnly } | ConvertTo-Json -Compress"""


def _windows_info(target: str, run: Run = _run,
                  access: Callable[[str], bool] = lambda path: os.access(path, os.W_OK)) -> dict:
    """``target`` is a drive's top folder. Only a disk on the USB bus that is not the one Windows
    starts from counts as external. The partition table comes along (WholeDiskContent)."""
    letter = _letter(target)
    result = _powershell(WINDOWS_FACTS.replace("@L@", letter), run)
    try:
        if result.returncode:
            raise ValueError(result.stderr.strip().splitlines()[0] if result.stderr.strip() else "no answer")
        facts = json.loads(result.stdout.lstrip("\ufeff"))
        if not isinstance(facts, dict):
            raise ValueError("not a set of facts")
    except ValueError as error:  # json.JSONDecodeError is a ValueError
        raise HostError(f"Windows could not read the disk behind {letter}: ({error})") from error
    bus = str(facts.get("BusType") or "?")
    bus = WINDOWS_BUS.get(bus, bus).upper()
    style = str(facts.get("PartitionStyle") or "?")
    style = WINDOWS_STYLES.get(style, style).upper()
    system = [what for flag, what in (("IsBoot", "Windows itself"), ("IsSystem", "Windows' system partition"))
              if facts.get(flag) is True]
    external = bus == "USB" and not system
    kind = str(facts.get("FileSystem") or facts.get("FileSystemType") or "?")
    return {
        "DeviceIdentifier": f"{letter}:",
        "ParentWholeDisk": f"PhysicalDrive{facts.get('DiskNumber', '?')}",
        "WholeDiskContent": {"MBR": MBR, "GPT": GPT, "RAW": "none (no partition table)"}.get(style, style),
        "FilesystemName": "MS-DOS FAT32" if kind.upper() == "FAT32" else kind,
        "TotalSize": int(facts.get("Size") or 0),
        "Internal": not external,
        "Ejectable": external,
        "BusProtocol": bus,
        "SystemMounts": system,
        "WritableVolume": facts.get("IsReadOnly") is False and access(f"{letter}:\\"),
        "FreeSpace": int(facts.get("SizeRemaining") or 0),
    }


def disk_info(target: str) -> dict:
    """The facts ``diskcheck.check`` needs about a mounted stick (or a whole disk, by name)."""
    if SYSTEM == "Darwin":
        return _mac_info(target)
    if SYSTEM == "Linux":
        return _linux_info(target)
    if SYSTEM == "Windows":
        return _windows_info(target)
    raise _unsupported()


# ---- eject and remount ------------------------------------------------------------------------

def _linux_devices(stick: Path, run: Run) -> tuple[str, str]:
    """The stick's partition and its whole disk (the same device when it has no partition table)."""
    info = _linux_info(str(stick), run, free=lambda path: 0, access=lambda path: True)
    if info["SystemMounts"]:  # never unmount or power off a disk the computer itself uses
        raise HostError(f"the disk behind {stick} also holds {', '.join(info['SystemMounts'])}")
    if info["Internal"]:  # nor one that is not on the USB bus
        raise HostError(f"the disk behind {stick} is not a USB disk ({info['BusProtocol']})")
    return info["DeviceNode"], f"/dev/{info['ParentWholeDisk']}" if info["ParentWholeDisk"] else info["DeviceNode"]


# Explorer's own Eject (what "Eject" in This PC does), then wait until the drive is gone: only then
# is the stick safe to pull. Explorer itself says so if something on it is still open.
WINDOWS_EJECT = """$drive = (New-Object -ComObject Shell.Application).Namespace(17).ParseName('@L@:')
if ($null -eq $drive) { [Console]::Error.WriteLine('@L@: is not listed under This PC'); exit 2 }
$drive.InvokeVerb('Eject')
for ($i = 0; $i -lt 30; $i++) {
  if (-not (Test-Path -LiteralPath '@L@:\\')) { exit 0 }
  Start-Sleep -Milliseconds 500
}
[Console]::Error.WriteLine('@L@: is still there after 15 seconds'); exit 1"""


def eject(stick: Path, system: str = SYSTEM, run: Run = _run) -> tuple[bool, str]:
    """Make the stick safe to pull. (worked, what to tell the user if it did not)."""
    if system == "Darwin":
        result = run(["diskutil", "eject", str(stick)])
        return result.returncode == 0, f"eject it in Finder before pulling it: {result.stderr.strip()}"
    if system == "Linux":
        try:
            device, whole = _linux_devices(stick, run)
        except HostError as error:
            return False, f"unmount it in your file manager before pulling it: {error}"
        result = run(["udisksctl", "unmount", "--block-device", device])
        if result.returncode:
            return False, f"unmount it in your file manager before pulling it: {result.stderr.strip()}"
        # Only this volume was unmounted. UDisks refuses to power off a disk while anything else on
        # it is still mounted, and then the stick is not safe to pull: say so, touch nothing else.
        result = run(["udisksctl", "power-off", "--block-device", whole])
        if result.returncode:
            return False, (f"{stick.name} is unmounted, but the stick could not be switched off "
                           f"({result.stderr.strip()}). Something else on it may still be open: eject the "
                           "stick in your file manager and wait until it says it is safe before pulling it")
        return True, ""
    if system == "Windows":
        advice = "eject it with Safely Remove Hardware (the USB icon by the clock) before pulling it"
        try:
            info = _windows_info(str(stick), run, access=lambda path: True)
        except HostError as error:
            return False, f"{advice}: {error}"
        if info["SystemMounts"]:  # never eject the disk Windows runs from
            return False, f"{advice}: the disk behind {stick} also holds {', '.join(info['SystemMounts'])}"
        if info["Internal"]:  # nor one that is not on the USB bus
            return False, f"{advice}: the disk behind {stick} is not a USB disk ({info['BusProtocol']})"
        result = _powershell(WINDOWS_EJECT.replace("@L@", info["DeviceIdentifier"][0]), run)
        if result.returncode:
            return False, f"{advice}: {result.stderr.strip() or 'Windows did not eject it'}"
        return True, ""
    raise _unsupported()


def remount(stick: Path, system: str = SYSTEM, run: Run = _run, wait: Callable[[float], None] = time.sleep) -> bool:
    """Unmount the stick and mount it again, so it is read from the stick and not from a cache."""
    if system == "Darwin":
        info = run(["diskutil", "info", str(stick)]).stdout
        device = next((line.split(":", 1)[1].strip() for line in info.splitlines()
                       if line.strip().startswith("Device Identifier:")), None)
        if not device:
            return False
        for _ in range(5):  # Spotlight may hold it for a moment
            if run(["diskutil", "unmount", str(stick)]).returncode == 0:
                break
            wait(2)
        else:
            return False
        return run(["diskutil", "mount", device]).returncode == 0 and stick.is_dir()
    if system == "Linux":
        try:
            device, _ = _linux_devices(stick, run)
        except HostError:
            return False
        for _ in range(5):  # a file manager's indexer may hold it for a moment
            if run(["udisksctl", "unmount", "--block-device", device]).returncode == 0:
                break
            wait(2)
        else:
            return False
        if run(["udisksctl", "mount", "--block-device", device]).returncode:
            return False
        back = run(["findmnt", "--noheadings", "--output", "TARGET", "--source", device]).stdout.strip()
        return back == str(stick) and stick.is_dir()  # the same place, or the caller would read elsewhere
    if system == "Windows":
        return False  # Windows remounts a volume only for an administrator (see REMOUNT_NOTE)
    raise _unsupported()


REMOUNT_NOTE = {"Windows": "read through Windows' file cache: remounting the stick needs administrator rights"}


def linux_problems(run: Run = _run, which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """What keeps s2am from reading sticks on this Linux computer, in words for the user."""
    missing = [tool for tool in LINUX_TOOLS if not which(tool)]
    if missing:
        return [f"missing: {', '.join(missing)} (lsblk and findmnt are in util-linux, udisksctl in udisks2)"]
    result = run(["lsblk", "--nodeps", "--noheadings", "-o", "FSVER"])
    if result.returncode:
        return [TOO_OLD if "unknown column" in result.stderr.lower()
                else f"lsblk does not work here: {result.stderr.strip()}"]
    return []


def format_steps(system: str = SYSTEM) -> list[str]:
    """How to make a stick FAT32 with an MBR table, in the user's own tools. s2am never formats."""
    if system == "Darwin":
        return ["Open Disk Utility, choose View > Show All Devices, select the stick itself "
                "(the top line, not the volume).",
                "Click Erase: Name SYNC, Format MS-DOS (FAT), Scheme Master Boot Record."]
    if system == "Windows":
        return ["Open This PC, right-click the stick and choose Format: File system FAT32, Volume label "
                "SYNC, Quick Format, then Start.",
                "If the check then says the partition scheme is not MBR, the stick needs diskpart: see "
                "\"On Windows\" in docs/INSTALL.md."]
    return ["Open Disks (GNOME Disks) and select the stick itself in the list on the left.",
            "Menu (three dots) > Format Disk: Partitioning \"Compatible with all systems and devices "
            "(MBR / DOS)\".",
            "Then + to add a partition over all of it: Name SYNC, type \"For use with all systems and "
            "devices (FAT)\".",
            "Open the stick once in your file manager, so it is mounted."]
