"""Reads nd.txt, the report of s2amnd.exe (job kind neondiag): which NEON test stages a car
passed, and for a stage that faulted, which exception and where.

Lines: S|s2am-nd-v1, D|debug|0 or 1, G|<n>|<name>, M|exe or dll|<base>, X|<code>|<address>|
<first chance>|<parameters...>, Y|<pc>|<opcode>|<psr>|<sp>|<lr>|<r0..r12>,
Q|<n>|<name>|<how>|<exit code>, T|complete. Numbers after X, Y, M and the Q code are hex.
Each stage is watched by a debugger process of its own. When that gave no answer (how is not
exit, fault or break) the stage is run once more without one: Z|<n>|<name>|<how>|<exit code>.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from .container import REPO

sys.path.insert(0, str(REPO / "tools"))
import patch_waveout  # noqa: E402

REPORT = "nd.txt"
SAMPLE = "sample.h264"
DLLS = ("avutil-54.dll", "avcodec-56.dll", "avformat-56.dll")
MARKERS = {"avutil": ("avutil-54.dll", "av_malloc"), "avcodec": ("avcodec-56.dll", "avcodec_register_all"),
           "avformat": ("avformat-56.dll", "av_register_all")}  # the function each L| line names
MAX_SETS = 4
MAX_SAMPLE = 8 * 1024 * 1024
LIMIT = 524288
EXPECTED_FAULT = ("break", "q128-off8")  # a fault is the right answer for these on hardware
LAZY = ("cold-dp", "cold-ls", "cold-thread-dp", "cold-thread-ls", "xfer-dp", "xfer-ls", "dp-loop")
ALIGNED = ("ld32-off2", "ld32-off1", "st32-off2", "st32-off1", "ld16-off1",
           "ld32-full-off4", "ld32-full-off1", "st32-full-off1")
STAGES = ("break", *LAZY, *ALIGNED, "word-off1", "q128-off8")
UNKNOWN = ("stuck", "silent", "lost", "start", "timeout")  # the test itself gave no answer: says nothing about NEON
EXCEPTIONS = {0xC000001D: "illegal instruction", 0x80000002: "misaligned data",
              0xC0000005: "access violation", 0x80000003: "breakpoint",
              0xC000001E: "invalid lock sequence", 0xC00000FD: "stack overflow"}


def export_rva(data: bytes, name: str) -> int:
    """Where a named function lies in a DLL, from its start."""
    image = patch_waveout.PEImage(data)
    rva, _ = image.directory(0)
    table = image.rva_to_offset(rva)
    count, functions, names, ordinals = (image.u32(table + 24), image.u32(table + 28),
                                         image.u32(table + 32), image.u32(table + 36))
    for i in range(count):
        if image.cstring(image.u32(image.rva_to_offset(names) + 4 * i)) == name:
            ordinal = image.u16(image.rva_to_offset(ordinals) + 2 * i)
            return image.u32(image.rva_to_offset(functions) + 4 * ordinal)
    raise ValueError(f"no function {name} in this file")


def fnv(data: bytes, start: int = 2166136261) -> int:
    for byte in data:
        start = ((start ^ byte) * 16777619) & 0xFFFFFFFF
    return start


def plan(sets: list[str], sample: Path | None, reference: Path | None = None,
         frame: str | None = None) -> tuple[dict, dict, list]:
    """(params, extra files, payload) for a job with trial decodes; all empty without sets.

    sets: "label=folder", each folder holding the three decoder files. The files go to
    set-<label> in the job's folder on the car and are only loaded from there. reference is
    the sample decoded by a decoder known to be right (raw I420), frame its "WIDTHxHEIGHT":
    with them the import can say whether each set decoded the right picture."""
    if not sets:
        if sample or reference:
            raise ValueError("--sample and --reference need at least one --decode LABEL=FOLDER")
        return {}, {}, []
    if not sample:
        raise ValueError("--decode needs --sample FILE (a raw H.264 stream)")
    if len(sets) > MAX_SETS:
        raise ValueError(f"at most {MAX_SETS} sets")
    stream = sample.read_bytes()
    if not 0 < len(stream) <= MAX_SAMPLE:
        raise ValueError("the sample must be between 1 byte and 8 MB")
    params = {"sets": {}, "sample_sha256": hashlib.sha256(stream).hexdigest()}
    payload = []
    for item in sets:
        label, _, folder = item.partition("=")
        if not re.fullmatch(r"[a-z0-9]{1,8}", label) or label == "installed" or label in params["sets"]:
            raise ValueError(f"set label {label!r}: 1-8 of a-z and 0-9, each once, not 'installed'")
        files = {}
        for name in DLLS:
            path = Path(folder) / name
            if not path.is_file():
                raise ValueError(f"{path} is missing")
            data = path.read_bytes()
            marker = next(function for file, function in MARKERS.values() if file == name)
            files[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "marker_rva": export_rva(data, marker),
                           "image_size": patch_waveout.PEImage(data).u32(patch_waveout.PEImage(data).opt + 56)}
            payload.append((path, f"set-{label}/{name}"))
        params["sets"][label] = files
    if reference:
        match = re.fullmatch(r"(\d{2,4})x(\d{2,4})", frame or "")
        if not match:
            raise ValueError("--reference needs --frame WIDTHxHEIGHT")
        size = int(match[1]) * int(match[2]) * 3 // 2
        picture = reference.read_bytes()
        if not picture or len(picture) % size:
            raise ValueError("the reference is not a whole number of frames of that size")
        sums, value = [], 2166136261
        for start in range(0, len(picture), size):
            value = fnv(picture[start:start + size], value)
            sums.append(f"{value:08x}")
        params["frame"], params["sums"] = frame, sums
    return params, {SAMPLE: stream}, payload


def parse(path: Path) -> dict:
    """{'complete', 'debug', 'stages': {name: {'how', 'code', 'faults': [...]}}, 'running'}.

    Raises ValueError for a file that is not an s2amnd report."""
    data = path.read_bytes()
    if len(data) > LIMIT:
        raise ValueError("the report is larger than s2amnd.exe writes")
    lines = data.decode("ascii", errors="replace").split("\r\n")
    if not lines or lines[0] != "S|s2am-nd-v1":
        raise ValueError("not an s2amnd report")
    result = {"complete": False, "debug": None, "stages": {}, "running": None}
    faults: list[dict] = []
    notes: list[list[str]] = []
    for line in lines[1:]:
        part = line.split("|")
        try:
            if part[0] == "D" and part[1:2] == ["debug"]:
                result["debug"] = part[2] == "1"
            elif part[0] == "G":
                result["running"], faults, notes = part[2], [], []
            elif part[0] in ("L", "P", "R", "E", "B"):
                notes.append(part)
            elif part[0] == "X":
                faults.append({"code": int(part[1], 16), "address": int(part[2], 16),
                               "first": int(part[3], 16), "parameters": [int(x, 16) for x in part[4:]]})
            elif part[0] == "Y" and faults and part[1] != "none":
                faults[-1].update(pc=int(part[1], 16), opcode=int(part[2], 16),
                                  registers=[int(x, 16) for x in part[3:]])
            elif part[0] == "Q":
                result["stages"][part[2]] = {"how": part[3], "code": int(part[4], 16), "faults": faults,
                                             "notes": notes}
                result["running"], faults, notes = None, [], []
            elif part[0] == "Z":
                result["stages"][part[2]]["plain"] = {"how": part[3], "code": int(part[4], 16), "notes": notes}
                result["running"], faults, notes = None, [], []
            elif line == "T|complete":
                result["complete"] = True
        except (IndexError, ValueError, KeyError) as error:
            raise ValueError(f"damaged line {line!r}") from error
    return result


def _fault(name: str, stage: dict) -> str:
    if not stage["faults"]:
        return f"{name}: ended by a fault that was not recorded (exit code {stage['code']:#x})"
    fault = stage["faults"][-1]
    what = EXCEPTIONS.get(fault["code"], f"exception {fault['code']:#010x}")
    text = f"{name}: {what} at {fault['address']:#010x}"
    if "opcode" in fault:
        text += f", instruction {fault['opcode']:08x}"
    if fault["parameters"]:
        text += ", parameters " + " ".join(f"{x:#x}" for x in fault["parameters"])
    return text


def _where(address: int, stage: dict, files: dict | None) -> str:
    """'in avcodec-56.dll at +0x1234' when the address lies in one of the set's files."""
    for note in stage["notes"]:
        if note[0] == "L" and files and note[1] in MARKERS:
            name = MARKERS[note[1]][0]
            base = int(note[2], 16) - files[name]["marker_rva"]
            if 0 <= address - base < files[name]["image_size"]:
                return f" (in {name} at +{address - base:#x})"
    return ""


