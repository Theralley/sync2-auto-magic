"""Is this USB stick fit for SYNC 2? FAT32, MBR, 32 GB or less, external, nothing left to run.

On macOS the volume facts come from `diskutil info -plist`; tests inject their own.
"""
from __future__ import annotations

import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAX_BYTES = 32 * 1024 ** 3  # SyncExtPack: "maximum 32GB"
MIN_FREE = 200 * 10 ** 6    # the bootstrap pack is about 25 MB; leave room for reports
MBR = "FDisk_partition_scheme"
UPDATER_BAIT = ("install.bin", "Installer.jpg", "update.bin", "pack_install.bin")
FIRMWARE_AUTORUN = ("autoinstall.lst", "SyncMyRide")  # FIRMWARE_INSTALLATION.md layout

DiskInfo = Callable[[str], dict]


def diskutil_info(target: str) -> dict:
    return plistlib.loads(subprocess.run(["diskutil", "info", "-plist", target],
                                         check=True, capture_output=True).stdout)


@dataclass
class Finding:
    level: str  # "ok", "warn" or "fail"
    message: str


def check(stick: Path, info: DiskInfo | None = diskutil_info) -> list[Finding]:
    """Findings for the stick; ``info=None`` skips the disk-level checks."""
    findings: list[Finding] = []
    if info is not None:
        try:
            volume = info(str(stick))
        except (subprocess.CalledProcessError, OSError, plistlib.InvalidFileException) as error:
            return [Finding("fail", f"diskutil could not read {stick}: {error}")]
        name = volume.get("FilesystemName", volume.get("FilesystemType", "?"))
        findings.append(Finding("ok" if name == "MS-DOS FAT32" else "fail",
                                f"file system: {name} (needs MS-DOS FAT32)"))
        size = int(volume.get("TotalSize", 0))
        findings.append(Finding("ok" if 0 < size <= MAX_BYTES else "fail",
                                f"size: {size / 1e9:.1f} GB (needs 32 GB or less)"))
        external = not volume.get("Internal", True) and volume.get("Ejectable", volume.get(
            "RemovableMediaOrExternalDevice", False))
        findings.append(Finding("ok" if external else "fail",
                                f"external removable disk: {'yes' if external else 'no'} "
                                f"({volume.get('BusProtocol', '?')})"))
        whole = volume.get("ParentWholeDisk")
        scheme = info(whole).get("Content", "?") if whole and whole != volume.get(
            "DeviceIdentifier") else "none (no partition table)"
        findings.append(Finding("ok" if scheme == MBR else "fail",
                                f"partition scheme: {scheme} (needs MBR / {MBR})"))
        writable = volume.get("WritableVolume", volume.get("Writable", True))
        findings.append(Finding("ok" if writable else "fail",
                                f"writable: {'yes' if writable else 'no'}"))
        free = int(volume.get("FreeSpace", 0) or 0)
        findings.append(Finding("ok" if free >= MIN_FREE else "warn",
                                f"free space: {free / 1e6:.0f} MB (packs need up to {MIN_FREE // 10**6} MB)"))
        if volume.get("BusProtocol") not in (None, "USB"):
            findings.append(Finding("warn", f"bus is {volume.get('BusProtocol')}, not USB"))

    # Ford's own updater runs these as soon as a stick goes in.
    firmware = [n for n in FIRMWARE_AUTORUN if (stick / n).exists()]
    if firmware:
        findings.append(Finding("fail", f"firmware update files on the stick ({', '.join(firmware)}): "
                                        "SYNC would start a firmware update"))
    root_links = [p.name for p in stick.iterdir() if p.is_symlink()] if stick.is_dir() else []
    if root_links:
        findings.append(Finding("fail", f"symlinks at the top of the stick: {root_links}"))

    updater = stick / "SyncExtPack"
    leftovers = [n for n in UPDATER_BAIT if (updater / n).exists()]
    if (updater / "install.bin").exists():
        findings.append(Finding("warn", "SyncExtPack/install.bin is present: a car with "
                                        "SyncExtPack installs it as soon as the stick goes in"))
    elif leftovers:
        findings.append(Finding("warn", f"SyncExtPack/ already holds {', '.join(leftovers)}"))
    else:
        findings.append(Finding("ok", "no SyncExtPack files waiting to run"))
    links = [p for p in (updater, stick / "s2am") if p.is_symlink()]
    if links:
        findings.append(Finding("fail", f"symlinked folders on the stick: {links}"))
    return findings


def failed(findings: list[Finding]) -> bool:
    return any(f.level == "fail" for f in findings)
