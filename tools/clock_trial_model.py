"""INERT clock-trial rehearsal. No device access, native code, job packer or live backend.

All example identities, operating points, temperatures and limits are synthetic.
Intents describe a future verified adapter's work; nothing dispatches them.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class OperatingState:
    opp: str
    mhz: int
    rail_profile: str
    domain_profile: str
    policy: str


def next_point(points: list[OperatingState], baseline: OperatingState, ceiling_mhz: int) -> OperatingState:
    """Select only a supplied point; the caller's table/ceiling are not hardware qualification."""
    if not 1 <= len(points) <= 16 or baseline not in points \
            or type(ceiling_mhz) is not int or ceiling_mhz <= baseline.mhz:
        raise ValueError("invalid table, baseline or ceiling")
    if len({p.opp for p in points}) != len(points) or len({p.mhz for p in points}) != len(points) \
            or any(type(p.mhz) is not int or p.mhz <= 0 for p in points):
        raise ValueError("ambiguous or invalid operating-point table")
    candidates = [p for p in points if baseline.mhz < p.mhz <= ceiling_mhz]
    if not candidates:
        raise ValueError("no supplied higher operating point within the trial ceiling")
    return min(candidates, key=lambda p: p.mhz)


@dataclass(frozen=True)
class Plan:
    evidence_digest: str  # binding only: a hash does not prove the evidence's claims
    baseline: OperatingState
    target: OperatingState
    duration_ms: int = 30000
    sample_max_age_ms: int = 1500
    call_timeout_ms: int = 1000
    max_temp_c: float = 80.0  # SYNTHETIC fixture threshold, not a Ford/i.MX51 limit
    max_rise_c: float = 5.0   # SYNTHETIC fixture threshold

    def __post_init__(self):
        if not re.fullmatch(r"[0-9a-f]{64}", self.evidence_digest):
            raise ValueError("missing evidence binding")
        next_point([self.baseline, self.target], self.baseline, self.target.mhz)
        if any(type(v) is not int or not 0 < v <= 30000 for v in
               (self.duration_ms, self.sample_max_age_ms, self.call_timeout_ms)) \
                or max(self.sample_max_age_ms, self.call_timeout_ms) > self.duration_ms \
                or not finite(self.max_temp_c) or not finite(self.max_rise_c) or self.max_rise_c <= 0:
            raise ValueError("invalid model limits")

    @property
    def digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class Sample:
    observed_ms: int
    state: OperatingState
    temp_c: float | None
    healthy: bool = True
    journal_ok: bool = True


class Trial:
    """Pure event model; complete() means the operation settled AND independent readback arrived.

    An expired pending call remains unresolved. No concurrent undo/retry is emitted.
    State tokens stand for the entire rail/domain/policy snapshot, not just CPU MHz.
    """
    def __init__(self, plan: Plan):
        self.plan = plan
        self.state = "prepared"
        self.now = 0
        self.deadline = None
        self.pending = None
        self.pending_action = None
        self.sent_at = 0
        self.last_sample = 0
        self.initial_temp = None
        self.reason = ""
        self.lost = False
        self.intents = []
        self.trace = []

    def _log(self, event: str, **details):
        # The examples are bounded. The live journal, if implemented, needs its own durable ACK.
        self.trace.append({"simulation_only": True, "ms": self.now, "event": event,
                           "state": self.state, **details})

    def _request(self, action: str):
        assert self.pending is None
        self.pending = f"operation-{len(self.intents) + 1}"
        self.pending_action = action
        self.sent_at = self.now
        target = self.plan.target if action == "request_target" else self.plan.baseline
        self.intents.append({"operation": self.pending, "action": action,
                             "state": asdict(target), "simulation_only": True})
        self.state = "applying" if action == "request_target" else "restoring"
        self._log("intent", operation=self.pending, action=action)

    def _fail(self, reason: str):
        self.reason = self.reason or reason
        if self.state == "prepared":
            self.state = "refused"
        elif self.pending is not None:
            self.state = "unresolved"
        elif self.state == "active":
            self._request("restore_baseline")
        self._log("fault", reason=reason)

    def _time(self, now: int) -> bool:
        if self.lost:
            return False
        if type(now) is not int or now < self.now:
            self._fail("invalid_monotonic_time")
            return False
        self.now = now
        return True

    def _sample_ok(self, sample: Sample, expected: OperatingState) -> bool:
        return (type(sample.observed_ms) is int and self.last_sample <= sample.observed_ms <= self.now
                and self.now - sample.observed_ms <= self.plan.sample_max_age_ms
                and sample.healthy is True and sample.journal_ok is True and sample.state == expected
                and finite(sample.temp_c) and sample.temp_c < self.plan.max_temp_c
                and (self.initial_temp is None or sample.temp_c - self.initial_temp < self.plan.max_rise_c))

    def start(self, now: int, sample: Sample, simulation_approval: str, *, journal_ready: bool):
        if self.state != "prepared":
            raise ValueError("a trial can start only once; interrupted trials cannot auto-reapply")
        if not self._time(now):
            return
        if simulation_approval != "SIMULATION:" + self.plan.digest or journal_ready is not True \
                or not self._sample_ok(sample, self.plan.baseline):
            self._fail("preflight_refused")
            return
        self.initial_temp = sample.temp_c
        self.last_sample = sample.observed_ms
        self.deadline = now + self.plan.duration_ms  # starts BEFORE requesting the target
        self._log("baseline", sample=asdict(sample), trial_digest=self.plan.digest)
        self._request("request_target")

    def complete(self, now: int, operation: str, ok: bool, observed: OperatingState | None):
        if not operation or operation != self.pending:
            raise ValueError("unknown or duplicate operation completion")
        if not self._time(now):
            return
        action = self.pending_action
        late = now - self.sent_at >= self.plan.call_timeout_ms
        if observed is None:
            # A reply without independent readback does not satisfy complete()'s contract.
            # Keep the same operation outstanding; never send a second hardware intent.
            self._fail("readback_missing")
            return
        self.pending = self.pending_action = None  # explicit settled-call/readback event
        self._log("completion", operation=operation, ok=ok,
                  observed=asdict(observed) if observed is not None else None)
        if action == "restore_baseline":
            self.state = "restored" if ok is True and observed == self.plan.baseline and not late else "unresolved"
            self._log("restoration_checked", late=late)
        elif ok is True and observed == self.plan.target and not self.reason and not late \
                and now < self.deadline and now - self.last_sample <= self.plan.sample_max_age_ms:
            self.state = "active"
            self._log("target_checked")
        else:
            self.reason = self.reason or "apply_failed_late_or_mismatched"
            self._request("restore_baseline")

    def observe(self, now: int, sample: Sample):
        if not self._time(now):
            return
        checking_apply = self.pending_action == "request_target"
        if self.state != "active" and not checking_apply:
            return
        data = asdict(sample)
        if sample.temp_c is not None and not finite(sample.temp_c):
            data.update(temp_c=None, temperature_invalid=True)
        self._log("telemetry", sample=data)
        # A fresh arrival must not erase an already missed sample deadline.
        self.tick(now)
        if self.state != "active" and not checking_apply:
            return
        expected = (self.plan.baseline, self.plan.target) if checking_apply else (self.plan.target,)
        if not any(self._sample_ok(sample, state) for state in expected):
            self._fail("telemetry_or_stability_fault")
        else:
            self.last_sample = sample.observed_ms

    def tick(self, now: int):
        if not self._time(now):
            return
        if self.pending and (now - self.sent_at >= self.plan.call_timeout_ms
                             or self.pending_action == "request_target" and now >= self.deadline):
            self._fail("pending_call_timeout")
        elif self.pending_action == "request_target" and now - self.last_sample > self.plan.sample_max_age_ms:
            self._fail("telemetry_missing_during_apply")
        elif self.state == "active":
            if now >= self.deadline:
                self._fail("trial_deadline")
            elif now - self.last_sample > self.plan.sample_max_age_ms:
                self._fail("telemetry_missing")

    def cancel(self, now: int):
        if self._time(now) and self.state not in ("restored", "refused"):
            self._fail("cancelled")

    def controller_lost(self, now: int):
        if self._time(now):
            self.lost = True
            self.state = "unresolved"
            self._log("controller_lost_no_software_recovery_guarantee")

    def artifact(self) -> dict:
        return {"mode": "simulation_only", "deployable": False, "trial_digest": self.plan.digest,
                "state": self.state, "reason": self.reason, "intents": self.intents, "trace": self.trace}


