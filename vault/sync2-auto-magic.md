# SYNC 2 clock investigation
Live clock baseline and timer qualification are verified; no overclock is qualified or deployed.

## New controlled successor USB ready, November 18

NO NAME now contains **`20261118-174115-cpuavail-dbf6`**, a new read-only v2 diagnostic.
Its **48,760-byte** pack has SHA-256
`34b579e33ac385ec36c073e15e29be44c18699c1e0728a6ea47c70c9924e1f4c`.
The official unpacker reproduced all five staged files exactly: three executables, the
predecessor receipt and `job.json`. No MortScript, restart or clock writer is included.

All 57 earlier managed USB files were backed up and hash-verified before mutation. Consumed
updater files and old root instructions were archived, not replayed. New pack, single pending
identity and Swedish instructions matched after ordinary unmount/remount; NO NAME was then
**safely ejected**. Other sticks were untouched. Valid before **December 17, 2026, 09:35:59 UTC**.

The source/test commit `84079ac` remains local. **116 focused checks** pass; three source
reviews and a separate compiled-artifact review clear this bounded read-only diagnostic.
The raw PE files matched all **7,027 disassembly words**. All 28/40/40 direct imports resolve
in the inspected candidate COREDLL; six ordinary Toolhelp exports and the actual candidate
structure sizes were checked. Candidate availability is not live firmware identity or
permission proof. No full CI, server run or production build was performed.

Insert **once while parked**, wait for the install completion message plus at least one
minute, then return the stick for preservation and import. Photograph an error and do not
repeat. Root instructions: `S2AM-CPU-SUCCESSOR-20261118.txt`. This completes USB preparation,
**not** on-car CPU observation, measured frequency or overclock qualification.


## Actual returned CPU diagnostic, November 18

The first CPU job `20261118-164459-cpuavail-3226` returned and was preserved before import.
Its 243-byte controller journal stopped at `E|api|debug-wait|258`, before positive debugger
attachment or gate release; the probe report is absent. The outer collector independently
observed controller exit 1. Import is **not verified**, not a CPU permission denial. No CPU
values, rate measurement, PMU enablement or clock change resulted.

The bound controller rejected CE's actual 258 poll-timeout form. A focused regression now
accepts that form while retaining the event/deadline bounds. Original reports, installed pack
and all one-shot state remain preserved; the consumed job must not be replayed.

The controlled v2 successor above retains the original claim, pins the exact predecessor
evidence, requires two fresh process checks and consumes one fixed predecessor edge. Its
probe starts behind a closed event and may read only after positive debugger attachment.
It never enables PMU or changes clocks. Its actual car return remains the next step.


## Historical first CPU diagnostic USB readiness, November 18

NO NAME now contains one new gated, three-layer CPU permission/control diagnostic,
`20261118-164459-cpuavail-3226`. Its 40,352-byte pack passed exact unpack comparison,
managed files were backed up, pack/pending/Swedish instructions matched after remount and
the stick was safely ejected. 140 focused tests and independent source/artifact reviews pass.
This is USB preparation only: no car result, measured CPU rate or overclock exists.
See [[clock-cpu-availability-2026-11-18]]; earlier readiness entries below are historical.

## Read-only CPU availability component, November 18

A standalone USEREN/PMNC/CNTENS probe and strict parser are implemented, host-fault-tested
and compiled as one experimental CE helper. It never enables PMU state or samples CPU
cycles. Combined targeted checks pass 72 tests. No car execution or new USB package exists;
fault-containing parent/one-shot integration remains the next component.
See [[clock-cpu-availability-2026-11-18]].

## Evidence-bound transition work, November 18

The preserved actual return now feeds an inert specification: seven captured facts met,
twelve prerequisites still unknown, +4% arithmetic ratio, no write authority or operations.
A hardware-independent transition/restoration coordinator passes host fault tests; no
hardware adapter or new USB package exists. Candidate process-local clock locking and the
PMU initialization path do not resolve policy exclusion or independent CPU-rate measurement.
See [[clock-transition-2026-11-18]] for the current boundary and next prerequisites.

## Verified live baseline and timer qualification, November 18

The controlled recovery and fixed reader completed in the car: 64 stable reads, clean child
exit and successful cleanup. A subsequent qualifier also completed with stable timer/gates,
informative one-to-one EPIT/QPC coherence and no enabled sampled PLL1-derived clock output.
Nominal 600 MHz assumes a 24 MHz oscillator; no independent frequency calibration or overclock
was performed. Suspend, policy ownership, physical limits and independent recovery remain
separate prerequisites. Do not repeat consumed jobs or remove retained ownership barriers.

