# Raw load observer implementation — November 20, 2026
The single-port observer is built and reviewed; its USB files passed remounted readback, with no car execution yet verified.

## Published implementation and actual build

Owner-authorized source is on `build/raw-load-20261120`, commit
`b018ae7b3e4919dbb5a7f25efab4c11a4cd98063`. This observer work did not update main,
merge, create a release or automatically install anything in the car. This documentation branch
contains the evidence notes, not the implementation files.

[GitHub Actions run 44754266037, attempt 1](https://github.com/Theralley/sync2-auto-magic/actions/runs/44754266037)
succeeded: 104 focused tests and both Windows CE ARM compilations passed. The owned-branch
build-only workflow uses read-only permissions, pinned actions and a digest-pinned,
offline compiler container. Source, binaries, run and attempt are bound in the v2
artifact manifest. No Mac CE build or full repository CI fallback was used.

The earlier standalone build was not suitable for the owner's single USB port.
The current artifact contains a matching pair; do not mix it with that earlier payload:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| S2AMLOAD.EXE | 15360 | `22697da9424169e3f1ef9fbb968def26764a41c4a783f3fecaa04e6d332fb5bd` |
| S2AMCTL.EXE | 14336 | `e6f8dc7ceafa0b557a84697ac39decb8bff78a975d12212da0c506c3f80df752` |

## Single-port lifecycle

The user manually launches `S2AM-LOAD\S2AMCTL.EXE`, not the collector directly.
The controller reserves one fresh fixed internal run directory, writes a flush-checked
claim, copies and verifies the size/SHA-pinned collector, then starts only that
internal executable without arguments. A bounded live-child/PID/TID/header check
precedes the start confirmation. This is startup observation, not completion or
power-loss durability proof.

The user closes the controller before removing the USB, connects CarPlay and keeps
SYNC on while parked for at least six minutes. Later, running the same controller
collects the already-published internal result; it never starts another recording.
Collection verifies the bounded source and USB readback before non-replacing
publication of `S2AM-LOAD\LOAD.CSV`. Existing claims, partial results and old reports
are never cleared automatically. See the source branch's
[lifecycle contract](https://github.com/Theralley/sync2-auto-magic/blob/b018ae7b3e4919dbb5a7f25efab4c11a4cd98063/docs/LOAD-START-COLLECT.md).

## Verification actually performed

- All 104 focused methods pass both on the host and in Actions. Real C executes under
  deterministic CE API fakes with ASan/UBSan; 17 producer scenarios feed the strict parser.
- Lifecycle regressions cover same-fixture retry without relaunch, wrong claims/payloads,
  independent copy/readback/receipt failures, short I/O, delayed readiness, early exit,
  wrong PID/TID, output races, admission expiry and actual DWORD tick rollover.
- Tests exposed two defects before publication: fixed-length claims did not accumulate
  short reads, and a stale USB receipt could create an empty car folder. Both were fixed
  and independently rechecked. Equal-length corruption tests reach content/hash checks.
- Security, performance and tests reviews cleared the final source. Independent compiled
  review matched all 4,824 disassembly words to the two actual PE binaries, verified CE ARM
  identities and the controller's embedded collector size/hash and fixed paths. No
  unexpected privileged operation was found; CRT imports are not application clock control.
- Static imports exist in the inspected firmware candidate. That candidate is not proof
  of deployed-image identity, runtime compatibility, actual cost or successful car execution.

## Delivery and evidence limits

After backup and compiled-artifact review, the matched pair and instructions were
copied to a fresh USB folder. All 87 original managed files and five new files matched
their hashes after unmount/remount, followed by safe ejection; only three old root
instruction files were archived.
Old programs, results and consumed installer evidence remain intact. Insertion alone
will not start anything: this is a manual start/collect procedure, not a new installer.
No successful on-car recording or returned new LOAD.CSV is claimed yet.

The observer records ordinary-API CPU times, identities, bracketed reads and explicit
coverage/error status. New identities are baseline-only; collection latency and
self-accounted CPU are separate, and indirect OS/I/O cost is unmeasured. No driver,
spin benchmark, PMU/MMIO, registry, clock, voltage or priority change is introduced.
All clock qualification and write-authority flags remain false. Frequency, fitted-grade
and independent-recovery gates are unresolved: this is not a clock solution or proof
of a causal CarPlay bottleneck. See [[load-observer-design-2026-11-20]] and
[[clock-evidence-boundary-2026-11-20]].
