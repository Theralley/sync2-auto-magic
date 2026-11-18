# Live timer and clock-output qualification succeeded
The one-shot qualifier returned a stable baseline, informative PLL1-independent timer observations, coherent counters and successful cleanup; no clock was changed.

The returned package/job/predecessor bindings and all eight preserved file hashes match.
Child exit is zero. Baseline journal is 1,697 bytes/CRC32 1012515983; qualification is
677 bytes/CRC32 642098802. Eight full-width QPC brackets agree with 614,273 elapsed EPIT
ticks; their common offset interval is [7377121952,7377121987]. Maximum bracket is 46 ticks.
QPF reports 8 MHz. This is unit-tick coherence, not external oscillator calibration.

EPIT CR is `0x023c0005`; CCGR2 is `0x3c000377` (IPG gate 1/highfreq gate 3). The captured
COSC→LP_APM→PERCLK/3 timer route does not consume PLL1. CCOSR `0x01330001` selects PLL1 for
disabled CKO1, while enabled CKO2 selects SSI2→SSI_APM→CKIH1/CAMP1. No enabled clock output
consumes PLL1 in this capture. Later policy activity and suspend remain outside this proof.

Three independent return/firmware/test reviewers pass; five new byte-exact actual-return
regressions pass. Data captures remain separate from retry permission and clock-write
authority, both false. No new car package was prepared and no identical timer trip is needed.

Next work: actual-data-bound transition/restoration specification, policy serialization and
suspend handling, fitted-part/loaded-rail/thermal evidence, and demonstrated CPU-independent
recovery. MFN 1→2 is a +4% arithmetic candidate, not a qualified operating point.

[Actual return and remaining prerequisites](../docs/CLOCK-QUALIFICATION-2026-11-18.md).
Related: [[clock-qualification-2026-11-18]], [[clock-baseline-2026-11-18]], [[sync2-auto-magic]].
