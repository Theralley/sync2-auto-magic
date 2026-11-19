# Controlled CPU read after live CE module evidence
A narrow preflight correction uses the actual metadata return while preserving the gated read-only CPU probe, old claims and one-shot successor edge.

## New gated CPU-read USB ready, November 19

NO NAME now contains **`20261119-090912-cpuavail-a8cd`**. The **49,784-byte** pack has SHA-256
`85f5de9cb500c861345bb22aacc297a6fc8d1cd75caa49cc2e6a32cc2cc9841c`.
The official unpacker reproduced all five payload files exactly: three executables, the
canonical predecessor receipt and `job.json`. No MortScript or restart action is included.

All 71 previous managed USB files were backed up and hash-verified before mutation. Consumed
updater files and old root instructions were archived; old reports remain preserved. The
new pack, single pending identity and Swedish instructions matched after ordinary
unmount/remount. The stick is **safely ejected**. Other sticks were untouched.

While parked: disconnect the CarPlay adapter, restart SYNC and open no app. Insert NO NAME
**once**, wait for install completion plus at least one minute, then return the stick.
Photograph errors; do not repeat insertion, remove claims or use an old undo package. Root
instructions: `S2AM-CPU-READ-20261119.txt`. Use before **December 17, 2026, 09:35:59 UTC**.

This is a new controlled attempt to read existing CPU control registers, **not an overclock**
or CPU-rate measurement. Its on-car read/debug behavior remains unverified. No frequency,
voltage or PMU enable/reset operation exists.


## What the car established

The metadata job `20261118-185807-cpumeta-8c51` returned with its exact prepared pack and
trusted pending identity. Original managed files were preserved before import. Independent
host analysis reports a completed diagnostic, with incomplete parent enumeration—not CPU
permission or overclock success.

Qualified Toolhelp loading and all six exports succeeded. The process scan completed with
12 entries and normal end code 18. The observer had a unique matching process entry and
its exact executable path. Its module list completed with three valid DLL entries and end
code 18, but **no entry for its own EXE**. Every recorded parent PID was zero, so the parent
could not be resolved. The CPU preflight does not require parent PID; none is added now.

These live facts contradict the old mandatory self-EXE-in-module-list predicate. They do
not uniquely establish why the earlier CPU job stopped at its `predecessor-bound` prefix:
that row's flush or the following ledger write could also have failed.

## Narrow repair and unchanged barriers

Only the final requirement that self EXE appear in Module32 enumeration is removed.
Cooperative self identity remains positively bound by current PID, exact GetModuleFileNameW
path and a unique matching process entry. A complete, nonempty module scan still requires
valid terminated names, qualified paths, matching returned PIDs, normal end code 18, limits
and successful cleanup. A CPU diagnostic module that does appear must be the one exact self
EXE; foreign diagnostic modules, duplicate self EXEs and other CPU processes still fail.

All old file/hash locks, immutable original CPU claim, fixed CREATE_NEW successor edge,
two fresh process scans, staged ready publication and pre-launch ledger copying remain.
No old job is replayed, and no claim or edge is deleted, overwritten or adopted.

The CPU probe and debugger controller sources **and executable bytes** are unchanged from
the previously reviewed v2 bundle. The parent resumes the owned probe once behind a closed
gate, requires matching CREATE_PROCESS before release, and treats every exception as
inconclusive. The child waits before any report/MRC and reads only USEREN, then PMNC/CNTENS
when allowed by the observed USEREN bit. No CCNT sample, PMU enable/reset, MCR, driver,
frequency/voltage writer, non-debug fallback or PC adjustment exists.

## Failure diagnostics without changing success proofs

The success ledger remains exactly nine rows, controller sixteen, outer seven and child
four/eight. Failed preflight may append one bounded row:

`E|preflight|phase|kind|code`

Opaque helper refusal is `predicate|0`, not a guessed API error. Shared journal-write
refusal is `journal-write|0`; deadline refusal is `budget|0`. `api` records an immediately
captured failed FlushFileBuffers error. Writing the failure row can itself fail, leaving
only the earlier prefix; absence of that row does not prove absence of failure.

The host exposes this only as **reported context** from the CRC-bound ledger of a failed
outer execution. Identity, canonical phases/kinds/codes and ordered prefixes are checked.
The exact final-T-before-E exception is limited to a full success-prefix followed by a
`ledger-complete/api` failure; even visible terminal bytes cannot turn a failed outer result
into CPU success. Generic outer error 5 remains a synthetic stop code, not access denial.
Post-ledger-close/publication failures can still lack a detail row; the outer failure must
remain authoritative. All rate/write/retry qualification flags remain false.

## Verification

189 focused checks pass (169 CPU/metadata/legacy checks plus 20 neighboring recovery and
qualification transactions), including strict host C, ASan/UBSan, DLL-only positive and
empty/partial/wrong-PID/path/foreign-module negative cases, fixed-edge retention, and
actual-C producer/host diagnostics for flush failures before scanning and after final T.
Independent security, resource and tests reviews clear this read-only diagnostic scope.
No full CI, server run or production build was performed.

The isolated experimental CE build binds nine sources, predecessor receipt, compiler and
three executables. Probe/controller bytes match the previous reviewed versions exactly;
only the outer collector changes. Candidate imports and independent raw executable review
remain consistency checks—not live firmware identity or CPU permission attestation.
Source/test commits remain local; project-safe documentation is published separately.

## Final compiled artifacts

Source snapshot: `1210847`. Independent raw review matched all **7,275 disassembly words**
to executable bytes, confirmed the changed DLL-only predicate and retained two-scan/edge/
ready ordering. All 41/40/28 COREDLL imports resolve in the inspected candidate. Only the
probe contains its three allowed MRCs; neither parent has CP15 transfers.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `s2amcpuprobe.exe` | 8,704 | `a374772485195b049ea789befe1cf3a5c2c402153084761d05144b66fd3bd21a` |
| `s2amcpuctl.exe` | 16,384 | `54f26b6fbba456f7021b62b785c0860e210a5c12a6f49d36d7b012b17a7c89e8` |
| `s2amcpujob.exe` | 20,480 | `5e50be4e56a2b296a9c7c7a48e01367ebb84e225295613ba46e66a83510d7332` |
| `cpu-predecessor.txt` | 506 | `6b2ff299902104e29f0dd73d2a9dbb6397d45d60132da1c7e6c978ac56c65e31` |

The unchanged byte-equal reference is the prior **contract-v2** bundle, not the older first
CPU USB revision. Qwen independently checked all nine current/snapshot/manifest sources,
four artifact hashes/sizes and embedded child/receipt bindings. Candidate availability is
not live firmware identity, CPU permission or execution attestation.

## Next evidence boundary

A completed install does not prove usable CPU observations. Preserve the next original
return before import, validate its trusted job/pack/source bindings, and interpret the nested
exits, attachment/gate events, hashes, CRCs and child records. Failure retains one-shot state;
do not repeat insertion or use an old undo job. No CPU frequency or overclock is qualified.
