"""Validate fixed native PLL1/CCM snapshots; raw registers are not a frequency measurement."""
from pathlib import Path

from .decoder_inspect import _read, _numbers

PLL = (0, 4, 8, 12, 16, 28, 32, 36, 40, 44)
CCM = (0, 8, 12, 16, 20, 24, 28, 32, 72, 76, 84)
EXPECTED = tuple((sample, block, offset) for sample in (1, 2)
                 for block, offsets in (("ccm-before", CCM), ("pll1", PLL), ("ccm-after", CCM))
                 for offset in offsets)


def analyze(path: Path, child: dict) -> dict:
    bad = {"complete": False, "stable": False}
    if not (child.get("status") == "exited" and child.get("exit_valid") is True
            and child.get("exit") == 0 and child.get("wait") == 0
            and child.get("error") == 0 and child.get("marker") is True):
        return bad
    try:
        lines = _read(path, 32768).decode("ascii").splitlines()
        if len(lines) > 512 or lines[0] != "S|s2am-clock-v1" or lines[-1] != "T|complete":
            return bad
        values = {}
        for line in lines[1:-1]:
            parts = line.split("|")
            if parts[0] == "B" and len(line) <= 200:
                continue  # progress is informative, never evidence of a register value
            if len(parts) != 5 or parts[0] != "R":
                return bad
            sample, offset, value = _numbers([parts[1], parts[3], parts[4]])
            key = sample, parts[2], offset
            if key not in EXPECTED or key in values:
                return bad
            values[key] = value
        if set(values) != set(EXPECTED):
            return bad
        ccm = {offset: values[1, "ccm-before", offset] for offset in CCM}
        pll = {offset: values[1, "pll1", offset] for offset in PLL}
        stable = all(values[sample, block, offset] == ccm[offset]
                     for sample in (1, 2) for block in ("ccm-before", "ccm-after") for offset in CCM)
        stable = stable and all(values[2, "pll1", offset] == pll[offset] for offset in PLL)
        stable = stable and ccm[72] == 0  # no divider/source handshake outstanding
        result = {"complete": True, "stable": stable, "ccm": ccm, "pll1": pll}
        if stable:
            # NXP AN4140 / i.MX51 CCM definitions. No PLL2 reading: do not infer DDR MHz.
            selector = (ccm[24] >> 10) & 3
            result["ddr_source"] = "PLL1 high-frequency" if ccm[20] & (1 << 30) else (
                "AXI_A" if selector == 0 else f"DDR mux input {selector}")
            result["arm_divider"] = (ccm[16] & 7) + 1
            result["arm_source"] = "step clock" if ccm[12] & 4 else "PLL1"
        return result
    except (OSError, ValueError, IndexError, UnicodeError):
        return bad


def summary(path: Path, child: dict) -> str:
    result = analyze(path, child)
    if not result["complete"]:
        return "clock snapshot NOT verified: inspect clock.txt and the native child status"
    if not result["stable"]:
        return "clock snapshot captured, but changed or busy; no stable clock interpretation"
    return (f"clock snapshot: 64 fixed register reads agree; ARM source {result['arm_source']}, "
            f"divider {result['arm_divider']}; DDR route {result['ddr_source']}. "
            "No measured MHz, voltage/temperature result or overclock.")
