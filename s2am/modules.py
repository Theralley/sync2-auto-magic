"""Validate a fixed, bounded ordinary-file capture; ROM metadata is not a binary."""
from pathlib import Path
import re
import stat
import zlib

FILES = ("cspddk.dll", "autopmdrv.dll", "pmicPdk_mc13892.dll", "pmicSdk_mc13892.dll",
         "dvfc_mc13892.dll", "nk.exe", "kernel.dll", "coredll.dll")
FILE_LIMIT = 4 * 1024 * 1024
STATUSES = {"copied", "rom-module", "directory", "too-large", "attrs-error", "open-error",
            "read-error", "create-error", "write-error", "flush-error", "close-error",
            "changed", "error-budget"}


def summary(report: Path) -> str:
    """Only count a copied file after its length and native CRC match the imported bytes."""
    incomplete = "NOT complete: module report may be partial; see modules.txt"
    invalid = "NOT verified: module report or copied-file integrity mismatch"
    try:
        with (report / "modules-done.txt").open("rb") as stream:
            marker = stream.read(129)
        if len(marker) > 128 or marker.strip() != b"T|complete":
            return incomplete
    except OSError:
        return incomplete
    try:
        with (report / "modules.txt").open("rb") as stream:
            raw = stream.read(8193)
        lines = raw.decode("ascii").splitlines()
        if len(raw) > 8192 or len(lines) != 10 or lines[0] != "S|s2am-modules-v1|8" \
                or lines[-1] != "T|complete":
            return invalid
        copied = rom = 0
        for name, line in zip(FILES, lines[1:-1]):
            parts = line.split("|")
            if len(parts) != 11 or parts[:2] != ["F", name] or parts[7] not in STATUSES:
                return invalid
            strings = parts[2:7] + parts[8:]
            if any(not re.fullmatch(r"[0-9]{1,10}", item) for item in strings):
                return invalid
            values = [int(item) for item in strings]
            if any(value > 0xffffffff for value in values):
                return invalid
            attrs, high, low, _time_high, _time_low, error, count, crc = values
            status = parts[7]
            if count > FILE_LIMIT:
                return invalid
            if status == "copied":
                if attrs & (0x2000 | 0x10) or high or low > FILE_LIMIT or error or count != low:
                    return invalid
                path = report / "modules" / name
                info = path.lstat()
                if (report / "modules").is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size != count:
                    return invalid
                checksum = 0
                with path.open("rb") as stream:
                    remaining = count
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            return invalid
                        checksum = zlib.crc32(chunk, checksum)
                        remaining -= len(chunk)
                    if stream.read(1):
                        return invalid
                if checksum != crc:
                    return invalid
                copied += 1
            elif crc:
                return invalid
            elif status == "rom-module":
                if not attrs & 0x2000 or count or error:
                    return invalid
                rom += 1
            elif status == "directory" and (not attrs & 0x10 or count or error):
                return invalid
            elif status == "too-large" and (not (high or low > FILE_LIMIT) or count or error):
                return invalid
            elif status == "attrs-error" and any((attrs, high, low, _time_high, _time_low, count)):
                return invalid
    except (OSError, UnicodeError, ValueError):
        return invalid
    return (f"modules: {copied}/8 files copied, {rom} ROM modules, {8 - copied - rom} unavailable; "
            "details in modules.txt; no clock-control interface established")
