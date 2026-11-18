# CPU startup metadata diagnostic
A separate metadata-only diagnostic isolates the CPU-startup preflight failure; it does not access CPU controls or qualify an overclock.


## New metadata diagnostic USB ready, November 18

NO NAME now contains **`20261118-185807-cpumeta-8c51`**. Its **29,584-byte** pack has SHA-256
`be71ca43b769944167cf856cbf728e64ea9db885aa2f693c50c4bea8742d1001`.
The official unpacker reproduced all three payload files exactly. All 64 previous managed
USB files were backed up and hash-verified before mutation; consumed updater files and old
instructions were archived. New pack, single pending identity and instructions matched
after ordinary unmount/remount; the stick is **safely ejected**. Other sticks were untouched.

Insert **once while parked**, wait for the installation completion message plus at least
one minute, then return the stick for preservation and analysis. Photograph an error and
do not retry. Root instructions: `S2AM-CPU-METADATA-20261118.txt`. Use before
**December 17, 2026, 09:35:59 UTC**. Installation success does not establish valid metadata.

This is the next diagnostic toward CPU readout, **not** a CPU-register read, frequency
measurement or overclock. A useful API-error/inconclusive journal is an expected possible
result. The actual return selects the next evidence-bound change; old CPU barriers remain.


## Why this package exists

The consumed CPU job `20261118-174115-cpuavail-dbf6` stopped after a 112-byte
`predecessor-bound` ledger prefix. The generic error 5 cannot distinguish that row's flush,
the first process/module check, or the next ledger write. Two real-C fault reproductions
produce that same prefix. Replaying it or removing a claim would not resolve the uncertainty.

This new `cpumeta` job is independent of the CPU-availability route. It never launches its
CPU probe/controller, consumes an edge, publishes CPU readiness or changes old claim files.
The two diagnostic executables and `job.json` are the only payload files: no MortScript,
restart, registry/device/driver operation, PMU instruction or clock/voltage writer is included.

## Logging and identity

The observer derives its exact job/module path and accepts only its own job ID argument.
It creates its local journal once. Before each ordinary API call it flushes a stage record;
afterward it records the return and immediately captured error. A missing result after a
stage means unknown—not proof that the API itself failed. Refusal before safe path/identity
resolution intentionally leaves no child journal; the independent outer outcome remains.

It loads only the qualified installed Toolhelp library and resolves six ordinary exports.
It observes its own PID and a collector parent resolved by the self process entry's parent
PID plus exactly one matching collector process entry. It then records bounded self and
collector module enumerations: numeric shape/PID predicates, terminal errors/counts and only
the first two UTF-16-hex module-name/path samples per role. Other process names are not copied.
No DLL-name fallback or guessed export ordinal exists.

An absent EXE in an otherwise complete module list is recorded as zero. That observation
neither weakens the existing CPU preflight nor grants permission to repeat it. Future changes
must use the actual return, not infer historical behavior from a later successful snapshot.

A clean metadata observation is not a CPU-rate measurement. `cpu_access_qualified`,
`cpu_rate_qualified`, `write_authorized` and `retry_safe` remain false in every host result.

## Independent collection and bounds

The separate collector holds a read-only lock on its exact hashed observer executable,
retains a fresh local entry marker, and independently records the observer's exit. It copies
at most 32,768 journal bytes with size/CRC binding and marks collection only after closing
its own report and evidence handle. Partial or late bytes cannot promote a failed child.
The payload's six source dependencies, compiler configuration, executable hashes and lengths
are bound by dispatch/result/manifest receipts and checked before staging.

The observer has a cooperative 15-second budget, 512-process and 256-module-per-role limits,
and a 32,768-byte journal cap. The collector's nominal 20-second wait is clamped to its
remaining overall budget. Synchronous CE calls cannot be forcibly bounded; timed-out work
is not automatically terminated, retried or considered quiescent.

Host parsing separately exposes collection integrity, completed diagnostic and complete
valid enumeration. Strict observed proof requires the full successful API trace, normal
end code 18, PID-bound identities, counts and consistent sampled predicates. Failed API,
missing identity/sample, zero PID, altered flags or reordered traces cannot become valid
enumeration. Successful API returns may carry a nonzero captured last error; that alone is
not treated as failure. API/predicate failures remain useful inconclusive diagnostics.

## Verification

135 focused checks pass, including actual C observer bytes and exit status through the
actual C collector into host analysis, strict warnings, ASan/UBSan, exact 512/256 limits,
32 KiB multi-chunk CRC, growing/shrinking sources, unknown errors, replay and final-I/O faults.
Independent security, performance and test reviews closed parser proof/sample consistency
and builder failure-receipt defects. No full CI, server run or production build ran.

One isolated experimental CE build failed strict indentation warnings and was retained as
failed, never deployed. A whitespace-only correction passed without weakening compiler
flags or host warning checks. The final bundle binds source commit `b0331f1`.

Both final ARM/CE executables import only COREDLL (31/35 names resolve in the inspected
candidate firmware). All 4,417 disassembly words match executable bytes; neither binary has
CP15/MRC/MCR instructions. Normal CE SDK shared-user-data reads for process identity are not
PMU/MMIO clock access. Candidate availability is not live firmware identity or permission.
Source/test commits remain local. Documentation alone is published separately.

## Reviewed final executables

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `s2amcpumeta.exe` | 15,360 | `392fae4deb53239b4ee44df9f6520d91d344e332f166029c571d57949e2b4483` |
| `s2ammetajob.exe` | 11,776 | `3a377701ab50c63ef0c92f5de88787b6591c17a859e71c2128d15ef59d818fe5` |

Codex led integration/USB operations; a live Qwen/DeepSeek peer implemented the separately
owned host parser/tests and reviewed test gaps. Native agents and independent source/binary
reviewers supplied bounded parallel work. Peer worktrees and all source changes remain local;
only project-safe documentation is published.

## Next boundary

After the metadata return, preserve original bytes before import and distinguish library
loading, export/enum errors, process identity, module-list predicates and journal completion.
Only then revise the gated CPU-read path. Existing baseline/timer observations and a +4%
arithmetic target do not qualify CPU frequency, fitted-part/rail/thermal limits, policy or
suspend exclusion, or independent recovery. No overclock is installed or qualified.