See [[clock-baseline-2026-11-18]] and [[clock-qualification-return-2026-11-18]].
Older readiness entries below are historical snapshots.

## Latest verified results and source publication, November 16

The second native inspection, after the revised decoder attempt, verified stock active DLLs,
complete stock backup and intact staged candidate. Exact packaged MortScript analysis shows
`DelTree` deleted the empty report folder and the subsequent failed `WriteFile` stopped execution
before decoder copies. Cleanup now guards missing directories and recreates the report folder;
the corrected decoder package has not yet run in the car. An existing but unwritable report
directory can still stop the pre-swap marker write. The independent decoder undo remains available.

The reviewed read-only clock driver, controller, tests and six-step clock plan are now in the
repository. Nineteen focused driver tests and five parser tests pass; independent mutations
confirmed registry isolation checks reject kernel-mode flags and altered memory windows. The
candidate 624 MHz result depends on unverified assumptions; no live frequency change exists.
USB integration is ongoing separately. Older readiness and unresolved-status entries below are
historical snapshots.

## Development goals and latest return, November 16 evening

The public [development update](../docs/PROGRESS-2026-11-16.md) records three goals: verify an
own FFmpeg decoder in the car, compare foreground CarPlay priority, and establish a controlled
CPU-frequency experiment. This is experimental development, not a release or an available
overclock package.

The first native inspection verified all three active decoder DLLs as stock, with stock backups
and candidate staged files. Its harmless script probe completed; the separate clock child failed
at PLL1 mapping with error 87 and returned no clock registers. The later revised decoder job
again returned a matching consumed package with no report. The owner reports working Maps and
Spotify with no noticeable improvement at the existing 640×384/10/software setting.

Independent source and exact-interpreter analysis confirmed that DelTree on an absent child
can remove its empty parent report folder. The generator now checks child existence and
recreates the output directory. The latest active DLLs remain unresolved despite this diagnosis.
A fresh native inspection is prepared; the decoder undo remains unchanged.

The next priority comparison targets 250 only while AutoKit is alone in the foreground, with
restoration checked on exit/backgrounding. Its measurement option reuses the load logger;
sampling timestamps must be checked because higher-priority work can delay the sampler.

A separate temporary clock-driver prototype has 18 focused tests plus five existing parser
tests passing and a successful CE ARM server build. It only reads fixed PLL1/CCM registers;
independent review, integration and first car activation are pending. No CPU-frequency or
voltage change has been made. Earlier readiness entries below are historical snapshots.

Publication verification: 201 focused decoder/guard/theme tests pass with no skips; the
decoder simulation now follows the car-first transaction and covers missing USB readback and
report-only recovery. Independent security, performance and tests reviews pass after that fix.
Documentation links, changed Python syntax and diff whitespace checks pass. No full CI or new
native build was needed for this update. Ongoing experimental changes may be committed and
pushed after review without another approval request; release/car-validation status remains explicit.

## Native inspection ready, November 16

Job `20261116-182444-decdiag-4e4c` replaces the consumed red-stick package. Its 183,728-byte
pack has SHA-256 `f81d785ec35acd1df335cafed4fbf539acbfc9c8f3352fe202aad0c0cef32657`.
All eight payload files passed byte-for-byte server unpack verification. Seven hundred USB
files were backed up with hashes before preparation; pack, pending record and updated
instructions matched after unmount/remount, then the stick was safely ejected. The 2 GB undo
was not changed. Use before November 17, 10:35 Swedish time; car validation remains pending.

The owner reports AutoKit seems fine, plus an insertion where nothing happened; which
insertion and whether undo ran are unresolved. The remounted stick contained the identical
consumed return, not new result evidence. UpdateService ignores POST_APP launch failure and
exit status; MortRunner also silently returns zero on missing script/interpreter launch failure.
That establishes an observability gap, not this run's cause.

`decoder-inspect` selects a new native POST_APP, captures fourteen fixed active/backup/staged
files and old completion evidence, records storage/mount state, and separately observes a
fresh harmless script. It never replays the old swap. Imported expected hashes are bound to
the trusted local diagnostic job. Current disk classification leaves the old verdict unchanged.

A separate fixed read-only application samples PLL1/CCM through ordinary installed CEDDK APIs.
Candidate CEDDK mapping code and a potentially independent DDR boot route were identified.
The host requires clean child exit and all 64 stable bracketed register reads before interpreting
source/divider fields. Runtime permission and actual clocks are unverified; no overclock or
voltage change is applied. See [procedure and limits](../docs/DECODER-INSPECTION.md).

