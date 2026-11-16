# SYNC 2 clock investigation
The November 16 car run demonstrates the PMIC read route and corrected registry capture; no CPU-frequency selector has been discovered.

## Targeted follow-up prepared, November 16

`s2am job clock --modules` pairs the v2 PMIC reader with a fixed eight-file inspector.
Register 28 adds SW1 mode/SID configuration; registers 7/24 retain their demonstrated read
route. The v2 helper is still untested in the car. SW1HI is rejected before any voltage
interpretation, including historical v1 reports.

The inspector records per-file attributes/errors and copies only ordinary files, with a
4 MiB per-file cap and a cooperative 60-second budget. ROM modules remain metadata only.
Length/CRC checks distinguish verified copies from partial files; completion does not imply
any module was recovered. Details and source references are in
[CLOCK-METHOD.md](../docs/CLOCK-METHOD.md#prepared-follow-up-clock---modules).

Thirty-three focused tests pass across PMIC, module and combined-job behavior. Independent
security, performance and correctness/tests review found and resolved unsupported SW1HI
decoding and missing deadline checks during short writes/final verification. The final
helpers are built on `ant-srv-001`, with warnings as errors and CE ARM/COREDLL-only checks.
No full CI runs for this experimental change. The USB remains with its owner; this preparation
does not write to it. No frequency/voltage change or installable overclock is available.

Job `20261116-082901-clock-d9b3` is available locally after server compilation and packing:
179,240 bytes, six payload files, byte-identical unpack verification. Three native binary
checks also pass; the optional local Docker build test is skipped. The pack expires on
November 17, 2026, at 10:35 Swedish time; rebuild the pack after that window rather than
using the expired artifact. USB preparation and the car run are still outstanding.

Next: run this diagnostic after preparing the identified stick, import both reports, then
analyze any verified files. If the key files are ROM modules, obtain and match the firmware
image offline; the exact `3.10.16180.EA` payload has not yet been obtained.

## Latest car result, November 16

Both diagnostics in `20261115-214729-clock-9792` completed. The returned pack and imported
reports match the preserved originals. PMIC identification/SW1 reads returned presets of
1050/1050/700 mV (normal/DVS/standby), not an active CPU-voltage measurement.

The registry contains 950 keys, 3,792 values and 49 withheld values. All five requested roots
are present with no recorded errors/limit markers. There are 116 active entries; 104 references
resolve directly, while 12 remain withheld, including three unnamed entries. No higher point
or complete table capped at 600 MHz has been established. Current route: interface discovery,
with exact CSPDDK and AutoPM module analysis next. See the
[full findings](../docs/CLOCK-CAPTURE-2026-11-16.md).

## Datasheet comparison, November 16

The [small-experiment assessment](../docs/CLOCK-METHOD.md#datasheet-comparison-for-a-small-experiment)
compares automotive/industrial VDDGP 0.95/1.00/1.10 V through 600 MHz with the consumer
1.05/1.10/1.15 V range through 800 MHz. Fitted grade is still unknown. The observed 1.05 V
presets do not demonstrate headroom: MC13892 output tolerance is ±50 mV under specified
conditions; rail mapping, SID/standby mode and loaded CPU voltage remain unresolved.

620–630 MHz is a conditional investigation range (+3.3–5.0% ideal CPU capacity), with unchanged
active voltage policy as the initial hypothesis. It is not an available or qualified operating
point. CPU-only transition/restore behavior, dependent clocks and thermal evidence still need
verification. No new hardware job or voltage/frequency write was prepared. Documentation and
arithmetic were reviewed; no build or CI is needed for this comparison.

## Earlier evidence audit, November 15

- The completed capture contains 116 active-device entries: 106 named and 10 unnamed.
- The registry exporter withheld every active device's `Key` reference as a potential credential.
- No explicit DVFC driver or CPU frequency selector was found in the captured text.
- Six of 21 requested files copied. Missing files have no recorded copy errors or attributes, so ROM restrictions remain an inference.
- The CPU was measured at 600 MHz; active core voltage and the memory clock source remain unknown.

## Implementation and verification

Commit `6d9e3dc` on `fix/clock-evidence` retains bounded, validated driver references while preserving credential filtering and corrects `docs/PERFORMANCE.md`. Nine focused registry tests pass, including malformed input and credential cases. Independent security, performance and tests reviews found no blocking issues. Both readers compile for Windows CE and completed in the November 16 car run. No clock-change implementation is available. Full CI was not run for this experimental development change.

## Next evidence

Resolve remaining structural identities and obtain exact clock/power module implementations. Record per-file attributes and copy errors before attributing missing files to ROM. Check actual Ford driver interfaces against the Freescale reference BSP; a documented reference interface does not prove that Ford ships it.

Reference: [Freescale i.MX51 CE 6.0 BSP manual, chapters 7 and 9](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/9897/1/481-WCE600_MX51_ER_1104_ReferenceManual.pdf).

## Further investigation and PMIC diagnostic

The follow-up is documented in [CLOCK-METHOD.md](../docs/CLOCK-METHOD.md). Existing reference
DVFC interfaces select compiled operating points; driver discovery alone does not establish
700 MHz support. The observed 58% AutoKit share is delivered CPU time under saturation, not
its unconstrained demand. No clock-change command or tested target frequency is available.

An ordinary application now reads identification and SW1 presets through the existing `PMI1:`
driver, using the reference Freescale read ABI. It checks identity before reading SW1 and has
no hardware-write interface. Normal/DVS/standby presets do not identify the active voltage.
The two fixed reads now have real-car evidence; other operations and active rail interpretation remain unverified.

The PMIC and registry helpers compiled on `ant-srv-001` with warnings as errors and passed CE
ARM/COREDLL-only checks. Eight PMIC tests, nine registry tests and three native binary checks
pass; the optional Docker build test was skipped locally. Review found and fixed interrupted
snapshot overwrite and oversized completion-marker acceptance. This host validation preceded
the November 16 car test; no full CI ran.
The standalone jobs were initially staged without install packs. A subsequent one-stick
request produced the combined diagnostic described below.

The bounded advisory review completed with `codex + agy`, no skipped providers. The synthesis
rejects speculative memory-scaling factors and an unsupported decoder-demand upper bound;
target performance still needs car measurement. See the finalized
[consultation](multi-consult/c5f58d8b-a1b5-4561-8b5e-69b359e1cb8f.md).

## Combined capture prepared November 15

`s2am job clock` runs the same two readers in one install, with one report folder and no reboot.
It captures Drivers, Services, System, Init and Platform to depth 8, while retaining separate
completion checks. Three combined-job tests and the existing eight PMIC/nine registry tests
pass. Three independent reviewers found no blockers; misleading overall wait wording was fixed.

Job `20261115-214729-clock-9792` was packed on `ant-srv-001`: 180,968 bytes, six payload files,
all byte-identical after unpacking. The pack and a Swedish instruction were written to the
identified SanDisk SYNC stick after backing up 665 existing files. The first read-back matched.
The earlier decoder package and instruction were archived; the second stick was not changed.
This pack must be used before November 17, 2026, 10:35 Swedish time.

The final check completed on November 16 after the SanDisk was reconnected and identified by
its volume UUID and device model. The install pack, pending-job record and Swedish instruction
matched byte for byte; the package remained valid. The stick was then successfully ejected.
Nothing was rebuilt or rewritten. At that pre-car check the owner confirmed it had not yet run;
no run marker or report was present. The prior remount interruption was resolved. The subsequent
successful car result is recorded above.

## Outcome plan and offline trial preparation

[CLOCK-OUTCOMES.md](../docs/CLOCK-OUTCOMES.md) now specifies the three routes: a verified higher
CPU operating point, a genuine 600 MHz table/policy limit, and no discovered DVFC interface.
Incomplete evidence is a separate unresolved outcome. The current discovery capture cannot
itself recover compiled tables, live frequency, active core voltage or CPU temperature.

`tools/clock_trial_model.py` prepares inert trial/undo proposals and eight synthetic fault
traces. It has no hardware backend, native launcher or install-pack path. The 600-to-667 example
and thermal limits are fixtures, not car operating settings. Every artifact is marked
`simulation_only` and `deployable: false`; it cannot be parsed as an s2am install job.

Sixteen focused model tests pass. Independent security, performance and tests/evidence reviews
found and verified fixes for faults during pending application, missed telemetry deadlines,
missing readback and late restoration. Pending operations never release concurrent undo;
incomplete or timed-out restoration remains unresolved. This validates the model, not physical
recovery. No full CI or car test ran for this offline preparation.

A future live job needs matching image/interface/table and thermal/recovery evidence, then an
explicit execution go bound to the final proposal. The offline preparation itself performs no USB or car work.
