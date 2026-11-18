# Evidence-bound clock transition and restoration work
The live reader evidence is now bound to an offline specification; hardware transition and recovery remain unqualified.

## Current boundary

The successful November 18 return establishes scoped baseline/timer observations, not a
perpetual clock-policy lease. `s2am/clock_transition_evidence.py` reads an explicitly named
trusted local job and the five exact preserved report files. It checks the expected predecessor/job identities and recorded stage order,
report CRC/lengths and success contract, pins report SHA-256 values, checks the local staged
artifact manifest and checks that inputs remain unchanged through analysis. The report
contains source/artifact/input digests, not private absolute paths or a device serial.

This is **caller-trusted local provenance**, not cryptographic attestation of code running
on a particular car or proof of present-day state. Before/after file checks are not locks
against hostile concurrent writers. No input can promote this module to write authority.

The actual job produces **7 captured requirements met / 12 still unknown**, with
`state=blocked`, `deployable=false`, `write_authorized=false` and `operations=[]`:

- Captured reference selection/divider and PLL output factor.
- Active normal parameter bank.
- Captured lock-mode/auto-restart configuration (not fresh-lock proof).
- Desense disabled and no pending load at capture.
- ARM source/divider.

Separately, the successful timer route/coherence/bracket facts are included explicitly.
The reference timer avoids PLL1 under the captured route; no CPU cycle-rate measurement,
physical oscillator calibration or suspend-exclusion guarantee is supplied. Full DDR and
consumer qualification, exact firmware/fitted silicon, runtime exclusion, loaded voltage,
thermal limits, independent recovery and mutation/journal contracts remain unresolved.

Bind local evidence without writing to a USB or device:

```sh
python3 tools/clock_transition_model.py --out build/clock-transition-bound \
  --qualification-job /explicit/trusted/job.json \
  --qualification-report /explicit/preserved/report-directory
```

The output directory must not already exist. `actual-evidence.json` and
`candidate-spec.json` remain inert. Other emitted traces are explicitly synthetic historical
Python rehearsals, not car observations or instructions for a platform adapter.
Without explicit inputs the command makes no observation claim; it does not mean the
already preserved car return is missing. A nominal reference assumption is optional and
must be named explicitly. The candidate ratio derived from the captured baseline is **26/25 (+4%)**; nominal 600/624
MHz additionally assumes an unmeasured 24 MHz oscillator.

## Transition contract

The implemented portable coordinator (`s2am/native/clock_transition_core.c/.h`) has
**no MMIO backend, CE entrypoint, IOCTL,
installer registration or USB job kind**. Only fixed operation identities are expressible:

1. Stage target MFN 2.
2. Request target load by asserting LDREQ while preserving other CONFIG bits.
3. Stage baseline MFN 1.
4. Request baseline load.

The complete immutable conditional plan must be durably committed before any submission.
Each operation can be submitted at most once, with potentially-dispatched state recorded
before calling a backend. Ambiguous submission or timeout retains ownership and blocks
all overlapping restoration. An ambiguous submission also permanently requests restoration;
if later positively settled, it cannot resume upward progression. There is no cancellation operation or raw register-dump replay.
No OP/MFD/CTL/HFS, step-clock, divider, reference or restart operation is available.

The [NXP reference manual](https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf),
§22.3.3.2 and Tables 22-2/22-3, separates staging MFN from its application. Consequently:

| Stage | MFN readback | Applied CPU/reference ratio relative to baseline |
| --- | --- | --- |
| Initial | 1 | 1 |
| Target staged | 2 | 1 |
| Target applied | 2 | 26/25 |
| Baseline staged | 1 | 26/25 |
| Baseline restored | 1 | 1 |

CONFIG's captured non-LDREQ bits are `4`; asserting LDREQ must preserve bit 2, producing
conceptually `5`, not `1`. Clearing LDREQ cannot cancel a pending update. Software need not
observe its short asserted pulse, but a zero bit alone cannot prove settlement. Sticky LRF
is necessary status, not fresh-lock evidence. With desense inactive, DESTAT's low MFN field
is not an authoritative applied-frequency indicator.

Settlement requires a matching positively completed/fenced operation, a subsequent fresh
complete observation, unchanged phase-appropriate controls and guards, clear LDREQ, and an
independent CPU-relative-rate interval supporting the expected ratio while excluding the
other. A broad interval containing both 1 and 26/25 remains inconclusive. Host fixture
bounds are not qualified Ford timings.

### Fault and audit policy

- Journal append failure permanently blocks further upward progress.
- The precommitted conditional baseline operations can still restore only in the same live
  owner/timebase epoch, after the preceding operation is positively settled and with fresh
  complete guards rechecked **after** journal work.
- A fault after staging but before target load restores MFN 1 only; it must not unnecessarily
  apply MFN 2 or request another load.
- A late target completion after a fault requires restoration, not an ordinary success.
- Both clean and audit-incomplete positive baseline states require a fresh full recheck
  **after final journal work**, with capture/rate windows after the operation fence and no
  earlier than the prior validated observation. Baseline observed with failed final audit is
  **audit incomplete**, not permission to release ownership barriers.
