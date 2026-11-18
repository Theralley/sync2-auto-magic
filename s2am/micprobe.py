"""Reads mic.txt, the report of s2ammic.exe (the microphone probe)."""
from __future__ import annotations

from pathlib import Path

QUIET_PEAK = 200  # below this peak a recording counts as silence (16-bit samples)
VERSIONS = ("s2am-mic-v1", "s2am-mic-v2", "s2am-mic-v3")
HEARD = ("device", "rate", "channels", "bytes", "peak", "average")
WHY = {"start": "opened, but recording would not start", "nomemory": "opened, but there was no memory to record",
       "abandoned": "recorded, but the driver would not give the buffers back",
       "queue": "opened, but not all of its buffers could be queued"}
BUSY = 4  # MMSYSERR_ALLOCATED: another program holds the device


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
    there. A line cut short (the probe was ended mid-write) is skipped and makes it incomplete.
    v1 recorded one device after the other; v2 listens on all at once and adds ``first second``
    (when a device first delivered data) and the mixer's controls."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = {"version": lines[0] if lines else "", "inputs": None, "names": [], "heard": [],
              "refused": [], "failed": [], "controls": [], "opened": set(), "steps": [], "phases": [],
              "complete": bool(lines) and lines[-1] == "end"}
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
            elif code == 0:
                result["opened"].add(opening.get("device", "?"))
        elif kind == "started":  # v1
            start = _number(fields, "result")
        elif kind == "listening" and _number(fields, "result"):  # v2
            result["failed"].append({"device": fields.get("device", "?"), "rate": "?", "why": "start",
                                     "result": fields["result"]})
        elif kind == "queued" and _number(fields, "result"):  # v2: some buffers may still be queued
            result["failed"].append({"device": fields.get("device", "?"), "rate": "?", "why": "queue",
                                     "result": fields["result"]})
        elif kind in ("nomemory", "abandoned"):
            target = fields if "device" in fields else opening
            if target is not None:
                result["failed"].append({"device": target.get("device", "?"), "rate": target.get("rate", "?"),
                                         "why": kind, "result": fields.get("result", "")})
        elif kind == "route test":  # v3
            able = _number(fields, "set property")
            result["can route"] = None if able is None else able == 1
        elif kind == "route" and "|step " in line and _number(fields, "number") is not None:
            result["steps"].append({"number": _number(fields, "number"), "result": None,  # v3: one request
                                    "step": line.split("|step ", 1)[1]})
        elif kind == "routed":  # its answer, matched by the request's own number
            for step in result["steps"]:
                if step["number"] == _number(fields, "number"):
                    step["result"] = _number(fields, "result")
        elif kind == "phase" and "|name " in line and _number(fields, "buffers left") is not None:
            result["phases"].append({"name": line.split("|name ", 1)[1], "seconds": _number(fields, "seconds"),
                                     "bytes": _number(fields, "bytes"), "left": _number(fields, "buffers left")})
        elif kind == "control" and "|name " in line and _number(fields, "read") == 0:
            result["controls"].append(line.split("|", 1)[1])
        elif kind == "heard":
            heard = {name: _number(fields, name) for name in HEARD}
            if None in heard.values():
                result["complete"] = False
            elif start:
                result["failed"].append({**opening, "why": "start", "result": str(start)})
            else:
                heard["first"] = _number(fields, "first second")
                result["heard"].append(heard)
    return result


def _device(number: str | int) -> str:
    return "the default device" if str(number) == "99" else f"device {number}"


