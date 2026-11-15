"""Interpret a bounded v1 PMIC report without confusing presets with measured voltage."""
from pathlib import Path
import re


def summary(report: Path) -> str:
    try:
        with (report / "pmic-done.txt").open("rb") as stream:
            marker = stream.read(129)
        done = marker.strip() if len(marker) <= 128 else b""
    except OSError:
        done = b""
    if done == b"T|unavailable":
        return "PMIC unavailable: see pmic.txt for the stage and system error; no voltage result"
    if done != b"T|complete":
        return "NOT complete: PMIC report may be partial; no verified voltage result"
    invalid = "NOT verified: PMIC completion marker has no matching valid preset report"
    try:
        with (report / "pmic.txt").open("rb") as stream:
            data = stream.read(4097)
        lines = data.decode("ascii").splitlines()
    except (OSError, UnicodeError):
        return invalid
    if len(data) > 4096 or len(lines) != 8 or not lines[0].startswith("S|s2am-pmic-v1|") \
            or not lines[6].startswith("N|") or lines[7] != "T|complete":
        return invalid
    fields = ("R|7|", "R|24|", "V|SW1 normal preset mV|", "V|SW1 DVS preset mV|",
              "V|SW1 standby preset mV|")
    values = []
    for line, prefix in zip(lines[1:6], fields):
        if not re.fullmatch(re.escape(prefix) + r"[0-9]{1,8}", line):
            return invalid
        values.append(int(line[len(prefix):]))
    identity, sw1, *presets = values
    if identity > 0xffffff or identity & 0x1e0 != 0x1c0 or (identity >> 13) & 0x3f != 2 \
            or sw1 > 0xffffff or presets != [600 + 25 * ((sw1 >> shift) & 31) for shift in (0, 5, 10)]:
        return invalid
    return (f"SW1 presets: normal {presets[0]} mV, DVS {presets[1]} mV, standby {presets[2]} mV; "
            "active rail voltage remains unknown")