Verification: 45 focused tests; independent security, performance and tests reviews; five
additional real-C producer-to-parser/import scenarios preserved the earlier decoder verdict.
Both helpers were compiled on ant-srv-001 with warnings as errors and checked for CE ARM /
COREDLL-only imports; all 37/23 imports exist in candidate COREDLL, and both mapping exports
exist in candidate CEDDK. No full CI or Mac native/production build was run.

## Decoder return unresolved, November 16

`20261115-205200-dec-edc8` imported as `processed-no-report`. The returned `installed.bin`
matches the prepared pack SHA-256 below; `install.bin` is absent. No report directory for
this job exists on the returned stick. Four original return files were preserved and hashed
before import; the imported installer log matches the preserved copy.

The launcher and MortScript interpreter are byte-identical to the successful `clock-d9b3`
job. Their initial report-creation code also matches after normalizing job IDs; the decoder
script passes current structural checks. Both installer logs have the same two-line form,
so that log alone does not locate the failure. An independent review found no deterministic
package-startup defect. No installation, unchanged-car or performance claim is justified.

Next evidence: the observed SYNC message/error and current AutoKit behavior, including any
use of the undo stick. Do not blindly replay the ambiguous installation. No replacement job,
code change, native build or CI run was made during return analysis. The preparation section
below is historical; the red stick's package has been consumed.

## Decoder test sticks prepared again, November 16

At the owner's request, the existing `20261115-205200-dec-edc8` test was put back on the
identified red SYNC stick after backing up and hash-verifying 696 files / 134,120,779 bytes.
The pack, pending record and updated Swedish instructions matched after unmount/remount;
the stick was safely ejected. Pack SHA-256:
`0c656039f1711b277bd4fcfbdf9b6dafa1f8534f5cb1cc5b73357db3be388b32`.

The 2 GB undo stick already held matching `20261115-205211-dec-393a`. Its pack and pending
record verified; 130 files / 30,346,435 bytes were backed up before replacing its stale
instructions. It was safely ejected and the owner removed it. Undo pack SHA-256:
`745343c159ff6c494ff6d600096001e5d8654770a2c9c2ab26a901f367286dc2`.

Use both packages before November 17, 10:35 Swedish time; rewriting does not extend the
installer window. The decoder's three DLLs and system imports passed the existing ABI check
and comparison with the metadata-matched candidate firmware, including COREDLL forwards.
Actual-car decoder hashes are unavailable; latest inventory reports stock sizes and
640×384/10/software. First installation/loading and performance validation are still pending.

