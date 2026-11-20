"""Read-only host parser for the S2AM-LOAD,1 raw load observer journal.

Frozen wire format and interpretation rules live in docs/LOAD-OBSERVER-V1.md
(lead-owned). This module reports observed CPU-time distribution and coverage
only: never physical MHz, inferred decoder identity or a causal bottleneck
claim, and never a clock-control observation. Every field is bounded and the
journal is untrusted text; malformed, truncated, extra or reordered rows raise
ValueError. A complete file may still contain partial observations.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import re

from .decoder_inspect import _read

MAX_BYTES = 8 * 1024 * 1024
MAX_LINES = 50_000
MAX_LINE_BYTES = 256
ROUNDS = 60
SLEEP_MS = 5000
THREAD_CAP = 512
PROCESS_CAP = 256
QPC_MAX = (1 << 63) - 1
FILETIME_MAX = (1 << 64) - 1
DWORD_MAX = (1 << 32) - 1
QPF_MIN = 1
QPF_MAX = 1_000_000_000
IDLE_SENTINEL = 0xFFFFFFFF
STATUSES = ("ok", "open_fail", "times_fail", "no_creation")

_UINT = re.compile(r"0|[1-9][0-9]*")
_PRIORITY = re.compile(r"0|[1-9][0-9]*|-[1-9][0-9]*")
_BASENAME = re.compile(r"[A-Za-z0-9_.?-]{1,63}")
_PRIORITY_MIN = -(1 << 31)
_PRIORITY_MAX = (1 << 31) - 1


def _uint(text, maximum):
    if not _UINT.fullmatch(text):
        raise ValueError("non-canonical unsigned number")
    value = int(text)
    if value > maximum:
        raise ValueError("unsigned number out of range")
    return value


def _qpc(text):
    return _uint(text, QPC_MAX)


def _filetime(text):
    return _uint(text, FILETIME_MAX)


def _dword(text):
    return _uint(text, DWORD_MAX)


def _priority(text):
    if not _PRIORITY.fullmatch(text):
        raise ValueError("non-canonical priority")
    value = int(text)
    if value < _PRIORITY_MIN or value > _PRIORITY_MAX:
        raise ValueError("priority out of range")
    return value


def _nonzero(text):
    value = _dword(text)
    if value == 0:
        raise ValueError("identifier must be nonzero")
    return value


def _flag(text):
    value = _dword(text)
    if value not in (0, 1):
        raise ValueError("flag must be 0 or 1")
    return value


def _bracket(before, after, begin, end):
    if not (0 < before <= after and begin <= before and after <= end):
        raise ValueError("QPC bracket invalid or outside its round")


def _status_fields(status, error, creation, kernel, user):
    if status not in STATUSES:
        raise ValueError("unknown observation status")
    if status == "ok":
        if creation == 0 or error != 0:
            raise ValueError("ok requires nonzero creation and zero error")
    elif status == "no_creation":
        if creation != 0 or error != 0:
            raise ValueError("no_creation requires zero creation and error")
    else:  # open_fail / times_fail
        if creation != 0 or kernel != 0 or user != 0:
            raise ValueError("failed observation requires zero counters")


def _lines(body):
    if not isinstance(body, bytes):
        raise ValueError("journal must be bytes")
    if len(body) > MAX_BYTES:
        raise ValueError("oversized journal")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("non-ASCII journal") from error
    if not text.endswith("\r\n"):
        raise ValueError("journal must end with CRLF")
    lines = text[:-2].split("\r\n")
    if len(lines) > MAX_LINES:
        raise ValueError("too many journal lines")
    for line in lines:
        if len(line.encode("ascii")) + 2 > MAX_LINE_BYTES:
            raise ValueError("journal line too long")
        if "\r" in line or "\n" in line or " " in line or line == "":
            raise ValueError("malformed journal line")
    return lines


def _fields(line, kind, count):
    parts = line.split(",")
    if parts[0] != kind or len(parts) != count:
        raise ValueError(f"expected {kind} row with {count} fields")
    return parts[1:]


def _parse_self(parts, seq, begin, end):
    if _dword(parts[0]) != seq:
        raise ValueError("self seq mismatch")
    creation = _filetime(parts[1])
    kernel = _filetime(parts[2])
    user = _filetime(parts[3])
    before = _qpc(parts[4])
    after = _qpc(parts[5])
    status = parts[6]
    error = _dword(parts[7])
    _bracket(before, after, begin, end)
    _status_fields(status, error, creation, kernel, user)
    return {"creation": creation, "kernel": kernel, "user": user,
            "before": before, "after": after, "status": status, "error": error}


def _parse_idle(parts, seq, begin, end):
    if _dword(parts[0]) != seq:
        raise ValueError("idle seq mismatch")
    ok = _flag(parts[1])
    before = _qpc(parts[2])
    after = _qpc(parts[3])
    value = _dword(parts[4])
    error = _dword(parts[5])
    _bracket(before, after, begin, end)
    if ok == 1 and (error != 0 or value == IDLE_SENTINEL):
        raise ValueError("ok idle requires zero error and non-sentinel value")
    return {"ok": ok, "before": before, "after": after,
            "value": value, "error": error}


def _parse_thread(parts, seq, begin, end):
    if _dword(parts[0]) != seq:
        raise ValueError("thread seq mismatch")
    pid = _nonzero(parts[1])
    tid = _nonzero(parts[2])
    creation = _filetime(parts[3])
    kernel = _filetime(parts[4])
    user = _filetime(parts[5])
    before = _qpc(parts[6])
    after = _qpc(parts[7])
    base = _priority(parts[8])
    delta = _priority(parts[9])
    status = parts[10]
    error = _dword(parts[11])
    _bracket(before, after, begin, end)
    _status_fields(status, error, creation, kernel, user)
    return {"pid": pid, "tid": tid, "creation": creation, "kernel": kernel,
            "user": user, "before": before, "after": after,
            "base_priority": base, "delta_priority": delta,
            "status": status, "error": error}


def _parse_round(lines, cursor, seq, prev_end):
    begin_parts = _fields(lines[cursor], "round", 8)
    if _dword(begin_parts[0]) != seq:
        raise ValueError("round seq mismatch")
    begin = _qpc(begin_parts[1])
    end = _qpc(begin_parts[2])
    if not (0 < begin <= end):
        raise ValueError("round bounds invalid")
    if prev_end is not None and begin <= prev_end:
        raise ValueError("successive rounds must not overlap")
    thread_enum_error = _dword(begin_parts[3])
    thread_truncated = _flag(begin_parts[4])
    process_enum_error = _dword(begin_parts[5])
    process_truncated = _flag(begin_parts[6])
    cursor += 1

    self_ = _parse_self(_fields(lines[cursor], "self", 9), seq, begin, end)
    cursor += 1
    idle = _parse_idle(_fields(lines[cursor], "idle", 7), seq, begin, end)
    cursor += 1

    processes = {}
    while cursor < len(lines) and lines[cursor].startswith("process,"):
        parts = _fields(lines[cursor], "process", 4)
        if _dword(parts[0]) != seq:
            raise ValueError("process seq mismatch")
        pid = _nonzero(parts[1])
        basename = parts[2]
        if not _BASENAME.fullmatch(basename):
            raise ValueError("invalid process basename")
        if pid in processes:
            raise ValueError("duplicate process pid in round")
        if len(processes) >= PROCESS_CAP:
            raise ValueError("process cap exceeded")
        processes[pid] = basename
        cursor += 1

    threads = []
    tids = set()
    while cursor < len(lines) and lines[cursor].startswith("thread,"):
        thread = _parse_thread(_fields(lines[cursor], "thread", 13), seq, begin, end)
        if thread["tid"] in tids:
            raise ValueError("duplicate thread tid in round")
        if len(threads) >= THREAD_CAP:
            raise ValueError("thread cap exceeded")
        tids.add(thread["tid"])
        threads.append(thread)
        cursor += 1

    end_parts = _fields(lines[cursor], "endround", 7)
    if _dword(end_parts[0]) != seq:
        raise ValueError("endround seq mismatch")
    attempted = _dword(end_parts[1])
    counts = {status: _dword(end_parts[2 + i]) for i, status in enumerate(STATUSES)}
    cursor += 1
    if attempted != sum(counts.values()) or attempted != len(threads):
        raise ValueError("endround counts do not match thread rows")
    for status in STATUSES:
        actual = sum(1 for thread in threads if thread["status"] == status)
        if counts[status] != actual:
            raise ValueError("endround status count mismatch")

    return cursor, {
        "seq": seq, "begin_qpc": begin, "end_qpc": end,
        "collection_latency_qpc": end - begin,
        "thread_enum_error": thread_enum_error,
        "thread_truncated": thread_truncated,
        "process_enum_error": process_enum_error,
        "process_truncated": process_truncated,
        "attempted": attempted, **counts,
        "self": self_, "idle": idle, "threads": threads, "processes": processes,
    }, end


def _share_bounds(total_delta, qpf, min_gap, max_gap):
    lower = Fraction(total_delta * qpf * 100, 10_000_000 * max_gap)
    upper = Fraction(total_delta * qpf * 100, 10_000_000 * min_gap)
    return float(lower), float(upper), lower > 100


def _cpu_interval(prev, now, from_seq, to_seq, qpf):
    min_gap = now["before"] - prev["after"]
    max_gap = now["after"] - prev["before"]
    record = {"from_seq": from_seq, "to_seq": to_seq,
              "min_gap": min_gap, "max_gap": max_gap,
              "kernel_delta": None, "user_delta": None,
              "share_lower_pct": None, "share_upper_pct": None,
              "implausible": False, "invalid": True}
    if min_gap <= 0:
        return record
    if now["kernel"] < prev["kernel"] or now["user"] < prev["user"]:
        return record  # counter regression: invalid, no modulo wrap
    kernel_delta = now["kernel"] - prev["kernel"]
    user_delta = now["user"] - prev["user"]
    lower, upper, implausible = _share_bounds(kernel_delta + user_delta, qpf,
                                              min_gap, max_gap)
    record.update(kernel_delta=kernel_delta, user_delta=user_delta,
                  share_lower_pct=lower, share_upper_pct=upper,
                  implausible=implausible, invalid=False)
    return record


def _chain(observations, qpf):
    """observations: {seq: ok-row}. Yield intervals for adjacent ok rounds."""
    intervals = []
    for seq in range(ROUNDS - 1):
        prev = observations.get(seq)
        now = observations.get(seq + 1)
        if prev is None or now is None:
            continue
        if prev["creation"] != now["creation"]:
            continue
        intervals.append(_cpu_interval(prev, now, seq, seq + 1, qpf))
    return intervals


def _interpret(rounds, qpf, self_pid, self_tid):
    identities = {}
    self_obs = {}
    idle_obs = {}
    for round_ in rounds:
        seq = round_["seq"]
        for thread in round_["threads"]:
            if thread["status"] == "ok":
                key = (thread["pid"], thread["tid"], thread["creation"])
                identities.setdefault(key, {})[seq] = thread
        if round_["self"]["status"] == "ok":
            self_obs[seq] = round_["self"]
        if round_["idle"]["ok"] == 1:
            idle_obs[seq] = round_["idle"]

    observed = []
    for (pid, tid, creation), observations in identities.items():
        for interval in _chain(observations, qpf):
            observed.append({"pid": pid, "tid": tid, "creation": creation, **interval})

    self_intervals = _chain(self_obs, qpf)

    idle_intervals = []
    for seq in range(ROUNDS - 1):
        prev = idle_obs.get(seq)
        now = idle_obs.get(seq + 1)
        if prev is None or now is None:
            continue
        min_gap = now["before"] - prev["after"]
        max_gap = now["after"] - prev["before"]
        value_delta = now["value"] - prev["value"]
        record = {"from_seq": seq, "to_seq": seq + 1,
                  "min_gap": min_gap, "max_gap": max_gap,
                  "value_delta": value_delta, "unknown": True,
                  "fraction_lower": None, "fraction_upper": None}
        if min_gap <= 0 or value_delta < 0 or value_delta * qpf > 1000 * max_gap:
            idle_intervals.append(record)
            continue
        lower = Fraction(value_delta * qpf, 1000 * max_gap)
        upper = Fraction(value_delta * qpf, 1000 * min_gap)
        record.update(unknown=False, fraction_lower=float(lower),
                      fraction_upper=float(upper))
        idle_intervals.append(record)

    partial = {
        "open_fail": sum(r["open_fail"] for r in rounds),
        "times_fail": sum(r["times_fail"] for r in rounds),
        "no_creation": sum(r["no_creation"] for r in rounds),
        "thread_truncated_rounds": sum(r["thread_truncated"] for r in rounds),
        "process_truncated_rounds": sum(r["process_truncated"] for r in rounds),
        "thread_enum_error_rounds": sum(1 for r in rounds if r["thread_enum_error"]),
        "process_enum_error_rounds": sum(1 for r in rounds if r["process_enum_error"]),
    }
    # Process basenames stay per-round in rounds[seq]["processes"]; a PID alone is
    # not a stable identity, so no global latest-basename map is published.
    return observed, self_intervals, idle_intervals, partial


def analyze(body: bytes) -> dict:
    """Strictly parse a complete S2AM-LOAD,1 journal and derive observed shares.

    Any IndexError from a truncated journal is translated to ValueError at this
    strict boundary; the contract requires ValueError for malformed/truncated input.
    """
    try:
        return _analyze(body)
    except IndexError as error:
        raise ValueError("truncated journal") from error


def _analyze(body: bytes) -> dict:
    lines = _lines(body)
    if lines[0] != "S2AM-LOAD,1":
        raise ValueError("wrong journal header")
    meta = _fields(lines[1], "meta", 7)
    if meta[0] != str(ROUNDS) or meta[1] != str(SLEEP_MS) \
            or meta[2] != str(THREAD_CAP) or meta[3] != str(PROCESS_CAP):
        raise ValueError("meta constants do not match the frozen contract")
    self_pid = _nonzero(meta[4])
    self_tid = _nonzero(meta[5])
    start = _fields(lines[2], "frequency", 3)
    if start[0] != "start":
        raise ValueError("expected frequency,start")
    qpf = _uint(start[1], QPF_MAX)
    if qpf < QPF_MIN:
        raise ValueError("qpf out of range")

    rounds = []
    cursor = 3
    prev_end = None
    for seq in range(ROUNDS):
        if cursor >= len(lines):
            raise ValueError("truncated journal: missing round")
        cursor, round_, prev_end = _parse_round(lines, cursor, seq, prev_end)
        rounds.append(round_)

    end = _fields(lines[cursor], "frequency", 3)
    if end[0] != "end" or _uint(end[1], QPF_MAX) != qpf:
        raise ValueError("frequency,end mismatch")
    cursor += 1
    complete = _fields(lines[cursor], "complete", 2)
    if _dword(complete[0]) != ROUNDS:
        raise ValueError("complete count mismatch")
    cursor += 1
    if cursor != len(lines):
        raise ValueError("extra or reordered rows after complete")

    observed, self_intervals, idle_intervals, partial = \
        _interpret(rounds, qpf, self_pid, self_tid)
    return {
        "complete": True, "qpf": qpf,
        "self_pid": self_pid, "self_tid": self_tid,
        "rounds": rounds,
        "observed_intervals": observed,
        "self_intervals": self_intervals,
        "idle_intervals": idle_intervals,
        "partial": partial,
        "qualified": False, "settled": False,
        "cpu_rate_qualified": False, "write_authorized": False,
    }


def read_result(path) -> dict:
    """Read a bounded LOAD.CSV result file and analyze it; no other basename."""
    path = Path(path)
    if path.name != "LOAD.CSV":
        raise ValueError("result basename must be LOAD.CSV")
    return analyze(_read(path, MAX_BYTES))