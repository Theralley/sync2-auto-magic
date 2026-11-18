# First verified live clock-register baseline
The November 18 recovery succeeded in the car and returned a complete stable register snapshot with successful cleanup; no frequency or voltage was changed.

## Verification

The returned installed package matches the prepared SHA-256
`9a49eb0395341f052e3b86eda887d6fac76aea7cfcd0e15c1caf5d6dcbd812bb`.
All seven preserved return files were hash-verified before import. The returned job identity
and artifact/source bindings match the trusted local job and reviewed build.

The ordered recovery record confirms exact old ownership, two fresh observations, old-key
deletion, registry flush/absence readback and readiness publication. The controller passed
activation identity, stream identity and snapshot validation. It exited **0**.

Its journal is **1,665 bytes**, CRC32 **2548719369**, containing exactly **64 readings**.
All repeated PLL values and bracketed CCM values agree; the CCM handshake field is zero.
Stream close, deactivation and new owned-key deletion returned success, followed by the
completion record and clean child exit. This is more than an installer/parent “done” marker.
The original claim and recovery latch intentionally remain; success is not replay authority.

## Captured register fields

| Block/offset | Value | Interpretation scope |
|---|---:|---|
| CCM CSR `0x08` | `0x0000003c` | Status register; **not CCSR** |
| CCM CCSR `0x0c` | `0x00000000` | ARM uses PLL1 rather than step clock |
| CCM CACRR `0x10` | `0` | ARM divider 1 |
| CCM CBCDR `0x14` | `0x24239180` | Source/divider fields captured; not a DDR MHz measurement |
| CCM CBCMR `0x18` | `0x00006046` | Live value differs from candidate startup `0x2042` |
| CCM CSCMR1 `0x1c` | `0xa351f010` | Peripheral-source fields captured |
| CCM CSCMR2 `0x20` | `0x616a744f` | Peripheral-source fields captured |
| CCM CDHIPR `0x48` | `0` | No sampled divider handshake outstanding |
| CCM CDCR `0x4c` | `1` | Programmed peripheral-DVFS divider; application state not established |
| PLL1 DP_CTL `0x00` | `0x1223` | Normal bank selected; reference/output control fields captured |
| PLL1 DP_CONFIG `0x04` | `4` | Sampled LDREQ=0 and AREN=0; preserve other bits |
| PLL1 DP_OP `0x08` | `0x60` | MFI=6, PDF=0 |
| PLL1 DP_MFD `0x0c` | `3` | Fraction denominator 4 |
| PLL1 DP_MFN `0x10` | `1` | Active numerator 1 |
| PLL1 DP_HFS_OP/MFD/MFN | `0x81 / 25 / 0` | Inactive HFS bank; do not use for current rate |
| PLL1 MFN_TOGC/DESTAT | `0x20000 / 1` | Desense-disable field captured; not policy ownership |

The raw scalar report is retained as a serial-free, host-path-free regression fixture in
`tests/fixtures/clock-recovery-20261118/`. Byte-preserving attributes retain its original
line endings and CRC. Five targeted tests validate the actual return and reject a changed
register, missing cleanup or timeout even when the copy digest is recomputed correctly.

## Conditional frequency interpretation

The live PLL reference selection identifies COSC/internal oscillator, reference divider 1,
doubled output enabled and normal bank selected. Its factors imply:

`f_ARM = 4 × f_OSC × (6 + 1 / 4) = 25 × f_OSC`.

**If the reference is 24 MHz, this is 600 MHz.** That is a register-derived conditional value,
not an independent frequency measurement. No voltage, CPU temperature or silicon grade was
measured by this job. The lock flag is sticky; it is not proof of a newly completed lock or
exclusive control of clock policy.

The existing analyzer reports DDR's immediate input as AXI_A, not its complete upstream
clock chain or absolute frequency. In particular, source labels and a programmed DVFS divider
must not be substituted for a verified bus/DDR rate.

Independent source-field interpretation traces the selected DDR path through AXI_A and the
main bus to PLL2, rather than PLL1. The live CBCMR difference `0x4004` moves VPU and DEBUG_APB
to AXI_B; it does not change the oscillator/PERCLK route discussed in the recovery plan.
This is not an exhaustive independence proof: clock-output selection CCOSR is absent from
this capture, and policy ownership is not established by a static snapshot.

## What this unlocks

The activation/read-access problem is resolved for this tested lifecycle. The next useful
work is interpretation of the live consumer graph, independent-timebase confirmation and
trial/recovery qualification—not repeating the same ownership observer.

Changing the active numerator from 1 to 2 would calculate to 624 MHz under the same 24 MHz
assumption. This is still an arithmetic candidate, **not an available or qualified overclock**.
No writer was added, no CPU/voltage change was made, and no next USB package was prepared
while analyzing this return. Applicable silicon/rail/thermal limits, policy serialization,
independent measurement and demonstrated recovery remain separate prerequisites.

Sources: [NXP AN4140, equation 1](https://www.nxp.com/docs/en/application-note/AN4140.pdf),
[NXP MCIMX51 reference manual](https://www.nxp.com/docs/en/reference-manual/MCIMX51RM.pdf),
[upstream CCM register definitions](https://github.com/torvalds/linux/blob/v6.6/drivers/clk/imx/clk-imx5.c),
[PLL implementation cross-check](https://github.com/torvalds/linux/blob/v6.6/drivers/clk/imx/clk-pllv2.c).
