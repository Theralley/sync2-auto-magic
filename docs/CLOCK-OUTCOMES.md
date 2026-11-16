# Clock outcomes, trial preparation and restoration
Three routes are prepared for the returned `clock-9792` evidence; no live clock-change job exists yet.

## Current working hypothesis

The strongest current observation is **no explicit CPU-frequency selector discovered**. That
makes interface discovery/platform work the working route, not proof that DVFC is absent.
There is no evidence-based probability estimate. The [returned `clock-9792` capture](CLOCK-CAPTURE-2026-11-16.md)
resolves 104/116 active references, with 12 still withheld and no explicit CPU selector found.
Do not label 667 or 700 MHz a qualified or
available operating point before the exact deployed implementation and fitted hardware agree.

Here, qualification means an explicit engineering assessment for the bounded experiment, with
the fitted part's published rating recorded separately. A BSP table entry does not make an
above-rating point manufacturer-supported, and owner acceptance does not supply its missing
clock/rail dependencies or restoration contract.

`clock-9792` collects five registry roots and two PMIC registers. It does not fetch driver
binaries, enumerate compiled operating points, measure live CPU frequency or temperature, or
identify the active CPU rail voltage. A successful installation alone cannot select a route.

## First decision after import

1. Preserve the original report and compute hashes. Match the job/device identity to the
   planned capture. Check both completion markers against their reports.
2. Check registry errors, truncation, withheld/oversized values and coverage of all requested
   roots. `T|complete` is not proof that every key was readable: individual enumeration/open
   failures and the depth/output bounds limit absence claims.
3. Resolve Active `Name` and `Key` to the corresponding configuration's `Dll`, `Prefix`,
   `Index`, load flags and interface metadata. Follow unexplained/unnamed entries. An `Hnd`
   value is instance metadata, not a handle another process can reuse.
4. Treat PMIC values as identification and SW1 presets only. A failed PMIC read does not imply
   no DVFC. A frequency-like registry number does not establish a live frequency or table.
5. If the evidence is incomplete, keep the outcome **unresolved**, retrieve the specific
   missing evidence, and make no frequency-change package.

## Plan for each substantive outcome

| Outcome supported by exact-image evidence | Immediate next work | Trial decision |
|---|---|---|
| **A. CPU DVFC has a higher operating point** | Identify the precise device/firmware/driver, complete CPU table, selection/query contract, current request/policy ownership and full baseline state. Match the fitted CPU/board to the point's voltage/domain requirements. | Propose the lowest strictly higher qualified point within the agreed ceiling. If the next point is 800 MHz, do not invent 667/700 or silently choose 800. Prepare a bounded transient request and matching undo only against the verified contract. |
| **B. DVFC's maximum is 600 MHz** | Distinguish a runtime policy cap from a compiled-table maximum. Trace any cap to its implementation and inspect the complete table. A single observed 600 MHz state is insufficient. | If a qualified higher point already exists behind a policy constraint, establish the policy's purpose and return to A only when that constraint can legitimately be changed. If the table truly ends at 600, an application cannot select an absent point: specify a platform/BSP change and validate it before creating a trial. |
| **C. No DVFC was discovered** | Resolve remaining driver/service references; obtain the exact image/module identities. Inspect matching CSPDDK/OAL/power-management interfaces and authoritative ABI/source material. Record what the search covers. | An existing OEM interface can lead back to A or B. If no suitable interface exists, the next deliverable is board-specific platform support with a complete transition/restore contract, not an application that guesses registers or IOCTLs. |

The reference BSP documents application access via `SetDevicePower`, a separate CPU-domain
stream, platform-specific state mapping, and a compiled setpoint array. Its mapping is not a
Ford mapping. CPU and DDR can share a clock source, so a CPU target cannot be assumed to leave
memory unaffected. Source: [Freescale i.MX51 CE 6.0 BSP manual, chapter 9](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/56630/1/WCE600_MX51_ER_1104_ReferenceManual.pdf).

### Concrete deliverables for the current discovery/platform route

1. **Image identity record:** driver-to-module mapping, firmware version and available hashes.
   Use matching locally available firmware/source or a purpose-built metadata capture when
   ordinary ROM file copying is unavailable. The six copied files do not supply the missing
   clock implementation; file attributes/errors are needed before selecting a retrieval method.
2. **Interface/table record:** domain, table bounds/count, selector, CPU frequency, voltage
   requirements, restrictions and dependent clock configuration, tied to that exact image.
   Inspect a complete implementation, not just a matching string/constant/export.
3. **Transition contract:** coordination with Ford power management, ownership/release of a
   request, synchronization, failure/timeout semantics and suspend/reset behavior. If a new
   operating point is needed, specify it here; no numeric point or voltage is filled in now.
4. **Recovery proof:** establish restoration while responsive and a separately demonstrated
   recovery path for CPU/DDR/kernel loss of service. Verify what survives a reset, including
   PMIC state. Do not assume a reboot restores everything.
