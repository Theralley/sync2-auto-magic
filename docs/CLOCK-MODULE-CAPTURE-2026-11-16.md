# Clock module and PMIC-mode capture, November 16

The car completed `20261116-082901-clock-d9b3`. Both diagnostic reports validate, but no
program binaries were recovered and no CPU-frequency control interface was established.

Later [offline firmware analysis](CLOCK-FIRMWARE-ANALYSIS-2026-11-16.md) recovered candidate
versions of all seven modules with matching metadata. This does not change the car-capture
outcome: no binaries were copied from the car, and no clock setting was changed.

## Evidence and verification

The returned `installed.bin` is byte-identical to the prepared 179,240-byte pack, SHA-256
`abe31058f16351368c75a7af04cf8bd88d951be2fd9e21e09918b6a7c4ccad5f`.
The pending job matched the staged job, `done.txt` was present and import recorded `applied`.
Fifteen return artifacts were preserved before import. All thirteen imported files match
those originals: twelve report files and the updater log. The stick was then safely ejected.
No new job was prepared and no clock or voltage setting was changed.

## PMIC configuration

| Register | Decimal | Hex | Result |
|---|---:|---|---|
| Identification, 7 | 17876 | `0x0045d4` | MC13892 identity check passed |
| SW1 presets, 24 | 4526674 | `0x451252` | Normal/DVS/standby: 1050/1050/700 mV; SW1HI clear |
| Switcher mode, 28 | 6366281 | `0x612449` | SW1MODE = 9; SIDEN = 0; reserved-bit checks passed |

Mode code 9 configures PWM without pulse skipping in Normal mode and PWM with pulse skipping
in Standby. SID increment/decrement control is disabled in this snapshot. The normal and DVS
voltage presets are equal. These describe regulator configuration, not CPU clock selection.
Mode readback does not reveal the state selected by the standby pins. Active CPU voltage,
rail mapping and loaded-voltage behavior remain unmeasured. See NXP's
[MC13892 Rev.14, table 34 pp.69–70, tables 47/49 pp.77–81, SID p.82 and register 28 p.140](https://www.nxp.com/docs/pcn_attachments/14928A_MC13892.pdf#page=69).

This is the first car evidence for the fixed register-28 read. The report header says it was
untested because that text was compiled before this run; the complete validated report is
the subsequent evidence. This does not establish other PMIC operations or other Ford builds.

## File inspection

Every existing target returned attributes `8263` (`0x2047`): read-only, hidden, system,
INROM and ROMMODULE. The helper correctly recorded metadata without trying to open those
modules as ordinary files.

| Requested name under `\Windows` | Reported size, bytes | Outcome |
|---|---:|---|
| `cspddk.dll` | 22,148 | ROM module |
| `autopmdrv.dll` | 7,324 | ROM module |
| `pmicPdk_mc13892.dll` | 13,116 | ROM module |
| `pmicSdk_mc13892.dll` | 30,348 | ROM module |
| `dvfc_mc13892.dll` | — | Attribute query failed, error 2 |
| `nk.exe` | 68,672 | ROM module |
| `kernel.dll` | 242,168 | ROM module |
| `coredll.dll` | 597,540 | ROM module |

Error 2 means the named file was not found; it does not rule out a differently named,
statically linked or otherwise exposed DVFC implementation.
[Microsoft error-code definitions](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-).
Microsoft distinguishes executable ROM modules from ordinary INROM files in the
[Windows CE attribute documentation](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms890895(v=msdn.10)).

The result is **0/8 binaries copied, 7 ROM modules, 1 missing named file**. None was rejected
for size or a copy-time budget. A complete inspection is not a successful binary extraction.
These attributes now substantiate the ROM explanation for these seven targets; they do not
retroactively classify every file requested by older jobs.

## Next step

Obtain the matching firmware image for the recorded `3.10.16180.EA` EU build and extract its
clock/power modules offline. Match module identities using the returned names, sizes and
timestamps plus image/build provenance; sizes alone are not proof of a binary match. Inspect
CPU-domain interfaces, compiled operating points and restoration behavior before preparing a
clock change. No matching image has been verified yet.

Repeating this same file-copy diagnostic would not recover ROM binaries. This result adds
configuration and file-storage evidence, not an available 620–630 MHz setting. The
[small-experiment assessment](CLOCK-METHOD.md#datasheet-comparison-for-a-small-experiment)
remains conditional. No new car trip is requested by this analysis.
