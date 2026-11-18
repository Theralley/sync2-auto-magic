# One-shot owned-state recovery and read-only clock baseline
The complete November 18 observation permits a reviewed, narrowly bound recovery attempt—not an overclock and not unrestricted retry permission.

## What returned from the car

The v2 observer exited cleanly. Its returned package and report binding match the prepared
job. It confirmed the old claim identity and the exact old DLL path: **146 UTF-16 bytes**.
It completed 116 Active-entry observations, found no matching key, and inspected all three
reported user-driver hosts (34, 3 and 6 modules), with no old DLL match. No controller was
reported among 12 processes. These are point-in-time observations, not universal absence proof.

The original controller journal and parent envelope independently establish a **returned
activation failure 1610 and controlled exit**, not a controller still waiting in that call.
All five original source hashes match the preserved commit. Combined with the candidate
Device Manager's 128-byte `Dll` limit, these results justify implementing one bounded recovery.
Candidate/live firmware byte identity remains unproven.

## This successor changes configuration state, not hardware clocks

Do not describe this package as wholly read-only. It may delete **one exactly verified flat
registry key**, then temporarily activate the existing fixed-address reader. It performs
**no frequency, voltage, timer or PLL writes** and makes no persistent boot registration.

Before deleting anything it:

1. Creates a durable, exclusive recovery latch. A failed or partial attempt keeps the latch.
2. Read-locks the unchanged original claim, entry, exact failure journal and hash-bound old DLL.
3. Verifies and read-locks the new DLL, controller and observer artifacts.
4. Checks all seven original registry names, types and exact values, rejecting extra values/subkeys.
5. Runs two fresh bounded observations. Errors, matches, malformed paths, missing APIs or
   changing host membership refuse execution without deletion.
6. Rechecks the exact registry contract immediately before the fixed-key deletion.

Deletion is preceded by flushed intent on both the car and USB. The relevant registry parent
is flushed and key absence is read back. Only then is launch intent flushed. A separate readiness
receipt is written, flushed and closed under a pending name before non-overwriting publication.
The recovery-built controller independently requires the old claim, acquisition latch and
exact per-job readiness receipt, retaining its own read locks throughout the reader lifecycle.
The early acquisition latch alone can never authorize activation.

The original claim and all original evidence remain. No global barrier is released. No host
is killed, no unknown activation handle is deactivated, no DLL is deleted and no automatic
retry is attempted. The new controller still creates a fresh key, verifies stream/device
identity, obtains exactly 64 fixed reads, and attempts its ordinary close/deactivation/owned-key
cleanup. Its staged `c.dll` path is **126 UTF-16 bytes including NUL**, below the candidate limit.

## Failure semantics

- A refusal or timeout is not permission to replay or run a generic undo stick.
- `done.txt` means collection, not successful activation or a verified snapshot.
- Import requires the exact ordered recovery record, trusted job identity, clean child exit,
  byte count/CRC, complete stable snapshot and cleanup markers.
- The 60-second cooperative budget and 15-second child waits cannot cancel a blocked CE API.
- A registry handle is not a lock against arbitrary privileged registry writers. The design
  serializes known participants and assumes other trusted local code does not deliberately
  replace this private test key between its last check and deletion.
- A later experiment needs its own reviewed successor transaction; the latch is retained even
  after successful readout.

## Verification

Independent security, performance/artifact and tests reviews approve this limited scope.
The security pass found and corrected an acquisition-latch authorization gap before packaging.
There are **73 passing targeted tests** across recovery, transaction, controller, driver and
launcher modules. The real recovery `WinMain` is exercised in 30 host scenarios, including
wrong ownership/artifacts, observer errors, key deletion/flush/readback failures, six readiness
publication failures, crash boundaries, timeout and replay. The transaction fixture substitutes
only the old DLL digest with a fixture digest; SHA vectors are separately checked.

The first native compile rejected two misleading-indentation warnings. Those line breaks were
corrected, and the fresh digest-pinned CE ARM build passed with warnings-as-errors. All four
artifacts pass source/binary/receipt binding and CE ARM/subsystem checks. All imports and the
new move API exist in candidate COREDLL; driver exports match the fixed stream interface.
Host mocks do not prove live CE locking, rename, mapping permission or physical-car safety.
No full Mac CI or production build was run.

## Parked-car procedure

1. Start SYNC normally while parked and leave AutoKit.
2. Insert the identified diagnostic stick once; wait for `Install successfully completed`.
3. Leave it inserted another minute, then return it for analysis.
4. If there is an error or no completion, photograph the message and return the stick.
   Do not repeatedly reinsert or use a generic recovery stick for this transaction.

Only a verified reader return unlocks baseline interpretation. See the
[conditional next-step plan](CLOCK-NEXT-STEPS-2026-11-17.md). No overclock is in this package.

## Concrete later timer/dependency work

Candidate NK implements its performance counter using EPIT1 (`0x73fac000`). Its initialization
selects source 2 and prescaler 0; candidate CCM routes the high-frequency input through a
24 MHz oscillator / 3 path, consistent with the reported **8 MHz** counter frequency and
independent of PLL1 under those assumed routes. This is a static candidate explanation,
not a confirmed live callback binding.

A later separately reviewed collector can read fixed EPIT1 control and optionally bracket its
counter with QPC while rejecting rollover/discontinuity/suspend. It must not read/write timer
status, compare, reset or load registers. Existing CCSR/CBCMR/CBCDR/CSCMR1/CSCMR2 already allow
much of the consumer graph to be decoded offline; DDR must be traced through AXI_A and the
main-bus mux, not merely labeled “AXI_A”. CCOSR is a specific missing clock-output observation,
not justification for an unrestricted register dump.

The useful arithmetic trial candidate remains 600→624 MHz, subject to a live baseline, actual
silicon/rail/thermal evidence, policy serialization, independent measurement and demonstrated
recovery. No 700/800 MHz promise follows.

Sources: [NXP reference manual](https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf),
[Freescale clock implementation](https://raw.githubusercontent.com/torvalds/linux/v6.6/drivers/clk/imx/clk-imx5.c),
and [candidate firmware provenance](CLOCK-FIRMWARE-ANALYSIS-2026-11-16.md).