- Restart, changed policy owner/bank/epoch or unresolved hardware operation never authorizes
  replay from precommitted intents. It requires reconciliation/external recovery.

Preauthorization improves best-effort restoration after a logging fault. It cannot recover a
stalled CPU, lost ownership, failed rail or DDR loss. No host test establishes those physical
properties. The eight qualification bits and callback results are adapter assertions,
not evidence this core establishes. A separate caller must supply the bounded trial dwell
governor; this coordinator is not a watchdog or a complete trial application. Commit, append
and refresh callbacks succeed only with return value exactly `1`; they must provide real
ordering/freshness semantics and may not re-enter the serialized core.

## Firmware findings: no shortcut through existing APIs

These are bounded static findings in the metadata-matched candidate, **not proof of live
firmware byte identity or exhaustive runtime behavior**.

- CSPDDK's `DDKClockLock` at RVA `0x2974` uses a DLL-local critical section at
  `0xc0066120`; the matching unlock is `0x298c`. It is not a demonstrated cross-host
  PLL1 policy lock. `SetFreq` at `0x4bd4–0x4c7c` does not acquire it and supports the
  previously identified PLL3 values, not a CPU PLL1 transition.
- The ACR/SDMA named mutexes belong to SDMA operations, not demonstrated clock ownership.
  Setpoint request/release update counts and signal `EVENT_DVFC_WORKER`; no CPU-frequency
  consumer was established. Their blocking wait is not a bounded transition mechanism.
- Candidate NK cold-start code sets the baseline PLL1 fields. Neither the inspected PMI
  power paths nor an unresolved watchdog callback proves that every warm reset, suspend
  or CPU lockup returns safely to that baseline.

Microsoft documents CE critical sections as single-process synchronization in
[System Programming, chapter 3](https://download.microsoft.com/download/8/a/6/8a66a2e1-f2e1-4113-8877-514d6f668fe3/Chapter%203%20-%20Performing%20System%20Programming.pdf).
The candidate CSPDDK digest is
`8f47eaa549982bfe81241a71ad3997701d8adfe00a9ef486d825d5ce563b310e`.

### CPU-relative-rate observation possibility

A **read-only** Cortex-A8 cycle counter might help only if its existing permissions and
counting state already permit it. The [ARM Cortex-A8 TRM, DDI0344K](https://documentation-service.arm.com/static/5e8e1ac688295d1e18d35fde),
§§3.2.42–43, 3.2.48 and 3.2.51, requires USEREN access permission, PMNC.E and CNTENS.C.
PMNC.D selects every cycle or every 64th cycle; idle/debug/security controls can suppress
counts. Wrap, reset, preemption and idle gaps must be handled. Average counted cycles alone
are not guaranteed nominal MHz.

Candidate NK contains a USEREN writer at `0x80106a60`; its sole direct caller found at
`0x8010a5b8` is gated by the ROM flag at `0x80101a98`, which is **zero** in original
`main.nb0`. The bounded NK/kernel scan found no PMNC/CNTENS initialization or cycle-counter
reads. Other components and later runtime changes were not excluded. Thus enabled user-mode
PMU access is **not established**.

A future fault-contained read-only child could read USEREN first, stop when disabled, and
only then inspect existing PMNC/CNTENS/CCNT state. It must never enable, reset or reconfigure
the PMU. No such probe or USB package was implemented in this stage.
[CE GetThreadTimes](https://learn.microsoft.com/en-us/previous-versions/ms908464(v=msdn.10))
returns execution time, not core cycles; QPF's 8 MHz also is not a CPU cycle measurement.

## Next hardware boundary

Qualify policy/suspend ownership and a CPU-rate sampler; establish fitted-part limits,
loaded-rail/thermal observation and genuinely independent recovery; then review a separate
fixed platform adapter. Baseline-to-baseline and fault restoration must be demonstrated on
a recoverable stationary bench before an increased-frequency experiment. An undo USB cannot
be treated as recovery when CPU/DDR execution is lost. Do not repeat consumed reader jobs,
remove old claims, enable PMU controls speculatively or substitute arbitrary kernel access.

## Verification in this stage

- **56 focused tests pass**, including the actual baseline/qualifier fixtures, binding,
  interpretation, historical model and a host-compiled C harness with **32 named synthetic
  scenarios** (several contain independent boundary/guard variants).
- The C harness uses strict C99, `-Wall -Wextra -Werror -pedantic` and AddressSanitizer /
  UndefinedBehaviorSanitizer. Clang's targeted static analyzer reports no finding.
- Independent security, performance and tests reviewers reproduced state-drift and final
  journal/freshness defects. Regression tests failed before their fixes and pass afterward;
  final rechecks find no blocking issue within the hardware-independent scope.
- Changed Python files parse, and `git diff --check` is clean. No full CI, server run,
  production/CE build, new car execution, hardware timing qualification or clock write ran.
- The identified NO NAME stick remains mounted with its already-consumed package. No new
  install package, pending operation or change to any of the three USB sticks was made.

Source and tests remain on the local development branch. Published documentation does not
publish or install the coordinator, nor certify an overclock as safe.
