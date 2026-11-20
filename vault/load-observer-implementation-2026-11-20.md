# Raw load observer implementation — November 20, 2026
Native collector and host parser are implemented and host-tested; no CE executable or USB delivery is ready.

## Later build-route update

The server became network-reachable but refuses SSH authentication. An explicit
GitHub Actions build-only alternative is prepared locally, pinned to the owned
repository and one non-main build branch, with read-only permissions, pinned actions,
offline compiler and run/attempt-bound receipts. Its additional routing regressions
bring the focused test total to 73. The prospective publication branch is based on
already-public history and contains only the selected observer changes, not unrelated
local development ancestry. No code has been pushed or Actions build dispatched:
publication to the public repository is awaiting explicit owner authorization.
Neither route has produced a CE executable. The USB remains unchanged.

## Implemented locally

Local branch `feat/raw-load-20261120` contains the frozen v1 contract, ordinary-API
`s2amload.c` collector, strict `load_observer.py` parser, report CLI and server-only
build helper. Reviewed code commit: `eb0831461fc9f1f2917534cee63567a65baa9ee9`.
Code has not been pushed, merged, released or installed. This published vault note
does not imply that its documentation branch contains the implementation files.

The live Qwen peer implemented the two parser/test files in a separate worktree;
Codex reviewed and integrated both commits, fixing complete-line truncation handling
and eliminating a misleading global PID-to-latest-process-name mapping. Codex owns
native code, integration, compilation and USB preparation. The peer lane is frozen.

The collector has no driver, spin benchmark, PMU/MMIO, registry or priority changes.
It buffers a bounded round before file I/O. It records full-width CPU times and
bracketed read attempts, with explicit partial/error/truncation status. New identities
are baseline-only. Self-accounted CPU and collection latency remain separate; indirect
OS/I/O cost is unmeasured. Clock qualification and write authority remain false.

## Verification actually performed

- 71 focused host unit-test methods pass across native collector, parser, build
  orchestration mocks and report CLI; no full repository gate suite was run.
- The real C producer runs under deterministic CE API fakes with ASan/UBSan. Seventeen
  success/partial/cap/width scenarios feed its actual bytes into the strict parser.
- Regressions cover thread identity/reuse, failed/zero-creation reads, skew, complete-line
  truncation, exact/overflow caps, enum-error normalization, optional idle, full-width
  accounting, signed priorities, tick wrap, admission expiry and result-file races.
- A review found an unchecked compiler-output read; bounded descriptor reads now reject
  oversized, symlink, FIFO and directory artifacts before PE validation. RED/GREEN
  tests preserve failed receipts and prohibit a success manifest on rejection.
- Targeted Clang static analysis, changed Python AST and whitespace checks pass.
  Independent security, performance and tests reviews have no remaining blocker.

These tests use host `wchar_t` and fake APIs; they do NOT verify CE ARM calling
conventions, 16-bit WCHAR layout, imports, actual execution cost or on-car behavior.

## Remaining before any ready-for-car claim

1. Restore access to `ant-srv-001`, currently unreachable from the active network.
   A hash-bound source request is saved but has not been dispatched. No Mac CE-build
   or full-CI fallback is allowed.
2. Compile on that server; verify ABI assertions, ARM/CE/COREDLL imports, source/binary
   hashes and disassembly. A passing host fixture is not an executable artifact.
3. Confirm whether CarPlay and the USB can remain connected simultaneously. The current
   collector writes next to its EXE and needs that volume throughout capture. If the
   port must be freed, add/review a unique car-side launch and later collection lifecycle
   before delivery; do not remove a USB holding an active executable/output.
4. Back up managed USB files, deploy only the reviewed artifacts, read back after
   remount, and eject safely. No USB file has been changed by this implementation task.

The frequency, fitted-grade and independent-recovery gates remain unresolved. This is
a CPU-time observer, not a clock solution. See [[load-observer-design-2026-11-20]] and
[[clock-evidence-boundary-2026-11-20]].