def _decode(name: str, stage: dict, params: dict) -> str:
    label = name[len("decode-"):]
    files = (params.get("sets") or {}).get(label)
    result = next((note for note in stage["notes"] if note[0] == "R"), None)
    progress = [int(note[1]) for note in stage["notes"] if note[0] == "P"]
    errors = ["|".join(note[1:]) for note in stage["notes"] if note[0] == "E"]
    text = f"decode '{label}': "
    if stage["how"] == "exit" and stage["code"] == 0 and result:
        count, total, milliseconds = int(result[2]), result[8], int(result[10])
        text += f"{count} frames {result[4]}x{result[6]} in {milliseconds} ms"
        if milliseconds:
            text += f" ({count * 1000 / milliseconds:.1f} frames a second)"
        sums = params.get("sums")
        if sums and 0 < count <= len(sums):
            text += ", the right picture" if sums[count - 1] == total else ", but NOT the right picture"
        else:
            text += f", picture sum {total}"
        return text
    if stage["how"] == "fault" and stage["faults"]:
        fault = stage["faults"][-1]
        what = EXCEPTIONS.get(fault["code"], f"exception {fault['code']:#010x}")
        text += f"{what} at {fault['address']:#010x}{_where(fault['address'], stage, files)}"
        if "opcode" in fault:
            text += f", instruction {fault['opcode']:08x}"
        if fault["parameters"]:
            text += ", parameters " + " ".join(f"{x:#x}" for x in fault["parameters"])
        return text + f", after {progress[-1] if progress else 'fewer than 10'} frames"
    return text + f"{stage['how']} (code {stage['code']:#x})" + (f", {'; '.join(errors)}" if errors else "")


