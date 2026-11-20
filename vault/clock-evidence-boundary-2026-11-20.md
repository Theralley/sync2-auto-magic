# CPU evidence boundary — November 20, 2026
Both manual USB captures returned; actual CPU frequency, fitted grade and independent recovery remain unqualified.

## Evidence reconciled

- V1 and RAM-buffered V2 each contain 32 windows. Their SHA-256 identities are
  `8685fdb15fbc90ce4d5d2b16181fe5807bdf0adfd1844abdbb8e1271e4be538a` and
  `ddeb8ea99f79ae01f5d07c4631359dc5a19cd47b62d0a8d7e0188bf0656316d6` respectively.
  V2 is archived in local evidence commit `7de809b46078f537bb8452b2167a1e7e61791d53`;
  that commit is not part of this documentation branch. The V2-pending text in this
  branch's older evidence manifest is superseded by this returned status.
- These are historical throughput observations, not measured physical MHz. V2 has
  two negative block contrasts and three windows longer than 40 ms. Repeating the
  same benchmark cannot resolve the missing independent clock evidence.
- A separate November 18 register observation gives configured ARM/reference = 25
  and PERCLK/reference = 1/3. ARM = 600 MHz follows only if reference = 24 MHz.
  That observation was not simultaneous with V2 and is not oscillator calibration.
- Reported module identifiers are HardwarePN `ES7T-14F130-BA` and AssemblyPN
  `ES7T-14D212-FA`. Neither is the fitted processor's ordering code.

## Bounded primary-source review

Reviewed November 20; negative searches do not establish that an OEM interface does not exist.

1. [Microsoft PROCESSOR_INFO](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447018(v=msdn.10))
   defines `dwClockSpeed` as maximum CPU clock speed. It does not promise current
   frequency. `szCatalogNumber` is optional; its existence is not fitted-part evidence.
2. [NXP IMX51AEC Rev. 6](https://www.nxp.com/docs/en/data-sheet/IMX51AEC.pdf), table 1,
   printed page 2, lists `MCIMX514AJM6C` and `MCIMX516AJM6C` with mask M77X.
   Table 13, printed page 18, specifies the automotive ARM range through 600 MHz.
   A mask shared by those parts does not establish which ordering code is fitted.
3. [IHS's original teardown](https://electronics360.globalspec.com/article/3192/ford-sync-2nd-generation-teardown)
   identifies `MCIMX516AJM6C` in its examined Gen 2 unit. Published September 27,
   2013, it explicitly dates the analysis to September 2010 and early MY2011
   hardware. It does not bind either ES7T identifier above to that processor.
   This is a useful lead, not identification of the fitted unit or an 800 MHz rating.
4. [Ford PTS Toolbox overview](https://www.fordtechservice.dealerconnection.com/vdirs/toolbox/ActiveX_learn_more_ENG.pdf)
   describes vehicle-session-dependent tools and module-information collection.
   It supplies neither a live CPU-frequency PID nor a complete PID inventory.
   General IDS availability therefore does not establish a supported CPU-rate channel.

No supported live ARM-frequency parameter or traceable exact-revision BOM linkage
was found in this bounded public review. No manufacturer or service contact was made.

## Evidence needed before reconsidering the next step

| Gate | Qualifying evidence | Insufficient substitute |
|---|---|---|
| Current CPU rate | Ford-supported read-only PID/API with exact hardware/firmware applicability, unit, source, update/caching semantics and measurement independence | Boot maximum, loop throughput, archived timestamps or unsynchronised register arithmetic |
| Fitted limits | Traceable build record or equivalent identification linking the fitted assembly/variant to full processor ordering code and applicable limits | Generic SYNC 2 teardown, shared mask, module part number or another family member's rating |
| Independent recovery | Revision-applicable procedure initiated independently of APIM CPU execution, establishing safe stock clock state after CPU/DDR failure, with verification | Software restart, same-CPU watchdog, registry cleanup or an undo USB that needs the stalled CPU |

These are separate gates: identifying the processor or finding telemetry alone does
not authorize a clock trial. Rail/loaded-voltage, thermal, clock-policy and suspend
requirements also remain unresolved.

## Next allowed work

Obtain documentary evidence against those gates. A Swedish service question is
prepared privately but has not been sent; request documentation only, not programming
or reset. A response must be checked for exact revision and semantics before use.

Do not start a clock writer, repeat the consumed `cpuavail` edge, prepare another
clock/throughput car test or connect timing CSVs to clock control. The separately
owner-authorized ordinary-API load observer is not such a test; its current build and
USB status are recorded in [[load-observer-implementation-2026-11-20]]. No clock/voltage
change, USB mutation, installation, merge, deployment or release occurred in this
documentary review itself. The overclock objective remains unachieved.
