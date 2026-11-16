"""Validate independent native decoder evidence without rewriting a swap's history."""
import hashlib
import re
import stat
import zlib
from pathlib import Path

from .job import DECODER_FILES, JOB_ID, Job
from .modules import FILE_LIMIT, STATUSES

LABELS = tuple(f"{prefix}-{name}" for prefix in ("active", "backup", "staged-new")
               for name in DECODER_FILES) + (
    "staged-script", "staged-runner", "staged-mortscript", "staged-job", "old-done")
DIRECTORIES = ("root", "apps", "usb", "staged", "backup")
PROCESS_STATES = {"unavailable", "stale-marker", "launch-error", "exited", "timeout",
                  "wait-error", "exit-error", "error-budget"}


def target_id(value: str) -> str:
    if not isinstance(value, str) or not JOB_ID.fullmatch(value) or value.split("-")[2] != "dec":
        raise ValueError("decoder inspection needs a valid decoder job ID")
    return value


def plan(record: dict) -> dict:
    target_id(record["id"])
    if record.get("kind") != "dec" or record.get("params", {}).get("restore"):
        raise ValueError("inspect the original decoder test job, not its restore")
    files = record.get("params", {}).get("files", {})
    if set(files) != set(DECODER_FILES):
        raise ValueError("decoder job lacks the three expected file identities")
    expected = {}
    for name in DECODER_FILES:
        expected[name] = {}
        for key in ("old_sha256", "new_sha256"):
            value = files[name].get(key, "")
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("decoder job lacks trusted SHA-256 identities")
            expected[name][key] = value
    return {"target": record["id"], "expected": expected}


def _read(path: Path, cap: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
        raise ValueError("non-regular or oversized evidence")
    with path.open("rb") as stream:
        data = stream.read(cap+1)
    if len(data) != info.st_size or len(data) > cap:
        raise ValueError("evidence changed while reading")
    return data


def _numbers(values):
    if any(not re.fullmatch(r"[0-9]{1,10}", x) or int(x) > 0xffffffff for x in values):
        raise ValueError("invalid DWORD")
    return [int(x) for x in values]


def analyze(folder: Path, job: Job) -> dict:
    bad = {"complete": False, "decoder": "unknown", "reason": "incomplete or invalid native evidence"}
    try:
        target_id(job.params["target"])
        if folder.is_symlink() or (folder / "files").is_symlink():
            return bad
        if _read(folder / "done.txt", 128).strip().decode("ascii") != job.id:
            return bad
        lines = _read(folder / "decdiag.txt", 16384).decode("ascii").splitlines()
        if lines[0] != f"S|s2am-decdiag-v1|{job.id}|{job.params['target']}" or lines[-1] != "T|complete":
            return bad
        seen, hashes, processes = set(), {}, {}
        for line in lines[1:-1]:
            parts = line.split("|")
            if len(parts) < 2 or tuple(parts[:2]) in seen:
                return bad
            seen.add(tuple(parts[:2]))
            if parts[0] == "F":
                if len(parts) != 11 or parts[1] not in LABELS or parts[7] not in STATUSES:
                    return bad
                attrs, high, low, th, tl, error, count, crc = _numbers(parts[2:7]+parts[8:])
                if count > FILE_LIMIT:
                    return bad
                if parts[7] == "copied":
                    if attrs & (0x2000 | 0x10) or high or low > FILE_LIMIT or error or count != low:
                        return bad
                    data = _read(folder / "files" / parts[1], FILE_LIMIT)
                    if len(data) != count or zlib.crc32(data) != crc:
                        return bad
                    hashes[parts[1]] = hashlib.sha256(data).hexdigest()
                elif crc:
                    return bad
                elif parts[7] == "attrs-error" and any((attrs, high, low, th, tl, count)):
                    return bad
            elif parts[0] == "D":
                if len(parts) != 10 or parts[1] not in DIRECTORIES:
                    return bad
                values = _numbers(parts[2:])
                if values[2] not in (0, 1):
                    return bad
            elif parts[0] in ("P", "C"):
                if len(parts) != 7 or parts[1] not in PROCESS_STATES or parts[0] in processes:
                    return bad
                error, wait, valid, code, marker = _numbers(parts[2:])
                if valid not in (0, 1) or marker not in (0, 1):
                    return bad
                if parts[1] == "exited" and (error or wait or valid != 1):
                    return bad
                if parts[1] == "timeout" and (error or wait != 258 or valid or code):
                    return bad
                if not valid and code:
                    return bad
                processes[parts[0]] = {"status": parts[1], "error": error, "wait": wait,
                                         "exit_valid": bool(valid), "exit": code, "marker": bool(marker)}
            else:
                return bad
        if {label for kind, label in seen if kind == "F"} != set(LABELS) \
                or {label for kind, label in seen if kind == "D"} != set(DIRECTORIES) \
                or set(processes) != {"P", "C"}:
            return bad
        matches = []
        for name in DECODER_FILES:
            digest = hashes.get("active-"+name)
            expect = job.params["expected"][name]
            matches.append({which for which in ("old", "new")
                            if digest and digest == expect[which+"_sha256"]})
        state = ("candidate" if all("new" in x for x in matches) else
                 "stock" if all("old" in x for x in matches) else
                 "mixed" if all(matches) else "unknown")
        return {"complete": True, "decoder": state, "hashes": hashes, "processes": processes}
    except (OSError, ValueError, IndexError, KeyError, TypeError, UnicodeError):
        return bad


def summary(folder: Path, job: Job) -> str:
    result = analyze(folder, job)
    if not result["complete"]:
        return "decoder inspection NOT verified: incomplete or invalid native evidence"
    probe = result["processes"]["P"]
    script = ("marker observed after clean exit" if probe["status"] == "exited" and
              probe["wait"] == 0 and probe["error"] == 0 and probe["exit_valid"] and
              probe["exit"] == 0 and probe["marker"] else
              f"unresolved ({probe['status']})")
    return (f"decoder files currently on disk: {result['decoder']}; fresh script probe: {script}. "
            "This does not identify DLLs loaded by a running AutoKit or change the earlier job verdict.")
