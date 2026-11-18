# Read-only CPU-counter availability probe
A standalone CE diagnostic and strict host parser are built and tested; no car execution or USB package has been prepared.

## Why this is the next component

The successful EPIT/QPC qualification is not a CPU cycle-rate measurement. Candidate NK's
PMU-enabling branch is skipped by its zero ROM flag, but that static finding cannot establish
present-day user permissions. A small live permission/control observation is new evidence,
not a repeat of the already completed clock/timer reader.

This first probe deliberately **does not sample CCNT, call QPC, estimate MHz or alter PMU
state**. Controls enabled would identify a possible later sampler, not qualify one.

## Exact read boundary

`s2am/native/s2amcpuprobe.c` implements only three fixed possible MRC instructions:

1. USEREN: `p15,0,Rd,c9,c14,0`, readable in every processor mode.
2. Only if USEREN.EN is set: PMNC, `p15,0,Rd,c9,c12,0`.
3. Only on that branch: CNTENS, `p15,0,Rd,c9,c12,1`.

There is no generic register selector, MCR, enable/reset, counter read, MMIO, driver,
registry operation, kernel fallback or retry. Each instruction requires a successfully
flushed progress record first. Output uses one bounded absolute report filename and
`CREATE_NEW`; a future parent must bind an exact owned ordinary report path. Report writes
and OS file operations can block; this standalone executable supplies no deadline.

The [ARM Cortex-A8 TRM, DDI0344K](https://documentation-service.arm.com/static/5e8e1ac688295d1e18d35fde),
§§3.2.42–43 and 3.2.51, defines USEREN.EN, global PMNC.E and CNTENS.C (bit 31), plus PMNC.D's
1/64 cycle divider. Reserved CNTENS bits are retained raw and do not affect the decision.
Existing controls do not establish counting progress, stability, future permissions,
preemption effects, debug/idle behavior or ownership.

## Small exact protocol

ASCII with CRLF, at most eight records and 2 KiB:

```text
S|s2am-cpu-counter-availability-v1
B|useren
R|useren|<unsigned DWORD>
B|pmnc
R|pmnc|<unsigned DWORD>
B|cntens
R|cntens|<unsigned DWORD>
T|complete|controls-enabled
```

If USEREN.EN is zero, stop after its result and emit
`T|complete|useren-disabled`: exactly four records. If USEREN.EN is one but either PMNC.E
or CNTENS.C is zero, the eight-record terminal reason is `counter-disabled`.

Every record is flushed. A terminal record **alone is not success**: final flush/close can
fail after those bytes become visible. The caller must independently observe clean child
exit and collection status. Missing terminal, timeout, invalid exit, instruction fault,
malformed bytes, reordered/extra records or inconsistent terminal reason is **inconclusive**,
never evidence that permissions are disabled. A last progress record identifies a stage,
not the cause of failure. No automatic retry is permitted.

`s2am/clock_cpu_probe.py:analyze(body, child)` consumes explicit bounded bytes and independent
child status. It performs no filesystem or device access. The caller supplies trusted
collection/provenance; the parser does not attest executed code, device or firmware identity.
All results retain `counter_progress_observed=false`, `cpu_rate_qualified=false`,
`write_authorized=false` and `retry_safe=false`.

## Verified artifact and tests

One explicitly scoped experimental diagnostic build ran locally with the existing pinned
CE image, `-O2 -Wall -Wextra -Werror`, no network and an exclusive source/receipt directory.
This was not CI, a production build or the ordinary all-program native build.

- Source SHA-256: `d00df7c9b55408bbb943195c461886716c643582438c785016f0b30b9bdf96a9`.
- `s2amcpuprobe.exe`: **6,144 bytes**, SHA-256
  `abdc9ea572b9d20ad784902b64acf00b3312cb59c56619ad9a41bf240a5e5c27`.
- PE machine ARM `0x1c0`, CE subsystem 9, COREDLL-only imports.
- All 18 imports resolve in the inspected candidate COREDLL; this is not live-byte identity
  or proof of permissions/behavior on the car.
- Actual binary inspection finds only the three allowed CP15 reads, no CP15 write, and the
  USEREN-disabled branch skips both later reads. Compiler ordering preserves progress-call
  failure branches before each MRC. A compiler memory clobber is not hardware serialization.
- **16 CPU-specific tests pass**, including strict host C compilation under ASan/UBSan,
  each flush failure, all 29 write-failure positions, traps, final flush/close failure,
  report-path validation, reserved bits and 12 actual C-bytes/actual-exit parser round trips.
- **72 focused tests pass** when combined with transition/interpretation/actual baseline and
  qualifier regressions. Targeted Clang analysis, changed-Python parsing and whitespace
  checks pass. Independent security, performance and tests reviews cover this offline scope.

Build receipts, source snapshot, compiler log, disassembly and verification remain in the
ignored local `build/cpu-availability-20261118-dbb251ba/` directory. Source is local; only
documentation is published.

## Not deployable yet

The helper is absent from automatic native builds, job kinds and installers. No new USB
pack, pending job or car execution exists. Actual instruction support and fault behavior
remain unverified. Host trap tests model abrupt child loss; they do not demonstrate CE
exception/debugger containment. A child process alone is not a promise of fault containment.

The next component is a separately reviewed parent that establishes fault containment and
exact executable/report identity, plus one-shot launch/collection binding without weakening
existing clock claims or replay barriers. Do not add an uncontained fallback if that route
is unavailable. Even a positive availability return would leave CPU-rate sampling,
clock-policy/suspend exclusion, physical limits and independent recovery unresolved.
