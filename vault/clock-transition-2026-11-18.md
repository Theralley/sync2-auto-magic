# Evidence-bound transition and restoration
The successful read-only capture now feeds an inert transition specification; no hardware clock writer is qualified or deployed.

## Captured evidence, not permission

The explicit local-job/report binder validates the preserved successful return, pins the
five report hashes, checks predecessor identity/stage order, CRC/cleanup and local artifact manifest consistency,
and rereads inputs after analysis. Actual output is **7 scoped captured facts met / 12
unknown**, blocked, non-deployable, with an empty operation list. Caller-trusted manifests
are not execution attestation, firmware identity or proof of present state.

MFN 1→2 has an exact arithmetic ratio **26/25 (+4%)** under the captured factors. Absolute
600→624 MHz still assumes a 24 MHz oscillator. EPIT/QPC coherence does not measure CPU rate.
No identical reader/timer trip is needed to obtain facts already preserved.

## Transition contract

A separate hardware-independent C coordinator is implemented and host-fault-tested.
It expresses only four fixed operations: stage target, request its load, stage baseline,
request its load. There is no MMIO backend, CE entrypoint, installer registration or USB
job kind. A staged MFN value is not proof that its rate has been applied.

Precommit the complete conditional plan before any submission; preserve CONFIG's other
bits; require positively fenced settlement and fresh guards plus CPU-relative-rate evidence.
Pending/ambiguous work forbids overlapping undo; ambiguity remains restoration-only even
after positive settlement. Journal failure forbids further upward
progress but may permit narrowly preauthorized restoration in the same live owner epoch.
Restart never authorizes replay; incomplete final audit is not clean restoration. Fresh
phase controls are checked while holding the target and baseline is revalidated after final
journal work. Adapter qualification flags are assertions, not evidence produced by the core;
a separate trial dwell governor and hardware-independent recovery remain necessary.

## Concrete remaining boundaries

Candidate CSPDDK's clock critical section is process-local, not a demonstrated cross-host
PLL1 policy lock. Existing setpoint signaling does not establish a CPU transition consumer.
Cold-start baseline initialization and an unresolved watchdog callback are not proof of
independent recovery after CPU/DDR failure.

A read-only Cortex-A8 cycle-counter probe might help only if existing permissions and
counting are already enabled. Candidate NK's USEREN-enable branch is skipped by a zero ROM
flag; no enabled PMU route was established. Do not enable or reset it speculatively.

Policy/suspend exclusion, qualified CPU-rate observation, fitted-part/rail/thermal limits,
independent physical recovery and a separately reviewed platform adapter are still required.
No new USB package was prepared in this offline stage. Consumed jobs and retained claims
must not be replayed or removed.

See [full contract and static evidence](../docs/CLOCK-TRANSITION-2026-11-18.md),
[[clock-baseline-2026-11-18]] and [[clock-qualification-return-2026-11-18]].

## Verified scope

56 focused tests pass, including a strict host C build running 32 synthetic scenarios under
ASan/UBSan. Targeted Clang analysis and whitespace checks pass. Independent security,
performance and tests rechecks approve this hardware-independent scope after reproduced
state-drift, post-journal freshness and callback-result defects were fixed with regressions.
No full CI, CE build, car transition, physical qualification or USB change ran.
