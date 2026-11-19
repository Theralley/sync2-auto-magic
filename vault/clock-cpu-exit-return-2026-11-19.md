# CPU-read return: preflight passed, completion wait failed
The probe reported USEREN zero, but independent completion failed; no repeated test or overclock is authorized.

All 80 managed files (761,777 bytes) were preserved and hash-verified before import. Pending
job, trusted local identity, consumed 49,784-byte pack, nine source snapshots and artifact
bindings match. Import correctly remains **not-verified**.

The successor ledger completed all five preflight phases, consuming its immutable one-shot
edge. The child journal contains USEREN zero and the disabled-user-access terminal. The
debug event reports exit zero, followed by an immediate process-wait failure, cleanup and
controller exit one. This is a raw observation, **not** a verified negative availability result.
The source proves the failed guard, but the old log does not distinguish wait timeout from
wait error. No register-enable or clock/voltage write occurred.

A bounded process-completion wait and exact failure-only diagnostics are repaired locally:
114 focused checks and three independent review lenses pass. The fix preserves the exact
success protocol, clean-exit/query agreement and every existing gate. No repaired CE binary
or new USB was built; the fix has not been tested in the car. The original return
stays inconclusive; a code repair cannot retrospectively validate it. Repeating this job or
resetting the consumed edge is forbidden, and a fresh same-contract ID would still fail.

No new package is prepared. Another PMU-negative trip alone would not establish CPU rate.
Continue offline toward an evidence-bound useful next transition: no generic predecessor
adoption, privileged-access workaround or speculative PMU enablement. Fitted-part/rail/thermal
limits, policy/suspend exclusion, a genuinely independent CPU-rate sampler and CPU-independent
recovery are still required before any increased-frequency trial.

See [actual evidence and repair](../docs/CLOCK-CPU-EXIT-RETURN-2026-11-19.md),
[[clock-cpu-read-2026-11-19]], [[clock-transition-2026-11-18]] and
[[clock-qualification-return-2026-11-18]].

The returned stick has no new installer or pending job. Its old instructions were archived,
returned/do-not-repeat status was read back, and ordinary ejection succeeded. Other sticks
were untouched. Source fix `2d02511` is local only.
