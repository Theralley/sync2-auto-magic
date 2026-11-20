# Proposed raw load observer — November 20, 2026
Codex and the live Qwen peer recommend a separate ordinary-API observer, not another loop-based CPU-frequency estimator.

## Decision and scope

Design only: no new logger source, executable, install job or vehicle test is supplied
by this note. The proposed `S2AM-LOAD,1` format is not yet a frozen wire contract.
Codex retains integration/publication ownership; Qwen's parser implementation offer
has not been activated. Existing code and archived reports remain unchanged.

The next useful diagnostic would improve CPU-time attribution while CarPlay runs.
It would not solve the missing independent frequency, fitted-grade or recovery evidence
in [[clock-evidence-boundary-2026-11-20]].

## Why replace rather than repeat the old measurement

Independent source inspection of `s2amdrive.c` found that its load mode:

- Matches previous thread accounting by TID alone and discards creation time.
- Can charge a newly observed thread's lifetime CPU usage to the latest interval.
- Divides by a shared interval although individual reads occur at different times.
- Does not expose per-read failures or table truncation sufficiently for completeness.
- Clamps excessive idle deltas and runs the add-loop clock estimate during load capture.

These limitations do not prove every historical sample wrong. They prevent treating
an old share such as AutoKit's 58% as exact isolated decoder cost.

## Proposed signals

- Ordinary `OpenThread(THREAD_QUERY_INFORMATION)`, `GetThreadTimes`, Toolhelp and
  QPC/QPF APIs; no driver, MMIO, PMU, benchmark, screenshots or copied app logs.
- Per-thread identity `(PID, TID, creation FILETIME)`, full-width kernel/user CPU times,
  and QPC before/after each read. Unknown/zero creation means no cross-round delta.
- Process executable basenames and snapshot priorities for context; no command lines,
  window titles, screen contents, VIN or serial collection. Do not identify a thread
  as the video decoder from its CPU share alone.
- Raw idle-counter values with their own read brackets and API status. Unsupported,
  regressing or implausible deltas are unknown, never clamped to a plausible percentage.
  Passing plausibility checks is not independent validation of OEM idle semantics.
- Explicit enumeration termination, attempted/read/error counts, truncation and partial
  flags. A missing thread is missing/last-observed, not proven terminated; no final
  CPU delta may be invented for it.
- Collector elapsed latency separately from its own thread's accounted CPU-time delta
  across rounds. Neither measures all indirect OS/I/O cost caused by the logger.

[Microsoft's CE GetThreadTimes contract](https://learn.microsoft.com/en-us/previous-versions/ms908464(v=msdn.10))
defines 64-bit FILETIME units and warns that OEM support varies. API presence does not
establish usable creation timestamps, accounting resolution or accuracy on this unit.

## Proposed bounds and analysis

Use a fixed maximum of 60 snapshots at a nominal five-second cadence, with at most
512 thread entries per snapshot. The first observation is a baseline: at most 59
successive intervals result. Include time spent late/collecting; do not run catch-up
bursts. Fixed loop/call counts do not guarantee cancellation of a stuck OS API.

The host derives deltas only between valid, consecutive observations of the same
identity. A FILETIME crossing 2^32 must remain correct; decreasing/reset 64-bit CPU
accounting is invalid, not silently wrapped. Failed or missing observations break the
delta chain. Every newly observed identity, including mid-run, is baseline-only on its
first observation. Changed QPF or nonpositive/overlapping temporal bounds invalidate a share.

Use gaps between successive read brackets, not the duration of a single API call, as
the elapsed denominator. Preserve sampling skew and uncertainty; do not present sums
of differently timed thread shares as an exact simultaneous process percentage.
No fixed one-millisecond accounting resolution is assumed without platform evidence.

Output means observed CPU-time distribution and coverage only. Low thread CPU time
can reflect blocking, starvation or other causes; high kernel time is not proof of I/O
waiting. CPU saturation alone does not establish decoder identity, frame latency,
the root bottleneck or benefit from a 4% clock increase. Never emit physical MHz,
overclock qualification or write permission, or connect this observer to clock control.

## Implementation acceptance before any deployment decision

Freeze an exact bounded schema, output/publication rules and launch/collection lifecycle
before separate native/parser implementation. Test TID/PID reuse, new/missing threads,
zero creation, failed reads, partial snapshots, full-width counters, idle anomalies,
skewed brackets, timer errors, caps and malformed/truncated output. Measure collector
CPU cost rather than promising negligible overhead. Native CE builds belong on the
build server; host fixtures cannot establish on-car correctness.

Planned files are `s2am/native/s2amload.c`, `s2am/load_observer.py` and focused native/
host tests. Before activating separate implementation scopes, freeze the exact bracket
endpoints, per-thread status taxonomy, byte/line limits and partial/complete file rules.

Defer the simultaneous PLL1/CCM logger: sampled configuration is not counted CPU cycles,
and matching endpoints do not exclude an intermediate change. Privileged PMU work is a
new permission boundary, not an extension of the existing user-mode reader. Repeating
the cached boot-maximum query adds no live-frequency evidence.
