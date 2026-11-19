"""Inspect S2AM-PAIR user-mode throughput, not physical CPU frequency."""
import argparse
import json
import re
from pathlib import Path
from statistics import mean, median

LIMIT = 16384
SCHEDULES = {
    b"S2AM-PAIR,1": (1, (16384,) * 4 + (32768,) * 4),
    b"S2AM-PAIR,2": (2, (16384, 32768, 32768, 16384) * 2),
}


def number(field):
    if not re.fullmatch(rb"0|[1-9][0-9]{0,19}", field):
        raise ValueError("invalid unsigned decimal")
    value = int(field)
    if value >= 1 << 64:
        raise ValueError("counter out of range")
    return value


def analyze(body: bytes) -> dict:
    if len(body) > LIMIT:
        raise ValueError("capture too large")
    rows = body.split(b"\r\n")
    if (len(rows) != 36 or rows[0] not in SCHEDULES
            or rows[-2:] != [b"complete,32", b""]):
        raise ValueError("incomplete or unknown capture")
    version, schedule = SCHEDULES[rows[0]]
    freq = rows[1].split(b",")
    if len(freq) != 2 or freq[0] != b"qpf" or not (qpf := number(freq[1])):
        raise ValueError("invalid timer frequency")
    blocks = []
    last = 0
    for b, n in enumerate(schedule):
        widths = (64, 32, 32, 64) if b % 2 else (32, 64, 64, 32)
        diff = 0
        windows = []
        for slot, width in enumerate(widths):
            rec = rows[2 + 4*b + slot].split(b",")
            if len(rec) != 7 or rec[0] != b"sample":
                raise ValueError("invalid sample")
            block, index, rounds, adds, start, end = map(number, rec[1:])
            if (block, index, rounds, adds) != (b, slot, n, width):
                raise ValueError("unexpected measurement order")
            if not start or start < last or end <= start:
                raise ValueError("invalid counter interval")
            last = end
            elapsed = end - start
            diff += elapsed if width == 64 else -elapsed
            windows.append({"width": width, "start": start, "end": end, "ticks": elapsed})
        blocks.append({"block": b, "rounds": n, "windows": windows,
                       "extra_ticks_per_round": diff / (2*n)})
    effects = [b["extra_ticks_per_round"] for b in blocks]
    if min(effects) <= 0:
        status = "nonpositive"
    elif max(effects) - min(effects) > 0.01 * median(effects):
        status = "noisy"
    else:
        status = "coherent"
    # V1 runs larger blocks last; V2 balances size against order and position.
    size_means = [mean(e for n, e in zip(schedule, effects) if n == size)
                  for size in (16384, 32768)]
    return {"version": version, "qpf": qpf, "blocks": blocks, "status": status,
            "order_delta": abs(mean(effects[::2]) - mean(effects[1::2])),
            "size_delta": abs(size_means[0] - size_means[1]),
            "qualified": False, "cpu_rate_qualified": False, "write_authorized": False}


def read_result(path: Path) -> dict:
    if path.name.upper() != "RESULT.CSV":
        raise ValueError("expected published RESULT.CSV, not a scratch file")
    with path.open("rb") as stream:
        return analyze(stream.read(LIMIT + 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    try:
        result = read_result(args.capture)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Invalid capture: {exc}\n")
    print(json.dumps(result, indent=2))
