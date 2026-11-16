# Offline clock implementation analysis, November 16

All seven requested clock, power and kernel modules have now been recovered from a
firmware candidate with metadata matching the car. The inspected clock exports do not
provide an arbitrary CPU-frequency setting. No clock-changing car job is ready.

## Identity and integrity

The input is the unofficial EU Langpack 2 candidate described in the
[capture report](CLOCK-MODULE-CAPTURE-2026-11-16.md), core image
`EA5T-14D544-BA.sec`, SHA-256
`e7603abf483036a7836901c8f9656ab28e716bc39162e6b10542be71a2e6faff`.
It was analyzed offline; neither its installer nor its firmware code was executed.

| Module | Storage in candidate region id6 | Car-reported size |
|---|---|---:|
| cspddk.dll | XIP | 22,148 |
| nk.exe | XIP | 68,672 |
| kernel.dll | XIP | 242,168 |
| coredll.dll | XIP | 597,540 |
| autopmdrv.dll | IMGFS | 7,324 |
| pmicPdk_mc13892.dll | IMGFS | 13,116 |
| pmicSdk_mc13892.dll | IMGFS | 30,348 |

All seven match the car's attributes (`0x2047`), FILETIME and reported size. For IMGFS
modules, that size is the sum of the module-header and four section streams, not the
size of a reconstructed PE file. A separate raw id7 image contains different versions:
none of its corresponding size/time tuples match. Its binaries are not substitutes.

The catalog's mathematical RSA-2048/SHA-1 signature verifies using its embedded leaf
certificate. The first 15 complete chunks (`img000` through `img014`) also match their
catalog hashes; these contain all bytes used for this analysis. The remaining 236 chunks
were not checked. This establishes internal consistency, not independently trusted Ford
provenance: a trusted root, revocation status and historical signing validity were not
established. Metadata agreement does not prove byte identity with modules in the car.

## Extraction and verification

