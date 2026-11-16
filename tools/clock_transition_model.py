"""INERT MFN-only transition contract; no device access, backend or install job.

The current Ford candidate is always blocked. Only explicitly synthetic fixtures
exercise operations. Names below describe proof obligations, not hardware calls.

NXP MCIMX51RM Rev. 1, sections 22.3.3.1/22.3.3.2 and Tables 22-2/22-3:
MFN alone can change after lock without restart. LDREQ clears when hardware
finishes; software cannot cancel it by writing zero. LRF is sticky. Rewriting
OP/MFD/CTL can restart the PLL, even with identical values, so restoration changes
only the owned MFN and verifies the entire baseline afterwards.
The separate clock_trial_model.py covers trial deadlines and thermal faults.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path

SOURCES = {
    "pll_update": "https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf",
    "clock_equation": "https://www.nxp.com/docs/en/application-note/AN4140.pdf#page=3",
    "silicon_errata": "https://www.nxp.com/docs/en/errata/IMX51CE.pdf",
}
REQUIREMENTS = (
    "exact_device_and_firmware", "silicon_grade_revision_and_errata",
    "live_reference_source_and_divider", "live_pll_output_factor",
    "live_active_parameter_bank", "live_pll_lock_mode_and_autorestart",
    "live_desense_disabled", "live_no_pending_load_request",
    "arm_source_and_divider", "ddr_source_and_divider",
    "axi_ahb_and_all_other_pll1_consumers", "exclusive_clock_policy_ownership",
    "suspend_resume_exclusion", "active_rail_and_loaded_voltage",
    "independent_frequency_timebase", "thermal_observation_and_limits",
    "independent_recovery", "qualified_mfn_only_transition_and_restore",
    "durable_ownership_and_journal",
)


def unresolved(evidence: dict[str, str]) -> list[str]:
    if set(evidence) - set(REQUIREMENTS) or any(value not in ("met", "unmet", "unknown")
                                               for value in evidence.values()):
        raise ValueError("unknown evidence field or invalid evidence status")
    return [name for name in REQUIREMENTS if evidence.get(name) != "met"]


def candidate_spec() -> dict:
    """Record current unknowns; a boot arithmetic example never supplies live evidence."""
    return {
        "mode": "simulation_only", "deployable": False, "state": "blocked",
        "candidate_nominal_mhz": 624, "baseline_nominal_mhz": 600,
        "arithmetic_only": "4 * 24 * (6 + MFN / 4); MFN 1 -> 600, MFN 2 -> 624",
        "qualification": "No live PLL baseline, transition, thermal or recovery proof",
        "evidence": {name: "unknown" for name in REQUIREMENTS},
        "unresolved": list(REQUIREMENTS), "operations": [], "sources": SOURCES,
        "method_to_investigate": "active MFN only, hardware-completed LDREQ and independent observation",
        "restore_contract": "restore owned MFN, then verify full baseline; never replay a raw register dump",
        "timeout_contract": "pending/unresolved; no LDREQ cancellation, concurrent undo or automatic retry",
    }


@dataclass(frozen=True)
class ClockState:
    """Synthetic full-state tokens; they are not a firmware register map."""
    mfn: int
    mfd: int
    bank: str
    reference: str
    pll_configuration: str
    arm_source: str
    arm_divider: int
    ddr_source: str
    ddr_divider: int
    other_consumers: str
    rail: str
    policy: str
    suspend: str


@dataclass(frozen=True)
class Readback:
    observed_ms: int
    state: ClockState
    measured_mhz: int | None
    load_pending: bool = False
    lock_flag: bool = True  # deliberately insufficient; it is not a fresh lock observation


@dataclass(frozen=True)
class Operation:
    id: str
    action: str
    issued_ms: int
    owned_fields: tuple[str, ...]


class Rehearsal:
    """Validate a synthetic trace; never dispatch any operation.

    Staging MFN is already a mutation. A pending request remains owned until a
    settled operation and fresh full readback/measurement establish its outcome.
    The 100 ms / 20 ms limits below are test fixtures, not qualified car timings.
    """
    def __init__(self, evidence: dict[str, str]):
        self.evidence = dict(evidence)
        unresolved(self.evidence)
        self.baseline = ClockState(1, 3, "normal", "synthetic-24mhz-div1",
                                   "synthetic-locked-mode-desense-off", "pll1", 1,
                                   "synthetic-pll2", 4, "synthetic-no-other-pll1-consumers",
                                   "synthetic-unchanged-rail", "synthetic-exclusive-owner",
                                   "synthetic-suspend-excluded")
        self.target = replace(self.baseline, mfn=2)
        self.state = "prepared"
        self.now = 0
        self.pending: Operation | None = None
        self.operations: list[Operation] = []
        self.last_observed: Readback | None = None
        self.reason = ""
        self.phase_faulted = False
        self.lost = False
        self.expected_state = self.baseline
        self.expected_mhz = 600
        self.trace = []

    def _time(self, now: int):
        if self.lost or type(now) is not int or now < self.now:
            raise ValueError("controller unavailable or invalid monotonic time")
        self.now = now

    def _observed(self, observed: Readback | None, expected: ClockState, mhz: int) -> bool:
        return (isinstance(observed, Readback) and type(observed.observed_ms) is int
                and (self.pending is None or observed.observed_ms >= self.pending.issued_ms)
                and 0 <= self.now - observed.observed_ms <= 20
                and observed.state == expected and observed.load_pending is False
                and observed.lock_flag is True  # necessary, but never sufficient by itself
                and type(observed.measured_mhz) is int and observed.measured_mhz == mhz)

    def _issue(self, action: str, state: ClockState, mhz: int):
        if self.pending is not None or len(self.operations) >= 4:
            raise ValueError("pending operation or operation bound reached")
        owned = ("active_mfn",) if action.startswith("stage_") else ("load_request",)
        self.pending = Operation(f"operation-{len(self.operations) + 1}", action, self.now, owned)
        self.operations.append(self.pending)
        self.expected_state, self.expected_mhz = state, mhz
        self.phase_faulted = False
        self.state = "pending"
        self.trace.append({"event": "synthetic_intent", **asdict(self.pending)})

    def start(self, now: int, observed: Readback, *, journal_ready: bool):
        if self.state != "prepared":
            raise ValueError("a rehearsal cannot start twice")
        self._time(now)
        if unresolved(self.evidence) or journal_ready is not True or not self._observed(observed, self.baseline, 600):
            self.state, self.reason = "refused", "preflight_unresolved"
            return
        self.last_observed = observed
        self._issue("stage_target_mfn", self.target, 600)

    def fault(self, now: int, reason: str):
        self._time(now)
        if not isinstance(reason, str) or not 1 <= len(reason) <= 100:
            raise ValueError("invalid fault reason")
        self.reason = self.reason or reason
        self.phase_faulted = True
        self.state = "unresolved" if self.pending or self.state != "active" else "restore_required"

    def tick(self, now: int):
        if self.lost:
            return
        self._time(now)
        if self.pending and now - self.pending.issued_ms >= 100:
            self.fault(now, "pending_timeout")

    def complete(self, now: int, operation: str, *, settled: bool, observed: Readback | None):
        if self.pending is None or operation != self.pending.id:
            raise ValueError("unknown or duplicate operation completion")
        self._time(now)
        self.tick(now)
        if settled is not True or not self._observed(observed, self.expected_state, self.expected_mhz):
            self.fault(now, "settlement_or_fresh_full_readback_missing")
            return  # retain ownership; LDREQ=0 software writes cannot cancel a request
        action = self.pending.action
        self.pending = None
        self.last_observed = observed
        self.trace.append({"event": "observed_settlement", "action": action, "ms": now,
                           "readback": asdict(observed), "phase_faulted": self.phase_faulted})
        if action == "request_baseline_load":
            self.state = "unresolved" if self.phase_faulted else "restored"
        elif action == "stage_baseline_mfn":
            if self.phase_faulted:
                self.state = "unresolved"
            else:
                self._issue("request_baseline_load", self.baseline, 600)
        elif self.phase_faulted:
            self.state = "restore_required"
        elif action == "stage_target_mfn":
            self._issue("request_target_load", self.target, 624)
        else:
            self.state = "active"

    def restore(self, now: int, observed: Readback, *, journal_ready: bool):
        if self.pending is not None or self.state not in ("active", "restore_required") or self.last_observed is None:
            raise ValueError("restoration requires known quiescence and retained ownership")
        self._time(now)
        if journal_ready is not True or not self._observed(
                observed, self.last_observed.state, self.last_observed.measured_mhz):
            self.state, self.reason = "unresolved", "restore_preflight_failed"
            return
        self._issue("stage_baseline_mfn", self.baseline, observed.measured_mhz)

    def controller_lost(self, now: int):
        self._time(now)
        self.state, self.reason, self.lost = "unresolved", "controller_lost", True

    def artifact(self) -> dict:
        return {"mode": "simulation_only", "deployable": False, "fixture": "synthetic; not Ford evidence",
                "state": self.state, "reason": self.reason, "sources": SOURCES,
                "operations": [asdict(operation) for operation in self.operations],
                "pending": asdict(self.pending) if self.pending else None, "trace": self.trace}


def synthetic_rehearsal(evidence: dict[str, str] | None = None) -> Rehearsal:
    return Rehearsal({name: "met" for name in REQUIREMENTS} if evidence is None else evidence)


def write_examples(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "candidate-spec.json").write_text(json.dumps(candidate_spec(), indent=2) + "\n")
    for scenario in ("restored", "staging_loss", "pending_load", "late_load", "restore_mismatch"):
        run = synthetic_rehearsal()
        run.start(0, Readback(0, run.baseline, 600), journal_ready=True)
        if scenario == "staging_loss":
            run.controller_lost(1)
        else:
            run.complete(10, run.pending.id, settled=True, observed=Readback(10, run.target, 600))
            if scenario in ("pending_load", "late_load"):
                run.tick(110)
                if scenario == "late_load":
                    run.complete(111, run.pending.id, settled=True, observed=Readback(111, run.target, 624))
            else:
                run.complete(20, run.pending.id, settled=True, observed=Readback(20, run.target, 624))
                run.restore(30, Readback(30, run.target, 624), journal_ready=True)
                run.complete(40, run.pending.id, settled=True, observed=Readback(40, run.baseline, 624))
                final = replace(run.baseline, rail="wrong-rail") if scenario == "restore_mismatch" else run.baseline
                run.complete(50, run.pending.id, settled=True, observed=Readback(50, final, 600))
        (destination / f"trace-{scenario}.json").write_text(json.dumps(run.artifact(), indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory for inert specification and traces")
    write_examples(parser.parse_args().out)
    print("Wrote blocked candidate specification and synthetic traces; no live backend or install pack.")
