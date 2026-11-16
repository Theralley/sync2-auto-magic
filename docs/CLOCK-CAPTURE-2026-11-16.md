# Clock capture from the car, November 16, 2026
Both diagnostics completed; the existing PMIC read route works for the two tested registers, but no CPU-frequency selector was discovered.

Job: `20261115-214729-clock-9792`. The car-reported completion time is `2026-11-16 08:01:47`.
Original USB evidence was backed up before import. Raw reports remain in the private car store;
this note contains the relevant technical findings only.

## Integrity and completion

- Returned `installed.bin` matches the prepared 180,968-byte pack:
  `281045d262e5f86691e40bccff0181252223f6380b551ac1a2d905f2b9f7ffc2`.
- Pending metadata matches the planned job. The five staged payload hashes validate.
- All 15 backup-manifest entries validate. All 12 report files and the separately imported
  installer log match their original USB copies.
- Both diagnostic completion markers agree with their report endings. The overall job is
  `applied`; neither conclusion relies solely on the installer success message.

## PMIC result

| Read or decoded field | Result |
|---|---:|
| Identification, register 7 | 17876 (`0x45d4`) |
| SW1 configuration, register 24 | 4526674 (`0x451252`) |
| Normal preset | 1050 mV |
| DVS preset | 1050 mV |
| Standby preset | 700 mV |

The SW1 field codes are 18, 18 and 4. The conversion is 600 mV + 25 mV per code.
The identity passes the MC13892 checks. The field layout and preset behavior are described in
the [NXP MC13892 datasheet](https://www.nxp.com/docs/pcn_attachments/14928A_MC13892.pdf), register 24.

This is actual-car evidence for the fixed identification/SW1 read contract through `PMI1:`.
It does not validate other driver requests or a clock-change interface. Equal normal/DVS
presets do not establish which mode is active, the board's SW1-to-CPU rail connection, actual
rail voltage, temperature, or frequency headroom. There is no fresh CPU-frequency measurement.

`pmic.txt` SHA-256: `15a13266b914a9c8e1be7bdee8b32ee06476cc3a1ddb9a22b1355df537442a83`.

## Registry coverage and remaining gaps

The matching terminal summaries report **950 keys, 3,792 values, 49 withheld**.

| Requested root | Captured keys |
|---|---:|
| Drivers | 772 |
| Services | 57 |
| System | 118 |
| Init | 2 |
| Platform | 1 |

There are no recorded `E|` lines, output-limit markers or oversized-value messages. The Drivers
traversal reaches the configured depth 8 in USB-modem Unimodem Settings/Init branches. This is
still a bounded traversal; completion cannot exclude unreported enumeration errors or deeper
descendants. It is not a complete inventory of every OEM interface.

There are **116 active entries: 106 named and 10 unnamed**. The corrected exporter recovers
104 `Key` references, and all 104 resolve to captured configurations. Twelve remain withheld:
entries 188, 109, 86, 85, 82, 61, 59, 58, 57, 56, 52 and 15. Three of these (86, 85, 82) are
unnamed. Entry 82's `BusName=services` corroborates the services enumerator, but its `Key` was
not recovered. Do not call these 12 direct mappings resolved by inference.

Seven unnamed entries now resolve directly: PPP, AFD, TAPI, ErrorReporting/DwXfer, two BuiltIn
bus-enumerator entries, and CSPDDK. In particular, the active entry now directly corroborates
the earlier CSPDDK boot configuration.

`registry.txt` SHA-256: `feeb18e5719e4eda2b6f256e3e597eea1bf604ea231b76796d9081ef20062c38`.

## Frequency-control findings

No explicit DVFC/DVFS interface, CPU-frequency selector or operating-point table appears in
this capture. It does not establish a complete table capped at 600 MHz, either.

| Observed mapping or value | Interpretation and next use |
|---|---|
| `PMI1:` → `BuiltIn\PMI` → `pmicpdk_mc13892.dll` | The tested two-register read works. This is not a discovered CPU selector. |
| Active entry 02 → `BuiltIn\CSPDDK` → `cspddk.dll` | Confirmed loaded library; obtain the exact module/interface implementation next. |
| `APD0:` → `BuiltIn\AutoPM` → `autopmdrv.dll` | An OEM power-management inspection lead. No CPU-frequency contract is present in the registry. |
| `CPM0:` → `CriticalProcessMonitor` → `CritProcMonDrv.dll` | Process-monitor identity, not evidence of a clock manager. |
| `MCM1:` → `mcm.dll` | Earlier factory configuration associates its load order with USB power in VHM; its name does not demonstrate CPU clock control. |
| `OPP1:` → `Services\OPPSvc` → `oppservice.dll` | Earlier OBEX/OPP-inbox configuration supports object-push functionality; do not mistake the acronym for CPU operating points. |
| `Services\SyncClockSvc` → `SyncClockSvc.dll` | Service-name hint only; its implementation and purpose are not established here. |
| `ESDHC2\MaximumClockFrequency=52000000` | Storage-controller clock setting, not a CPU clock. |

The system power-state tree contains Suspend, WaitSuspend, VHM and Infotainment settings.
Its fail-safe timeouts and SysHealth reboot/logging settings do not demonstrate recovery from
an unstable CPU or DDR configuration. No temperature channel is established by this report.

## Decision and next work

This supports **route C: no CPU-frequency selector discovered within the capture**, while
tracking incomplete identification. Neither route A (verified higher operating point) nor B
(verified 600 MHz table maximum) has been established.

Resolve the remaining structural identities, especially unnamed 85/86, without exporting
credentials. Obtain the exact deployed clock/power module identities and implementations,
starting with CSPDDK and AutoPM. Record file attributes and copy errors before choosing a ROM
retrieval method. This job requested no module files, so it cannot supply those binaries or
their compiled tables. A further identical full registry dump would not provide the missing
module implementation.

Keep active rail mapping, thermal observation and recovery behavior as separate evidence
requirements in [CLOCK-OUTCOMES.md](CLOCK-OUTCOMES.md). The successful PMIC reads do not qualify
667/700 MHz or authorize a clock/voltage write. No overclock was applied.
