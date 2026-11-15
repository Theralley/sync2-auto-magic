# SYNC 2 clock investigation
The November 15 registry capture does not establish that custom kernel code is the only clock-control route.

## Evidence

- The completed capture contains 116 active-device entries: 106 named and 10 unnamed.
- The registry exporter withheld every active device's `Key` reference as a potential credential.
- No explicit DVFC driver or CPU frequency selector was found in the captured text.
- Six of 21 requested files copied. Missing files have no recorded copy errors or attributes, so ROM restrictions remain an inference.
- The CPU was measured at 600 MHz; active core voltage and the memory clock source remain unknown.

## Implementation and verification

Local commit `6d9e3dc` on `fix/clock-evidence` retains bounded, validated driver references while preserving credential filtering and corrects `docs/PERFORMANCE.md`. Nine focused registry tests pass, including malformed input and credential cases. Independent security, performance and tests reviews found no blocking issues. Windows CE compilation and a car run are outstanding; no clock-change implementation or new USB job was produced. Full CI was not run for this experimental development change.

## Next evidence

Build and validate the updated registry reader before another capture. Record per-file attributes and copy errors before attributing missing files to ROM. Check actual Ford driver interfaces against the Freescale reference BSP; a documented reference interface does not prove that Ford ships it.

Reference: [Freescale i.MX51 CE 6.0 BSP manual, chapters 7 and 9](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/9897/1/481-WCE600_MX51_ER_1104_ReferenceManual.pdf).

This documentation branch contains only the investigation record. The implementation remains local.