def example_plan() -> Plan:
    baseline = OperatingState("sim-600", 600, "synthetic-stock-rails", "synthetic-stock-domains", "original-policy")
    target = OperatingState("sim-667", 667, "synthetic-target-rails", "synthetic-target-domains", "temporary-request")
    return Plan(digest({"fixture": "synthetic; no Ford evidence or user GO"}), baseline, target)


def write_examples(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier run
    plan = example_plan()
    common = {"mode": "simulation_only", "deployable": False, "live_backend": "not implemented",
              "warning": "Synthetic points, temperatures and limits; not Ford operating settings or user approval."}
    trial = {**common, "trial_digest": plan.digest, "plan": asdict(plan)}
    undo = {**common, "bound_trial_digest": plan.digest, "evidence_digest": plan.evidence_digest,
            "restore_state": asdict(plan.baseline), "require_matching_full_readback": True,
            "if_controller_or_driver_unresponsive": "unresolved; no automatic recovery guarantee"}
    (destination / "trial-plan.json").write_text(json.dumps(trial, indent=2) + "\n")
    (destination / "undo-plan.json").write_text(json.dumps(undo, indent=2) + "\n")
    for scenario in ("deadline", "temperature", "lost_telemetry", "blocked_apply", "late_apply",
                     "restore_failure", "cancel", "controller_loss"):
        run = Trial(plan)
        run.start(0, Sample(0, plan.baseline, 40.0), "SIMULATION:" + plan.digest, journal_ready=True)
        if scenario in ("blocked_apply", "late_apply"):
            operation = run.pending
            run.tick(plan.call_timeout_ms)
            if scenario == "late_apply":
                run.complete(plan.call_timeout_ms + 1, operation, True, plan.target)
        else:
            run.complete(100, run.pending, True, plan.target)
            if scenario == "temperature":
                run.observe(200, Sample(200, plan.target, 81.0))
            elif scenario == "lost_telemetry":
                run.tick(2000)
            elif scenario in ("restore_failure", "cancel"):
                run.cancel(200)
            elif scenario == "controller_loss":
                run.controller_lost(200)
            else:
                for now in range(1000, plan.duration_ms, 1000):
                    run.observe(now, Sample(now, plan.target, 40.0))
                run.tick(plan.duration_ms)
        if run.state == "restoring":
            run.complete(run.now + 100, run.pending, scenario != "restore_failure", plan.baseline)
        (destination / f"{scenario}.json").write_text(json.dumps(run.artifact(), indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="fresh directory for synthetic trial/undo and fault traces")
    args = parser.parse_args()
    write_examples(args.out)
    print(f"Offline model artifacts: {args.out}; no live backend or install pack.")
