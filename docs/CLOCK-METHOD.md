# SYNC 2 clock method and the next measurement
The clock investigation has a working diagnostic implementation, but no verified 700 MHz operating point yet.

## What an application could control

| Route | What it can establish | What is still missing |
|---|---|---|
| Existing DVFC driver | Selects operating points compiled into that driver; the reference BSP exposes CPU and peripheral domains separately | A matching Ford driver, its API contract and its actual operating-point table |
| Existing `PMI1:` driver | Reads MC13892 registers through the documented register-read request | Compatibility of Ford's implementation with the reference ABI; this is not a CPU clock selector |
| `cspddk.dll` clock services | The reference BSP has clock-query and configuration services | Ford's exports, callable context and implementation; a function name does not prove arbitrary CPU-frequency support |
| New board-specific platform support | Would be needed if the deployed software has no suitable operating point/interface | Actual CPU grade, clock tree, DDR/AXI dependencies, rail control, synchronization and suspend/resume behavior |

Source: Freescale's [i.MX51 CE 6.0 BSP manual](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/9897/1/481-WCE600_MX51_ER_1104_ReferenceManual.pdf), chapters 7, 9 and 19.

Finding an existing DVFC driver would not by itself make 700 MHz available. Its compiled table
must contain a suitable point, or its platform implementation must change. The captured Ford
registry has no explicit DVFC entry; the corrected reader will recover previously hidden driver
references. An absence in that capture is not a complete inventory of OEM interfaces.

