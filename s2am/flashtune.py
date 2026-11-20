"""Ford's screen program (Desktop.exe) and the processor time it asks for.

Desktop.exe reads four numbers from HKLM\\Software\\Ford\\Flash when it starts. The flash-tune job
changes them through s2amflash.exe, which keeps Ford's values in a backup on the car and holds the
same limits as LIMITS below; ``--undo`` writes them back. Nothing takes effect before SYNC restarts.
"""
from __future__ import annotations

from pathlib import Path

# name: (lowest, highest, Ford's value as read from a car on 2026-11-19, the command line option)
LIMITS = {
    "ThreadPrio256": (250, 253, 250, "prio"),
    "FastThreadPrio256": (248, 253, 248, "fast_prio"),
    "FlashNormalTimerInterval": (500, 2000, 500, "interval"),
    "FlashFastTimerInterval": (66, 250, 66, "fast_interval"),
}
BACKUP = "\\SyncExtendedPack\\_s2am\\flash-backup.txt"
WAIT_S = 30


def check(values) -> dict[str, int]:
    """The settings of a job, validated: known names, whole numbers inside the limits, at least one."""
    if not isinstance(values, dict) or not values:
        raise ValueError(f"invalid flash settings {values!r}")
    for name, value in values.items():
        if name not in LIMITS or not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"invalid flash setting {name!r}: {value!r}")
        low, high = LIMITS[name][:2]
        if not low <= value <= high:
            raise ValueError(f"{name} must be {low} to {high}, not {value}")
    return {name: values[name] for name in LIMITS if name in values}


def argument(params: dict) -> str:
    """What s2amflash.exe is given before the '|' and the report folder."""
    if params.get("undo") is True:
        if params.get("values"):
            raise ValueError("an undo takes no settings")
        return "undo"
    if params.get("undo") not in (None, False):
        raise ValueError(f"invalid undo {params.get('undo')!r}")
    return "set:" + ",".join(f"{name}={value}" for name, value in check(params.get("values")).items())


def parse(report: Path) -> dict:
    """flash.txt as {"before": {...}, "after": {...}, "restore": {...}, "backup": str|None,
    "flush": int|None, "done": "ok"|"refused"|"failed"|None, "why": str, "killed": bool}; a value is an int,
    or None for 'absent'. "restore" is what an undo found in the backup."""
    result = {"before": {}, "after": {}, "restore": {}, "backup": None, "flush": None, "done": None, "why": "",
              "killed": (report / "flash-killed.txt").is_file()}
    path = report / "flash.txt"
    if not path.is_file():
        return result
    for line in path.read_text(errors="replace").splitlines():
        parts = line.strip().split("|")
        if parts[0] in ("before", "after", "restore") and len(parts) == 3 and parts[1] in LIMITS:
            if parts[2] == "absent" or parts[2].isdigit():
                result[parts[0]][parts[1]] = None if parts[2] == "absent" else int(parts[2])
        elif parts[0] == "backup" and len(parts) == 2:
            result["backup"] = parts[1]
        elif parts[0] == "flush" and len(parts) == 2 and parts[1].isdigit():
            result["flush"] = int(parts[1])
        elif parts[0] == "done" and len(parts) >= 2:
            result["done"], result["why"] = parts[1], "|".join(parts[2:])
    return result


def _show(values: dict) -> str:
    return ", ".join(f"{name} {'absent' if values[name] is None else values[name]}" for name in LIMITS if name in values)


READ_BACK = ("read what the car holds with s2am job registry --root 'HKLM\\Software\\Ford\\Flash'; "
             "s2am job flash-tune --undo puts Ford's values back while the backup is on the car")


def summary(report: Path, params: dict) -> list[str]:
    """What the car answered, checked against what the job asked for. "verified" needs the whole
    chain: all four values read back after the write, the registry saved (flush 0), and the
    backup's state. Anything less after a possible write is reported as not known."""
    seen = parse(report)
    undo = params.get("undo") is True
    full = all(name in seen["after"] for name in LIMITS)
    lines = ["before: " + _show(seen["before"])] if seen["before"] else []
    if full:
        lines.append("now: " + _show(seen["after"]))
    if seen["killed"] or seen["done"] is None:
        return lines + ["NOT known: s2amflash.exe " + ("did not finish in time and was ended" if seen["killed"]
                                                       else "left no result") + "; " + READ_BACK]
    if seen["done"] == "refused":  # the tool's own word that it stopped before writing to the registry
        return lines + [f"nothing changed: {seen['why']}"]
    if seen["done"] != "ok":
        if full and all(name in seen["before"] for name in LIMITS) and seen["after"] == seen["before"] \
                and seen["flush"] == 0:
            return lines + [f"FAILED, nothing is changed: {seen['why']}"]
        return lines + [f"FAILED: {seen['why'] or seen['done']}",
                        ("the values on the car may differ from before" if full else "what the car holds is NOT known")
                        + "; " + READ_BACK]
    if undo:
        wanted = seen["restore"] if all(name in seen["restore"] for name in LIMITS) else None
        good = seen["backup"] == "removed"
    else:
        chosen = check(params.get("values"))
        wanted = {**seen["before"], **chosen} if all(name in seen["before"] for name in LIMITS) else None
        good = seen["backup"] in ("written", "kept")
    if not (full and wanted is not None and seen["after"] == wanted and seen["flush"] == 0 and good):
        return lines + ["NOT verified: the tool says it worked, but its report does not show it (values read "
                        "back, registry saved, backup); " + READ_BACK]
    lines.append("verified: Ford's values are back, saved, and the backup is removed" if undo else
                 "verified: the values read back as asked and were saved; Ford's values are in the backup "
                 "on the car" + (" (kept from an earlier run)" if seen["backup"] == "kept" else ""))
    lines.append("Desktop.exe uses them after SYNC restarts")
    return lines
