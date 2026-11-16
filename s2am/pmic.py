"""Interpret bounded v1/v2 PMIC reports without confusing configuration with measured voltage."""
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
    if len(data) > 4096 or not lines:
        return invalid
    header = lines[0].split("|", 3)
    if len(header) != 4 or header[0] != "S" or header[2] != "PMI1:" \
            or header[1] not in ("s2am-pmic-v1", "s2am-pmic-v2"):
        return invalid
    has_mode = header[1] == "s2am-pmic-v2"
    registers = ("R|7|", "R|24|", "R|28|") if has_mode else ("R|7|", "R|24|")
    fields = registers + ("V|SW1 normal preset mV|", "V|SW1 DVS preset mV|", "V|SW1 standby preset mV|")
    if len(lines) != len(fields) + 3 or not lines[-2].startswith("N|") or lines[-1] != "T|complete":
        return invalid
    values = []
    for line, prefix in zip(lines[1:-2], fields):
        if not re.fullmatch(re.escape(prefix) + r"[0-9]{1,8}", line):
            return invalid
        values.append(int(line[len(prefix):]))
    identity, sw1 = values[:2]
    presets = values[len(registers):]
    # MC13892 Rev.19 table 47 note 71: SW1HI (bit 23) is unsupported for SW1.
    if identity > 0xffffff or identity & 0x1e0 != 0x1c0 or (identity >> 13) & 0x3f != 2 \
            or sw1 > 0xffffff or sw1 & 0x800000 \
            or presets != [600 + 25 * ((sw1 >> shift) & 31) for shift in (0, 5, 10)]:
        return invalid
    configuration = ""
    if has_mode:
        mode_config = values[2]
        # MC13892 Rev.19 table 140: SW1MODE[3:0], SIDEN bit 8, reserved bits 9/23.
        if mode_config > 0xffffff or mode_config & 0x800200:
            return invalid
        configuration = (f"SW1 mode code {mode_config & 15}, "
                         f"SID {'enabled' if mode_config & 0x100 else 'disabled'}; ")
    return (f"SW1 presets: normal {presets[0]} mV, DVS {presets[1]} mV, standby {presets[2]} mV; "
            f"{configuration}active rail voltage remains unknown")