5. **Candidate implementation:** after those records resolve the method, implement the adapter
   and matching undo, then validate on a recoverable bench setup before the approved car trial.
   The offline model below can exercise orchestration meanwhile; it is not that adapter.

## Trial and undo contract being prepared

Bind a future trial to immutable hashes of the exact device identity, CPU grade/revision,
firmware, involved modules, ABI/table, evidence reports, thermal/recovery contracts and final
artifact. Hashes identify the reviewed material; they do not prove its assertions. Bind Rasmus's
go to that final artifact and its limits. Changed evidence, target, firmware or recovery method
requires a new review of that plan. No USB/car execution is authorized by the synthetic model.

The first trial is one temporary request to one verified higher point, with no persistent boot
configuration change and no automatic retry. Capture the full baseline: selected point, active
rail/domain state, policy caps and request ownership. Prepare undo before the target request.
Undo must restore that baseline and release only the trial's own request; forcing "600 MHz"
indefinitely could itself interfere with Ford's normal policy.

The local model uses a **30-second restoration deadline starting before application**. That is
an orchestration fixture, not a guaranteed upper bound on hardware exposure. Check baseline
readback, fresh temperature/stability samples and a durably recorded recovery intent before a
real apply operation. Once active, request restoration on deadline, cancellation, excessive
temperature/rise, stale/missing telemetry, state mismatch, stability error or journal failure.

If an apply call is still pending, mark the outcome unresolved. Do not issue concurrent undo:
the late apply could otherwise complete after restoration. Wait for demonstrated quiescence
and independent readback before any responsive-software restoration attempt. A failed restore,
timeout or incomplete/wrong readback is unresolved, never restored. A duplicate or interrupted
run must not reapply automatically.

Thermal/stability/journal faults are latched even while application is pending. The old sample's
freshness deadline is checked before accepting a new sample. A completion without independent
readback cannot release the pending operation; a later complete event refers to that same
operation, not a retry. A restore completion past its model deadline remains unresolved even
if it reports the baseline; its late observation is retained for review.

**Automatic restoration is best effort while the OS and verified driver remain responsive.**
A timer/thread/process on the same CPU cannot guarantee recovery from CPU lockup, unstable
DDR, a blocked kernel/driver, power loss or controller failure. An undo USB needs working USB
and update services. A separate watchdog's existence does not prove it resets this failure or
restores the full baseline. No such recovery guarantee has been established on this car.

## Temperature and stability logging

The existing code has CPU/process/memory load and UI/process heartbeat logging, and a timing-loop
clock estimate. It has no verified CPU temperature measurement. SW1 presets are not a thermal
sensor, and PMIC die temperature would not be CPU junction temperature. Do not substitute
unverified ADC channels or placeholder zeroes for measurements.

Establish the sensor's physical location, calibration/units, update rate and error signaling,
then derive thresholds from the fitted part and board evidence. If the required sensor is
unavailable, thermal preflight is unresolved; investigate documented read-only telemetry or
independent bench instrumentation. Surface temperature is not automatically junction temperature.
The model's 80 °C ceiling and 5 °C rise are **synthetic fault-test numbers**, not proposed limits.

A future timestamped log must retain the requested/observed point, raw frequency measurement
and timing-source identity, rail selection/state or explicit unknown, sensor provenance/value,
CPU load, workload/checksum status, UI heartbeat, audio interruptions, frame timings, drops and
backlog, and every apply/restore result. Before using the timing-loop estimate, verify that its
reference timer is independent of the changed clock. Startup frequency metadata is insufficient.

Use repeated baseline–target–baseline runs with identical input, resolution/frame rate and
background state. Keep a separate correctness check on decoded output. Compare completed work,
latency and interruptions, not CPU percentage alone. A short successful trial does not establish
long-term stability or hot-weather margins.

## Runnable preparation on the Mac

```sh
python3 -m unittest discover -s tests -p test_clock_trial_model.py
python3 tools/clock_trial_model.py --out build/clock-trial-model-mm-fordoc-2255
```

The output directory must be new. It contains a bound trial proposal, matching undo proposal,
and eight synthetic traces: normal deadline, temperature, missing telemetry, blocked apply,
late apply, failed restore, cancellation and controller loss. Tests also cover invalid clocks,
stale baseline, evidence/approval mismatch, invalid sensor data, duplicate calls and full-state
restoration. Every artifact says `simulation_only` and `deployable: false`.

This tool has **no hardware backend, native launcher, raw IOCTL/MMIO interface or pack builder**.
Its proposals cannot be parsed as s2am install jobs. The synthetic 600→667 example demonstrates
orchestration only; neither that point nor its symbolic rail/domain profiles describes the car.
The thermal/stability records are generated fixtures, not measurements. A passing rehearsal
proves only the modeled event handling. Live selection, telemetry and undo remain to be
implemented against the evidence and tested before Rasmus's execution go.