The [SEC container parser](https://github.com/gweslab/libCerfCore/blob/9bcb31d160f1a47c7496d8bb38945294359168d4/src/boot/sec_container.cpp)
identified the chunk wrapper. In this candidate the payload starts at `0xee54`; each
chunk has a 64-byte header and up to 8 MiB of data. The last chunk is partial. NAND
records inside id6 have 4096 data bytes followed by an 8-byte trailer.

For a main-XIP storage address `A`, use:

```text
relative = A - 0x80100000
flash = 0x1125400 + (relative // 4096) * 4104 + relative % 4096
SEC offset = 0xee54 + (flash // 0x800000) * 0x800040 + 64 + flash % 0x800000
```

Split reads at both page and chunk boundaries. All 1,302 page trailers spanning the
XIP declared extent matched their expected sequence and flags. The recovered flat image
is 5,331,044 bytes, SHA-256
`39a16cb2651fa5399f8f0faf9c00148315690d09048bc4538a0043c8edef6213`.
Its ROMHDR identifies 51 modules and five files. Module section **storage pointers**,
not their sometimes different runtime addresses, locate bytes in this image.

For IMGFS logical address `L`, first compute `X = 0x800000 + L`, then
`flash = 0x10a5000 + (X // 4096) * 4104 + X % 4096`; apply the same SEC mapping.
Only the selected module headers, index blocks and section streams were recovered.
All 18 touched IMGFS pages passed their observed trailer-number/flag checks. Exact
expanded lengths and all three independent code-stream hashes matched. Two data streams
use XPRESS compression; an independent decode with
[Fox-IT Dissect's decoder](https://github.com/fox-it/dissect.util/blob/4653ec740c4c30827fb389cd4aa103168dc0b9da/dissect/util/compression/lzxpress.py)
produced byte-identical expanded data. All code streams were stored uncompressed.

Reconstruction used [extract-wince-rom](https://github.com/gweslab/extract-wince-rom/tree/4d03004fb2c9642afac657583746d747eadd1121)
in raw mode, with no heuristic rebasing or relocation synthesis. Its LZX dependency was
pinned to `d08163aeda0dec22dbcc363dabf80606413d119c`; IMGFS XPRESS decoding uses the
extractor's own implementation at the linked commit. All four original sections of
CSPDDK, AutoPM and both PMIC modules compare byte-for-byte with their reconstructed PE
sections. NK/kernel contain split or discarded sections; their PE output is not treated
as a complete byte-preserving substitute. Kernel analysis used original mapped ROM bytes.
Firmware binaries and disassembly remain local, outside Git.

## What the actual code does

The following RVAs refer to the reconstructed CSPDDK candidate, SHA-256
`8f47eaa549982bfe81241a71ad3997701d8adfe00a9ef486d825d5ce563b310e`.

| Function | Observed implementation | Consequence |
|---|---|---|
| `DDKClockGetFreq`, `0x1a3c → 0x4bb0` | Reads a shared frequency table | A reported value is not an independent hardware-frequency measurement |
| `DDKClockSetFreq`, `0x1a4c → 0x4bd4` | Accepts signal 3 and only 216 or 297 MHz; writes the block at physical `0x83f88000` | This is PLL3, not a 620–630 MHz CPU setting |
| `DDKClockSetpointRequest`, `0x2944 → 0x51dc` | Updates a domain/setpoint reference count and signals a worker event | Success does not demonstrate a transition; the blocking path can wait indefinitely |
| `DDKClockSetpointRelease`, `0x2954 → 0x52c4` | Releases the reference and signals the worker | Requires a functioning consumer and its platform policy |
| `DDKClockGetSharedConfig`, `0x2964` | Returns the shared configuration pointer | It is not an exported table of higher CPU operating points |

There is no `DDKClockSetCpuFrequency` export. The inspected setpoint path uses shared
memory and events, with no imported `KernelIoControl` or `DeviceIoControl` call.
Freescale's [register definitions identify `0x83f88000` as PLL3](https://cos.googlesource.com/third_party/kernel/+/6dbbd92522a13bcd5003829cbed30bc38a3d0362/arch/arm/plat-mxc/include/mach/mx51.h).
The [i.MX51 CE reference manual](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/56630/1/WCE600_MX51_ER_1104_ReferenceManual.pdf)
assigns actual voltage/frequency transitions to a separate DVFC implementation. Its
evaluation-board operating points do not establish Ford's operating points.

AutoPM contains power-notification relay code using a message queue and client events/window
messages; its runtime operation is unverified. An initialization flag appears to make its
worker exit, so the presence of that code does not prove an active relay. Its imports and
traced path do not implement CPU-frequency switching or consume the CSPDDK DVFC worker event.

The PMIC Pdk imports only three GPIO services from CSPDDK, together with I2C access.
The PMIC SDK's `PmicSwitchModeRegulatorEnableSTBYDVFS` and corresponding disable function
are successful no-op stubs in this candidate. Their names are not evidence of CPU DVFC
support. Its regulator/ADC services do not establish a processor-temperature measurement.
The inspected ADC sampling routine configures registers and starts a conversion; an
ADC-named getter is not the same as the demonstrated passive PMIC register reads.

NK's startup code configures PLL1 consistently with 600 MHz under a 24 MHz oscillator
assumption, using the equation in [NXP AN4140, section 3.1](https://www.nxp.com/docs/en/application-note/AN4140.pdf).
That startup sequence is not an application-selectable operating point.
An 800 MHz constant in initialized RAM is overwritten from shared boot data during OEM
initialization; it is not evidence for an available 800 MHz setting. The processor-info
IOCTL copies the resulting value into `PROCESSOR_INFO.dwClockSpeed`. Microsoft defines
that optional field as [maximum CPU clock speed](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447018(v=msdn.10)),
not a live measurement.

The IMGFS directory chain was followed through all 43 blocks to its terminator: 500 module
names and 137 file names resolved, with none unresolved. No module name contains
DVFC/DVFS/CPUfreq/thermal/temperature/clock. `SyncClockSvc.dll` is a file entry; its name
alone does not establish CPU control. A bounded raw search finds the worker/setpoint event
names in CSPDDK copies, but compression prevents using that search to exclude every consumer.
Neither the name inventory nor the examined OAL handlers prove that no other implementation
exists anywhere in the system.

## What is still needed for an overclock trial

The earlier claim that no standalone DVFC driver means the clock can *only* be changed
by newly written kernel code was too strong. These binaries expose additional internal
clock services, but the services inspected so far do not supply the requested CPU step.

The next decision is whether a deployed worker/OEM implementation can perform a CPU-only
transition. That requires tracing the consumer and its actual policy, or establishing that
new board-specific support is necessary. Calling the discovered PLL3 setter or waiting on
an unproven DVFC consumer would not test the proposed CPU overclock.

The [600 MHz datasheet comparison](CLOCK-METHOD.md#datasheet-comparison-for-a-small-experiment)
and [trial/restoration contract](CLOCK-OUTCOMES.md) still apply. There is no demonstrated
620–630 MHz point, verified transition/undo implementation or independent live frequency
and temperature observation. No additional USB copy diagnostic is needed for these seven
modules. No USB, voltage setting, boot image or car clock was changed in this analysis.