def summary(report: Path | None, params: dict | None = None) -> list[str]:
    """Plain lines for the import: what held, what faulted, and what that points at."""
    path = report / REPORT if report else None
    if not path or not path.is_file():
        return ["NOT verified: s2amnd.exe wrote nothing; the diagnosis did not run"]
    try:
        found = parse(path)
    except ValueError as error:
        return [f"NOT verified: {error}"]
    lost = {name: stage["how"] for name, stage in found["stages"].items() if "plain" in stage}
    stages = {name: ({"how": stage["plain"]["how"], "code": stage["plain"]["code"], "faults": [],
                      "notes": stage["plain"]["notes"]} if name in lost else stage)
              for name, stage in found["stages"].items()}
    lines = []
    if not found["complete"]:
        stuck = [name for name, stage in stages.items() if stage["how"] == "stuck"]
        lines.append("NOT complete: " + (f"'{stuck[0]}' did not end when told to, so nothing was started after it"
                                         if stuck else "it stopped" +
                                         (f" during '{found['running']}'" if found["running"] else ""))
                     + "; what follows is only what it got to")
    if found["debug"] is False:
        lines.append("this Windows CE did not let the program watch its stages: only exit codes, no fault details")
    if lost:
        lines.append(f"the watcher got no answer for {len(lost)} ({', '.join(sorted(set(lost.values())))}): "
                     "those were run again without it, so a fault there has no details")
    decodes = {name: stage for name, stage in stages.items() if name.startswith("decode-")}
    bad = {name: stage for name, stage in stages.items() if name not in EXPECTED_FAULT and name not in decodes
           and (stage["how"] != "exit" or stage["code"] != 0)}
    held = [name for name in STAGES if name in stages and name not in bad and name not in EXPECTED_FAULT]
    lines.append(f"{len(held)} of {len(STAGES) - len(EXPECTED_FAULT)} stages held")
    for name, stage in bad.items():
        if stage["how"] == "fault":
            lines.append("  " + _fault(name, stage))
        elif stage["how"] == "exit":
            lines.append(f"  {name}: ran to the end with a wrong value (exit code {stage['code']:#x})")
        elif stage["how"] in UNKNOWN:
            lines.append(f"  {name}: no answer ({stage['how']}); nothing shows why, so this says nothing about NEON")
        else:
            lines.append(f"  {name}: {stage['how']} (code {stage['code']:#x})")
    control = stages.get("q128-off8")
    if control:
        lines.append("control (a load that breaks its 16-byte promise): "
                     + ("faulted, as it should" if control["how"] == "fault" else
                        "did NOT fault: this car does not enforce NEON alignment promises"
                        if control["how"] == "exit" and control["code"] == 0 else
                        f"no answer ({control['how']}, code {control['code']:#x})"))
    told = {name for name, stage in bad.items() if stage["how"] not in UNKNOWN}
    if any(name in told for name in LAZY):
        lines.append("points at: NEON-only instructions fail when the floating-point unit is not already "
                     "switched on for the thread. FFmpeg's NEON code cannot run on this system as it is")
    if any(name in told for name in ALIGNED):
        lines.append("points at: NEON loads/stores of 16- or 32-bit elements need aligned addresses here. "
                     "A NEON build that uses byte elements at those places should work")
    for name, stage in decodes.items():
        lines.append(_decode(name, stage, params or {}))
    if found["complete"] and not bad and not decodes:
        lines.append("none of the tested causes: the next step is a trial decode with the NEON files")
    return lines