Keep that picture configuration and priority unchanged for the first A/B. Restart and warm
up equally before each condition. This package starts no load logger, so the initial trial
checks operation and visible behavior; paired CPU measurement needs separate logging jobs.
See [the current procedure](../docs/PERFORMANCE.md#next-useful-tests-november-16).

New static NEON evidence: candidate NK/kernel integrate FPSCR and D0–D31 context routines.
This supports preparing a separate user-mode instruction/context-switch probe, not assuming
NEON works in the car. No separate NEON build/test executable was located. No new binary,
native build, full CI or car clock change was made in this preparation. Three independent
reviews corrected matched warm-up wording and stale readiness text.

## Candidate binaries recovered and inspected, November 16

The SEC chunk wrapper and NAND page framing are decoded. Region id6 contains the matching
modules: 51-module XIP supplies CSPDDK/NK/kernel/COREDLL; targeted IMGFS extraction supplies
AutoPM and both PMIC drivers. All seven match the car's attributes, FILETIME and reported
size. The separate id7 image has different modules and must not be substituted. Matching
metadata is not proof of byte identity or independently trusted provenance.

Verification: 1,302 XIP page trailers, 18 selected IMGFS page trailers, exact stream lengths,
independent hashes of the three IMGFS code streams, and byte comparisons for all four
sections of CSPDDK/AutoPM/PMIC Pdk/PMIC SDK passed. The first 15 SEC chunks match the signed
catalog; its mathematical signature verifies with the embedded certificate. Independent
certificate trust and the remaining 236 chunks were not verified. No firmware was executed.

Actual implementation: CSPDDK's SetFreq accepts only PLL3 at 216/297 MHz; its setpoint APIs
use reference counts/events and need an actual consumer. A blocking call can wait forever.
AutoPM contains power-notification relay code, whose runtime operation is unverified.
PMIC STBYDVFS-named helpers are successful no-op stubs.
NK's fixed PLL1 startup configuration is consistent with 600 MHz. Its 800 MHz initialized
metadata is overwritten from boot data, not exposed as a selectable operating point.

See [offline analysis](../docs/CLOCK-FIRMWARE-ANALYSIS-2026-11-16.md) for precise scope,
source references and extraction provenance. Local reconstructed modules and disassembly
remain under ignored build artifacts. Public changes are documentation only; no full CI,
production/native build, USB operation or frequency/voltage change ran.

Next: identify a functioning CPU transition consumer/policy or specify the missing platform
support. No 620–630 MHz trial is ready, and another ordinary-file-copy car diagnostic is
unnecessary for these seven modules.

## Earlier: firmware candidate obtained, November 16

An unofficial `Gen2v310build16180updatepackageEULangpack2.rar` candidate was downloaded for
offline inspection from `https://lg3gservice.home.pl/pub/ford/`. It is not authenticated or
verified as the car's exact firmware, and its language-pack label differs from the Langpack5
file referenced by the upstream installation guide. Nothing was installed or written to USB.

- RAR: 627,971,109 bytes; SHA-256 `c671911a9dc8bde701585351cb9c6e00c928d5e06923b9c1ab31bf691c1aade5`.
- Contained `EA5T-14D544-BA.ZIP`: 348,759,140 bytes; SHA-256 `3e98dc7049424e82d628cb7d2e564f03dbdf474780dcfa47d04ffa8be9dc3f60`.
- Extracted `EA5T-14D544-BA.sec`: 2,104,594,708 bytes; SHA-256 `e7603abf483036a7836901c8f9656ab28e716bc39162e6b10542be71a2e6faff`. ZIP CRC verification passed.

The image contains the clock/power module names. A bounded 128 MiB byte-pattern scan found
timestamp/size combinations matching four car targets, including CSPDDK; this is preliminary
correlation, not decoded module identity or proof of authenticity. A single linear mapping
from candidate directory pointers to file offsets was not established. Next: understand the
image layout, recover actual modules and validate their identity before interface analysis.
No operating-point table or callable clock-changing method has been recovered yet.

The upstream Mega link yielded no downloaded files in the installed client. A bounded search
found no verified Ford-hosted EU 3.10 core package; exact candidate URLs on Ford's historical
download host returned 404. An available Ford language package does not provide the OS image.
The owner needs no new car/USB action; an existing original Ford package would help provenance
if available. No code, build or CI changes were made for this research.

## Module diagnostic returned, November 16

`20261116-082901-clock-d9b3` returned applied with both diagnostics complete. Fifteen return
artifacts were backed up; all thirteen imported files match the preserved report/updater
originals, and the returned pack matches the prepared hash. The USB was safely ejected.

PMIC register 28 is `6366281` (`0x612449`): SW1MODE 9, SID disabled. Normal/DVS/standby presets
remain 1050/1050/700 mV. Regulator-mode configuration does not measure active CPU voltage.
The fixed register-28 read now has car evidence; other PMIC operations remain unverified.

All seven existing targets have `0x2047` ROM-module attributes. `dvfc_mc13892.dll` returned
file-not-found for that exact name. Zero binaries copied; this substantiates ROM storage for
these targets without ruling out other clock-control implementations. Next: obtain a matching
firmware image and inspect clock/power modules offline. No repeated copy job or new car run
was prepared. See [capture findings](../docs/CLOCK-MODULE-CAPTURE-2026-11-16.md).

Independent PMIC interpretation agrees with the NXP datasheet. Documentation and evidence
checks only; no code, rebuild or CI. The readiness notes below describe the earlier state.

## Earlier: module diagnostic USB ready, November 16

Job `20261116-082901-clock-d9b3` is now on the identified SanDisk SYNC stick. Its 681 existing
files were backed up and hash-verified first; previous updater files were archived. The new
179,240-byte install pack and pending-job record matched after an unmount/remount, then the
CLI successfully ejected the stick. The second stick was not changed. This is the first car
test of the module/PMIC-mode diagnostic, not an overclock; no report for this job exists yet.

The CLI's automatic eject occurred before the root instruction file could be replaced. That
file still describes the earlier registry job; its car steps and November 17, 10:35 Swedish
expiry remain applicable. The updated instruction is available beside the local job package,
and this limitation was disclosed. Use the new diagnostic before that deadline, wait for
"Install successfully completed", then bring back the stick for import.

Backup recovery note: copying old Windows dump-file flags with Python `copy2` failed on the
Mac. Copying file contents and verifying SHA-256 succeeded; original timestamps/flags were
recorded in the backup manifest instead of being applied to the backup files. No code changed
or new build/CI ran for USB preparation.

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
using the expired artifact. USB preparation was outstanding at this point and is completed
above; the car run remains outstanding.

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
