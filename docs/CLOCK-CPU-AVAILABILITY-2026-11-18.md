# Read-only CPU-counter availability diagnostic
A new three-layer one-shot diagnostic is prepared and remount-verified on the identified NO NAME stick; no overclock is installed or qualified.

## Current USB package, November 18

Job **`20261118-164459-cpuavail-3226`** contains exactly three experimental CE executables
and `job.json`. Its **40,352-byte** install pack has SHA-256:
`af76bd0fe09fbd4b407969628750ccf0cbe568721ff0238cf86ef1691aac8769`.

The earlier managed stick files and instructions were backed up and hash-verified before
preparation. Previous updater files and clock instructions were archived, not replayed or
discarded. Pack, pending identity and new Swedish instructions matched after ordinary
unmount/remount; NO NAME was then **safely ejected**. The other two sticks were untouched.
The key window ends **December 17, 2026, 09:35:59 UTC** (10:35:59 Swedish time).

This completes **preparation of a new USB diagnostic**, not validation of its behavior in
the car. No CPU-rate measurement, frequency/voltage update or overclock was performed.

### One parked test

1. Use only NO NAME while the car is parked. Insert it **once**.
2. Wait for “Install successfully completed”, then leave it inserted another minute.
3. Return it for preservation/hash verification/import. A success screen alone does not
   establish that the diagnostic obtained usable observations.
4. If an error appears, photograph it and return the stick. Do not repeat the insertion,
   remove retained claims or use an old undo package for this diagnostic.

The root file `S2AM-CPU-TEST-20261118.txt` carries these instructions. Results may legitimately
be **inconclusive** if CE refuses debugging, suspended launch, process-handle duplication or
CPU access. The design has no un-debugged execution fallback or automatic retry.

## Three layers and the pre-read gate

- **POST_APP collector, `s2amcpujob.exe`:** verifies and locks the exact controller/probe
  artifacts, creates a fresh retained CPU claim and publishes a ready receipt only after
  preflight. It independently observes the controller's exit, copies both bounded journals
  with size/CRC bindings and then creates its collection marker.
- **Debug controller, `s2amcpuctl.exe`:** requires the claim plus post-preflight receipt and
  its own new entry marker. It creates a fresh nonsignalled per-job manual-reset event,
  starts only the exact probe with `DEBUG_ONLY_THIS_PROCESS | CREATE_SUSPENDED`, and requires
  a matching CREATE_PROCESS event before signalling the gate and resuming execution.
- **Gated probe, `s2amcpuprobe.exe`:** requires its exact job/module/report identity and a
  pre-existing signalled event before **any** MRC. Missing/unsignalled gate means nonzero
  exit and zero CPU-register reads. It then performs only the existing USEREN/PMNC/CNTENS
  read protocol described below; no CCNT, PMU enable/reset or clock write exists.

The controller rejects every exception, including an unbound breakpoint. It never changes
PC/context, skips an instruction or reopens a process by PID. A separately duplicated owned
process handle survives debug-event handle cleanup. Failed/ambiguous execution remains
inconclusive, retains one-shot state and cannot authorize another attempt.

Microsoft documents [suspended/target-only creation](https://learn.microsoft.com/en-us/previous-versions/ms939168(v=msdn.10)),
[existing event opening through CreateEvent](https://learn.microsoft.com/en-us/previous-versions/ms959948(v=msdn.10))
and [debug continuation/handle lifetime](https://learn.microsoft.com/en-us/previous-versions/ms938952(v=msdn.10)).
A historical [CE5 OEM trust warning](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms904879(v=msdn.10))
explains why debugger flags alone are insufficient; it is not proof that this CE6 target
ignores them. Actual permissions and fault behavior still require the car return.

Debug processing has a 15-second budget and at most 64 events, within a 60-second overall
cooperative budget. Synchronous filesystem/loader/kernel calls cannot be forcibly bounded
by those checks. Failure cleanup targets only the process whose ownership was established.
Neither the event nor local artifact manifests authenticate against an equally privileged
host process; source/artifact binding is consistency evidence, not execution attestation.

## Reviewed gated artifacts

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `s2amcpuprobe.exe` | 8,704 | `716f3016ede10e00bbc9e39fe2ad4a33e9b90d22f58cb19267a2c8b79d8e2042` |
| `s2amcpuctl.exe` | 15,872 | `23d8daef0982f77328d72c0d6594a90ebea799ca46b8de772ce7bd81beb4ff57` |
| `s2amcpujob.exe` | 12,800 | `74298939b0c69b54617ac3c71d2162836fd1f067b2abaed0c137075198f6d1b7` |

The isolated `cpu-usb-20261118-reviewed-2` build binds all seven source dependencies,
including headers, to the pinned CE compiler image. Its three PE files are ARM `0x1c0`,
CE subsystem 9 and COREDLL-only. All 28/40/36 imports respectively resolve in the inspected
candidate COREDLL; this is not live firmware identity or runtime permission proof.

Independent raw-binary review compared **5,703 disassembly words** to executable bytes.
Only the probe contains the three allowed MRCs; the parents have no CP15 transfers, and
there is no MCR or CCNT read. Gate/attachment/release ordering and embedded artifact bindings
were checked in compiled code. Reviewed-1 is superseded and was never put on the stick.
The old ungated standalone artifact below **must never enter this USB route**.

**140 focused tests pass**, including strict host C builds under ASan/UBSan, all controller
write/flush boundaries, failed-handle ownership, ignored debug flags, event storms, tick
wrap, every owned-handle close, gate denial, artifact/include binding and actual-C
controller → actual-C collector → host-analysis round trips. Three independent security,
performance and tests reviews covered the diagnostic; a separate artifact review covered
the final compiled bundle. No full CI, server run or production build was performed.

Host import requires a trusted local job, the exact six-row outer record with independently
clean controller exit, the exact fourteen-row controller success record, matching hashes,
sizes and both CRC layers, then the exact four/eight-row child record. Visible terminal
bytes with a failed final close never become success. Collection completion is distinct
from a verified availability observation; all rate/write/retry qualification flags stay false.

Source/test commits remain local; published material is documentation only. The next step
is the **actual car return**, not another package or a clock change.

## Historical standalone component — not the current USB executable

The following records the earlier ungated offline component. Its smaller artifact and
lack of a deployment parent are historical, superseded by the gated bundle above.

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