def summary(report: Path) -> list[str]:
    """What the probe found, one finding per line."""
    path = report / "mic.txt"
    if not path.is_file():
        return ["microphone probe: no mic.txt in the report; the probe did not run"]
    found = parse(path.read_text(errors="replace"))
    if found["version"] not in VERSIONS:
        return ["microphone probe: mic.txt is not a report this version reads"]
    if found["version"] == "s2am-mic-v3":
        return _route_summary(found)
    lines = [f"microphone probe: {'an unknown number of' if found['inputs'] is None else found['inputs']} "
             "recording device(s)"
             + (f" ({', '.join(name or 'unnamed' for name in found['names'])})" if found["names"] else "")]
    unstarted = {str(f["device"]) for f in found["failed"] if f["why"] == "start"}
    for heard in found["heard"]:
        where = f"{_device(heard['device'])} at {heard['rate']} Hz"
        if not heard["bytes"] and str(heard["device"]) in unstarted:
            continue  # said below: it never started
        if not heard["bytes"]:
            lines.append(f"  {where}: opened, but no sound data arrived")
        elif heard["peak"] < QUIET_PEAK:
            lines.append(f"  {where}: data arrived, but it is silence (peak {heard['peak']} of 32767)")
        else:
            lines.append(f"  {where}: sound (peak {heard['peak']} of 32767, average {heard['average']})"
                         + (f", from second {heard['first']}" if heard.get("first") else ""))
    for failed in found["failed"]:
        rate = "" if failed["rate"] == "?" else f" at {failed['rate']} Hz"
        lines.append(f"  {_device(failed['device'])}{rate}: {WHY[failed['why']]}"
                     + (f" (error {failed['result']})" if failed["result"] else ""))
    opened = ({str(heard["device"]) for heard in found["heard"]} | {str(f["device"]) for f in found["failed"]}
              | found["opened"])
    refused: dict[str, set[str]] = {}
    for item in found["refused"]:
        refused.setdefault(item["device"], set()).add(item["result"])
    for device, codes in refused.items():
        if device in opened:
            continue  # it opened in a later format
        why = "in use by another program" if codes == {str(BUSY)} else f"error {', '.join(sorted(codes))}"
        lines.append(f"  {_device(device)}: would not open in any format ({why})")
    if found["controls"]:
        lines.append(f"  mixer: {len(found['controls'])} control value(s) read; see mic.txt")
    if not found["complete"]:
        lines.append("  NOT complete: the probe stopped before its end; the last line of mic.txt shows where")
    return lines


GIVEN_BACK = "give sync its microphone back"


def _route_summary(found: dict) -> list[str]:
    """The route test: each request to the router with its answer, what each phase delivered,
    and above all whether SYNC got its microphone back."""
    lines = ["microphone route test:"]
    if found.get("can route") is False:
        lines.append("  could not run: this SYNC has no waveInSetProperty; nothing was asked of the router")
    elif not found["steps"] and found["complete"]:
        lines.append("  could not run: recording device 0 did not open or start; nothing was asked of the router")
    for step in found["steps"]:
        answer = "no answer (the probe stopped there)" if step["result"] is None else \
            "ok" if step["result"] == 0 else f"refused (error {step['result']})"
        lines.append(f"  {step['step']}: {answer}")
    for phase in found["phases"]:
        note = "" if phase["bytes"] else " (nothing)"
        if not phase["left"]:
            note += " (its buffers were used up: says nothing about later sound)"
        lines.append(f"  {phase['name']}, {phase['seconds']} s: {phase['bytes']} bytes{note}")
    for heard in found["heard"]:
        lines.append(f"  recording: peak {heard['peak']} of 32767, average {heard['average']}"
                     + (" (silence)" if heard["bytes"] and heard["peak"] < QUIET_PEAK else ""))
    for failed in found["failed"]:
        lines.append(f"  {_device(failed['device'])}: {WHY[failed['why']]}"
                     + (f" (error {failed['result']})" if failed["result"] else ""))
    took = [s for s in found["steps"] if s["step"] == "take sync's route away"]
    back = [s for s in found["steps"] if s["step"] == GIVEN_BACK]
    if took and not (back and back[-1]["result"] == 0):
        lines.append("  SYNC did NOT get its microphone back: restart SYNC")
    elif took:
        lines.append("  SYNC's microphone route was put back; restart SYNC anyway to be sure")
    if not found["complete"]:
        lines.append("  NOT complete: the probe stopped before its end; the last line of mic.txt shows where")
    return lines
