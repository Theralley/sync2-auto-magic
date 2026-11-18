"""Reads mic.txt, the report of s2ammic.exe (the microphone probe)."""
from __future__ import annotations

from pathlib import Path

QUIET_PEAK = 200  # below this peak a recording counts as silence (16-bit samples)
HEARD = ("device", "rate", "channels", "bytes", "peak", "average")
WHY = {"start": "opened, but recording would not start", "nomemory": "opened, but there was no memory to record",
       "abandoned": "recorded, but the driver would not give the buffer back; the probe stopped there"}


def _fields(line: str) -> dict[str, str]:
    """"heard|device 0|rate 16000" -> {"device": "0", "rate": "16000"}; names may hold spaces."""
    out = {}
    for part in line.split("|")[1:]:
        name, _, value = part.rpartition(" ")
        out[name] = value
    return out


def _number(fields: dict[str, str], name: str) -> int | None:
    value = fields.get(name, "")
    return int(value) if value.isdigit() else None


def parse(text: str) -> dict:
    """Devices listed and what each recording attempt came to; ``complete`` once the end line is
    there. A line cut short (the probe was ended mid-write) is skipped and makes it incomplete."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = {"version": lines[0] if lines else "", "inputs": None, "names": [], "heard": [],
              "refused": [], "failed": [], "complete": bool(lines) and lines[-1] == "end"}
    opening, start = None, None
    for line in lines[1:]:
        kind, fields = line.split("|", 1)[0], _fields(line)
        if kind == "wave in":
            result["inputs"] = _number(fields, "devices")
        elif kind == "in":
            result["names"].append(line.split("|name ", 1)[-1] if "|name " in line else "")
        elif kind == "open":
            opening, start = fields, None
        elif kind == "opened" and opening is not None:
            code = _number(fields, "result")
            if code:
                result["refused"].append({**opening, "result": str(code)})
        elif kind == "started":
            start = _number(fields, "result")
        elif kind in ("nomemory", "abandoned") and opening is not None:
            result["failed"].append({**opening, "why": kind, "result": fields.get("result", "")})
        elif kind == "heard":
            heard = {name: _number(fields, name) for name in HEARD}
            if None in heard.values():
                result["complete"] = False
            elif start:
                result["failed"].append({**opening, "why": "start", "result": str(start)})
            else:
                result["heard"].append(heard)
    return result


def _device(number: int) -> str:
    return "the default device" if number == 99 else f"device {number}"


def summary(report: Path) -> list[str]:
    """What the probe found, one finding per line."""
    path = report / "mic.txt"
    if not path.is_file():
        return ["microphone probe: no mic.txt in the report; the probe did not run"]
    found = parse(path.read_text(errors="replace"))
    if found["version"] != "s2am-mic-v1":
        return ["microphone probe: mic.txt is not a report this version reads"]
    lines = [f"microphone probe: {'an unknown number of' if found['inputs'] is None else found['inputs']} "
             "recording device(s)"
             + (f" ({', '.join(name or 'unnamed' for name in found['names'])})" if found["names"] else "")]
    for heard in found["heard"]:
        where = f"{_device(heard['device'])} at {heard['rate']} Hz"
        if not heard["bytes"]:
            lines.append(f"  {where}: opened, but no sound data arrived in 5 s")
        elif heard["peak"] < QUIET_PEAK:
            lines.append(f"  {where}: data arrived, but it is silence (peak {heard['peak']} of 32767)")
        else:
            lines.append(f"  {where}: sound (peak {heard['peak']} of 32767, average {heard['average']})")
    for failed in found["failed"]:
        lines.append(f"  {_device(int(failed['device']))} at {failed['rate']} Hz: {WHY[failed['why']]}"
                     + (f" (error {failed['result']})" if failed["result"] else ""))
    for refused in found["refused"]:
        lines.append(f"  {_device(int(refused['device']))} at {refused['rate']} Hz, {refused['channels']} "
                     f"channel(s): would not open (error {refused['result']})")
    if not found["complete"]:
        lines.append("  NOT complete: the probe stopped before its end; the last line of mic.txt shows where")
    return lines
