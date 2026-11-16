"""Bounded artifact loading and evidence import for the isolated clock reader."""
import hashlib
import json
import re
import zlib
from pathlib import Path

from . import clock_snapshot, native
from .decoder_inspect import _numbers, _read
from .job import Job, validate

BINARIES = ("s2amclkdrv.dll", "s2amclockctl.exe", "s2amclockjob.exe")
SOURCES = ("s2amclkdrv.c", "s2amclkdrv.def", "s2amclockctl.c", "s2amclockjob.c", "clock_probe_protocol.h")


def _hashes(value, names):
    return isinstance(value, dict) and set(value) == set(names) and all(
        isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in value.values())


def artifacts(folder: Path) -> tuple[dict, dict[str, bytes]]:
    """Load an already built server bundle; this path never starts a compiler/container."""
    manifest = json.loads(_read(folder / "manifest.json", 8192))
    if manifest.get("format") != "s2am-clock-artifacts-v1" or not _hashes(manifest.get("sources"), SOURCES) \
            or not _hashes(manifest.get("binaries"), BINARIES):
        raise ValueError("invalid clock artifact manifest")
    for name in SOURCES:
        if hashlib.sha256((native.SOURCES / name).read_bytes()).hexdigest() != manifest["sources"][name]:
            raise ValueError(f"clock artifact source differs: {name}; rebuild on ant-srv-001")
    payload = {}
    for name in BINARIES:
        body = _read(folder / name, 1024 * 1024)
        native.check(body, name)
        if hashlib.sha256(body).hexdigest() != manifest["binaries"][name]:
            raise ValueError(f"clock artifact hash differs: {name}")
        payload[name] = body
    if manifest["binaries"]["s2amclkdrv.dll"].encode("ascii") not in payload["s2amclockctl.exe"]:
        raise ValueError("controller is not bound to the supplied clock DLL")
    return {"artifacts": manifest["binaries"], "sources": manifest["sources"]}, payload


def validate_job(job: Job) -> None:
    validate(job)
    if job.kind != "clkdiag" or job.id.split("-")[2] != "clkdiag" or set(job.params) != {"artifacts", "sources"} \
            or not _hashes(job.params["artifacts"], BINARIES) or not _hashes(job.params["sources"], SOURCES):
        raise ValueError("clock inspection requires the exact bound diagnostic artifact set")


def analyze(folder: Path, job: Job) -> dict:
    bad = {"complete": False, "snapshot": {"complete": False, "stable": False}}
    try:
        validate_job(job)
        if folder.is_symlink() or _read(folder / "done.txt", 128).decode("ascii") != job.id:
            return bad
        lines = _read(folder / "clock-job.txt", 4096).decode("ascii").splitlines()
        if len(lines) != 5 or lines[0] != f"S|s2am-clock-job-v1|{job.id}" \
                or lines[1] != "B|launch" or lines[-1] != "T|complete":
            return bad
        child, copied = lines[2].split("|"), lines[3].split("|")
        if len(child) != 6 or child[0] != "C" or child[1] not in {
                "launch-error", "exited", "exit-error", "timeout", "wait-error", "handle-error"}:
            return bad
        error, wait, valid, code = _numbers(child[2:])
        if valid not in (0, 1) or (not valid and code) \
                or (child[1] == "exited" and (error or wait or not valid)) \
                or (child[1] == "timeout" and (error or wait != 258 or valid or code)):
            return bad
        if len(copied) != 4 or copied[0] != "J" or copied[1] not in {"copied", "missing", "copy-error"}:
            return bad
        size, crc = _numbers(copied[2:])
        if size > 32768 or (copied[1] != "copied" and crc) or (copied[1] == "missing" and size):
            return bad
        if copied[1] == "copied":
            body = _read(folder / "clock-user-driver.txt", 32768)
            if len(body) != size or zlib.crc32(body) != crc:
                return bad
        state = {"status": child[1], "error": error, "wait": wait, "exit_valid": bool(valid),
                 "exit": code, "marker": copied[1] == "copied"}
        snapshot = clock_snapshot.analyze(folder / "clock-user-driver.txt", state)
        return {"complete": True, "child": state, "copy": copied[1], "snapshot": snapshot}
    except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError):
        return bad


def summary(folder: Path, job: Job) -> str:
    result = analyze(folder, job)
    if not result["complete"]:
        return "clock inspection incomplete or invalid; preserve local/USB evidence and do not replay"
    if not result["snapshot"]["complete"]:
        return (f"clock inspection collected; controller {result['child']['status']}, "
                f"exit {result['child']['exit'] if result['child']['exit_valid'] else 'unknown'}. "
                "No verified snapshot; preserve activation state and do not retry")
    return clock_snapshot.summary(folder / "clock-user-driver.txt", result["child"])
