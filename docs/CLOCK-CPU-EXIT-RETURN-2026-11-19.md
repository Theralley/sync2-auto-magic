# Controlled CPU-read return and exit-wait repair — November 19, 2026
The diagnostic reached the probe but did not satisfy independent completion; no CPU-rate or overclock qualification follows.

## Preserved return

The returned job is `20261119-090912-cpuavail-a8cd`, controlled contract 2. Before import,
all 80 managed USB files (761,777 bytes) were preserved with matching before/copy/after
SHA-256 manifests. The consumed 49,784-byte pack has SHA-256
`85f5de9cb500c861345bb22aacc297a6fc8d1cd75caa49cc2e6a32cc2cc9841c`.
Returned pending identity equals the trusted staged local job; its nine bound source hashes
match the immutable return source and bundle snapshots. Local provenance is not runtime
attestation. Import result is **not-verified**.

| Original report | Bytes | SHA-256 |
| --- | ---: | --- |
| cpu-job.txt | 162 | `417e5d81872b51f0d632688de28d4b8fb175cb3c3892f5abfa11ba4b7022d47b` |
| cpu-debug.txt | 355 | `20d7f355432f316b3f5d54c514369fd81ba9f84798c6c941a3d4babc10b72af0` |
| cpu-availability.txt | 86 | `c0c5ad98d154f05f1de87d740d1d35b927e113fe276948eea431c913fa037697` |
| cpu-successor.txt | 191 | `51fe6e485dfcf64fb6888388bd88151b20b0c8d86a89762b6f0c8285ace77911` |
| done.txt | 29 | `e7a0855a425d1c1220f00f175f22c2af64daabf749f8ddd914a2c5860f808636` |

## Observation versus completion

The successor ledger is exactly S/O/N, five P rows and `T|preflight-complete`. The repaired
DLL-only enumeration passed both scans; the immutable predecessor edge is now spent.
The matching child was attached while its read gate remained closed, then the gate opened.
The child journal contains `R|useren|0` and `T|complete|useren-disabled`; it has no PMNC/CNTENS
or cycle-counter observation. The debug-parent tail is:

```text
X|4|0
E|api|exit-query|0
K|termination|1|0
T|inconclusive|exit-query
```

`X|4|0` means four debug events and debug exit zero. It does not replace an independent
process-handle wait and exit-code query. The outer collector independently records controller
exit 1 and binds all three reports by size/CRC32 (2823793576, 1917492695, 983721106).
The strict analyzer returns collected=true, complete=false, observation=inconclusive and
all rate/write/retry permissions false. Never supply a synthetic clean child status to turn
the raw USEREN zero into a verified negative result.

## Concrete failed guard

In the bound `s2amcpuctl.c`, EXIT continuation is followed by `WaitForSingleObject(stable,0)`.
Only WAIT_OBJECT_0 sets exited. The recorded cleanup termination occurs only when exited is
false; therefore the returned wait was not WAIT_OBJECT_0. The following compound guard
short-circuits before GetExitCodeProcess. This is not a proven query API failure.

A zero-time wait is an immediate state test. A deferred signal after EXIT continuation is
plausible, but the old report does not retain the wait result; WAIT_FAILED/another return
cannot be excluded. Its displayed errno zero is captured after journal work and must not
be reinterpreted as a successful wait or authoritative wait error.

The [CE wait contract](https://learn.microsoft.com/en-us/previous-versions/ms915517(v=msdn.10))
and [debug continuation contract](https://learn.microsoft.com/en-us/previous-versions/ms938952(v=msdn.10))
do not grant a synchronous-signalling assumption for this separate stable process handle.

## Repair and next experiment boundary

The local repair permits an immediate process poll followed, only after WAIT_TIMEOUT, by
one finite wait capped at min(2,000 ms, remaining 15-second debug budget, remaining
60-second overall budget). It retains the exact 16-row success envelope, independent
exit-query agreement, gate/ownership, exception, budget and cleanup constraints. Failure-only
`W|exit-wait|<raw-wait>|<immediate-error>` records distinguish timeout/error from query failure.
Wait errors are retained before logging; only a signalled process and matching zero queried
and debug exit codes can succeed. Late completion remains inconclusive. Regression tests preserve these original bytes
and ensure a failed controller, even with forged clean outer exit, cannot promote the probe.
The exact wait and immediate WAIT_FAILED error are now retained before journal APIs can overwrite them.

No new CPU package is prepared or authorized for replay. The consumed fixed edge must not
be removed, reset or adopted by another job. A new same-contract ID is not a usable successor.
Any later on-car diagnostic requires a separately reviewed, exact evidence-bound transition
that preserves old claims, executable/report hashes, edge identity and fresh absence checks.
It must add useful evidence rather than repeat an already observed negative branch.

Even clean USEREN zero would close the no-write user-mode PMU cycle route, not establish
another sampler. Existing EPIT/QPC coherence and nominal 600 MHz clock-tree arithmetic are
not measured CPU cycles. A qualified independent CPU-rate measurement, policy/suspend
exclusion, fitted-part/loaded-rail/thermal limits and independent physical recovery remain
required. No privileged-access bypass or PMU enable/reset is introduced.

Related: [[clock-cpu-exit-return-2026-11-19]],
[transition boundaries](CLOCK-TRANSITION-2026-11-18.md).

## Verification and limits

**114 focused checks pass**, including 27 strict C99 native-controller test methods under
ASan/UBSan and seven new byte-exact actual-return tests. The delayed-signal regression
failed before production changes (10 expected failing subcases); an additional deadline
regression also failed before its branch repair. Targeted Clang static analysis and modified
Python AST/whitespace checks pass. Independent security/correctness, performance/timing
and test-coverage reviewers report no blocking finding.

The wait regression covers deferred signalling, exact budget caps, tick wrap/frozen ticks,
persistent timeout, failed/unexpected wait returns, error preservation across logger changes,
late signalling and query failure/disagreement/deadline. Success bytes remain unchanged.
The legacy write/flush sweeps cover the success path, not every new failure-only W-row write;
such failures remain inconclusive and cannot grant success.

Local repair commit: `2d02511`. The controller source SHA-256 is
`c28993d17ee8e5117a87ece18959a95ed77fbd2418111d891b8d53058023c3e5`.

This fix is **local source/test work only**: no repaired CE bundle or new USB package was
built. No on-car fix validation, full Mac CI, server CI or increased-frequency operation ran.
Existing synchronous kernel/file calls and the separate cleanup wait are not hard wall-clock
cancellation guarantees. The original return stays not-verified.

The bounded next-route review found no qualified alternate API: candidate DDKClockGetFreq
uses cached configuration, processor-info clock values are boot metadata, and existing EPIT/QPC
measure a reference route rather than CPU-core cycles. The next specific platform question is
whether this exact deployed CE/OAL provides an existing read-only profiling interface returning
core cycles with known ABI, source/divider/width, already-active counting state and uncertainty
small enough to distinguish 26/25. No such interface is established in available evidence.

## Returned stick closed safely

No installer or new pending job was placed on the stick. After import, the original root
instruction was archived, and its replacement explicitly says the test has run and must not
be repeated. All five original reports and the consumed pack were reread unchanged; the
returned-status instruction was reread exactly. Ordinary ejection succeeded. Other sticks
were untouched. This is **not** a new ready-for-car package.