The measured CPU clock is 600 MHz. The [automotive i.MX51A datasheet](https://www.nxp.com/docs/en/data-sheet/IMX51AEC.pdf)
rates that variant at up to 600 MHz; the fitted order code has not been established. A different
family member's 800 MHz specification is not a voltage/frequency specification for this board.

## Implemented now: `s2am job pmic`

This ordinary Windows CE application opens the existing `PMI1:` device and sends one fixed
register-read request. It reads identification first, checks the MC13892 identity, then reads
SW1's configuration. There is no SDK DLL load, new driver, physical-memory mapping, register
write, power-state request, or ADC/interrupt access. No clock-change command is implemented.

The report contains **normal, DVS and standby presets**, not a measurement of active core
voltage. The active selection and board rail mapping still need evidence. Temperature remains
unmeasured; the PMIC die and processor die are different thermal points.

Reference ABI provenance, inspected at commit `3b70b2690782acfcba7f4b0e43e05b5b070ed0da`:

- [Freescale PMIC IOCTL definitions](https://github.com/KunYi/em-works/blob/3b70b2690782acfcba7f4b0e43e05b5b070ed0da/WINCE600/PLATFORM/COMMON/SRC/SOC/COMMON_FSL_V2_PDK1_9/PMIC/MC13892/INC/pmic_ioctl.h): fixed read request, `0x00224000`.
- [Freescale SDK adapter](https://github.com/KunYi/em-works/blob/3b70b2690782acfcba7f4b0e43e05b5b070ed0da/WINCE600/PLATFORM/COMMON/SRC/SOC/COMMON_FSL_V2_PDK1_9/PMIC/MC13892/SDK/pmic_lla.cpp): DWORD input/output. The driver does not fill bytes-returned; the SDK passes NULL.
- [Reference driver](https://github.com/KunYi/em-works/blob/3b70b2690782acfcba7f4b0e43e05b5b070ed0da/WINCE600/PLATFORM/COMMON/SRC/SOC/COMMON_FSL_V2_PDK1_9/PMIC/MC13892/PDK/pmicpdk.cpp): register-read dispatch and identity check.
- [MC13892 datasheet](https://www.nxp.com/docs/en/data-sheet/MC13892.pdf): identification register 7 and SW1 register 24. Each SW1 preset is 600 mV plus 25 mV per code, with fields at bits 0–4, 5–9 and 10–14.

This source is a reference BSP mirror, not Ford's source. Matching the device/DLL names is
evidence for a testable interface hypothesis, not proof of binary compatibility. A nonzero
24-bit response and matching identity are required before the second read; failed, mismatched,
unwritten or malformed results do not become a voltage result.

```sh
python3 -m s2am job clock --serial YOURSERIAL  # both captures in one install
python3 -m s2am job pmic --serial YOURSERIAL
python3 -m s2am job registry --root 'HKLM\Drivers' --root 'HKLM\Services' --serial YOURSERIAL
```

The combined `clock` job runs the same PMIC helper and corrected registry reader, with one
report folder and no reboot. It captures `HKLM\Drivers`, `Services`, `System`, `Init` and
`Platform` to depth 8. Import checks both capture outcomes separately; a successful install
does not prove that either diagnostic succeeded. The 15-second PMIC and 90-second registry
script waits are separate; neither cancels a blocked native call. Leave the stick inserted
until **Install successfully completed**, including while the screen stays at 100%.

These captures expose the available registry and PMIC presets. They cannot guarantee recovery
of compiled operating-point tables from ROM modules or establish a usable frequency-control ABI.

Use the usual job/stick workflow. `--no-pack` stages files without building an install pack.
The normal pack-window check still applies. A PMIC job needs no settings undo because it
changes no settings; the job runner still stages its executable and writes its normal records.
The standalone jobs remain available; the combined job also has not run in the car.

After importing, the PMIC job prints presets only when its completion marker and full report
agree. `pmic.txt` retains raw decimal values and failure details. Stage 1 = identification read
failed; 2 = identity mismatch/invalid data; 3 = SW1 read failed; 4 = invalid SW1 data; 5 = device
open failed; 6 = report output failed before sampling. System error 0 can accompany a validation
failure; it does not mean the read was verified.

The script waits up to 15 seconds for the helper before continuing with its normal inventory.
That bounds the script's wait, **not** a blocked driver/filesystem call. A blocked helper could
remain running. A completed snapshot is preserved if the overall job was interrupted later.

## What 700 MHz could buy

For a fixed workload whose execution scales perfectly with CPU frequency:

| Clock | Capacity relative to 600 MHz | Time for the same CPU work |
|---|---:|---:|
| 630 MHz | +5.0% | −4.8% |
| 650 MHz | +8.3% | −7.7% |
| 700 MHz | +16.7% | −14.3% |

These are arithmetic limits under that model, not measured gains or recommended operating points.
Memory stalls, unscaled buses and changing workload can reduce the benefit.

AutoKit's observed 58% CPU share under saturation is delivered service, not its unconstrained
demand. It cannot tell us how much extra capacity clears the backlog. Illustratively, if the
other work keeps needing 42% of the original CPU, an ideal 700 MHz CPU leaves 448 rather than
348 MHz-equivalent for AutoKit: 28.7% more residual service. That is not a predicted frame-rate
gain and does not isolate decoder work from the rest of AutoKit.

A genuine 20% reduction in decoder cycles would allow 25% more decoder work in the same budget.
Under that same simplified 42%/58% model its saturation threshold is close to the 700 MHz case.
The emulator has shown fewer instructions, not a measured reduction in Cortex-A8 cycles.
Compare per-frame time, frame backlog/drop rate, UI latency and CPU load in the car before
deciding whether the clock change is necessary. The current evidence makes it a plausible lever,
not an established requirement.

## Verification and next decision

The PMIC and corrected registry helpers compile with CeGCC `-Wall -Wextra -Werror` on
`ant-srv-001`; their PE headers/imports validate as Windows CE ARM, COREDLL only. Focused host
tests execute the actual PMIC C application against an API shim and cover successful readings,
wrong identity, no-op success, read errors, partial writes and report validation. This verifies
application logic and buildability, not the Ford driver ABI or a real voltage reading.

Next decision requires the returned PMIC and corrected driver captures. Then identify the actual
CPU-domain interface and operating-point table. If none provides the target, the remaining work
is board-specific platform support; the present tools do not establish or apply an overclock.
