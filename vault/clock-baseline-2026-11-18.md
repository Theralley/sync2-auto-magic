# Verified live clock baseline
The identity-bound recovery and fixed read-only clock driver completed in the car with 64 stable readings, clean child exit and successful cleanup API returns.

The returned pack, job identity, seven source hashes and four binary hashes match the
prepared artifacts. Seven original return files were hash-preserved before import.
The controller journal is 1,665 bytes, CRC32 2548719369. Full recovery stages, activation/stream
identity, snapshot validation, close, deactivation and new-key deletion succeeded. Original
claim and latch remain by design. No clock or voltage write occurred.

Live ARM source is PLL1 with divider 1. Normal PLL bank OP/MFD/MFN are `0x60/3/1`;
CTL is `0x1223`. These imply 600 MHz **if the oscillator reference is 24 MHz**, not an
independently measured frequency. CSR at offset `0x08` is `0x3c`; actual CCSR at `0x0c` is
zero. Keep those labels separate. DDR's immediate route is AXI_A; absolute DDR/bus MHz and
full policy/consumer ownership are not established.

Two independent return/firmware reviewers confirm the result. Five new actual-return
regression tests pass, including correctly re-CRC'd corruptions and timeout refusal.
Original ASCII reports contain no car serial or host paths and are preserved byte-for-byte
as fixtures. The next step is live graph/timebase and hardware/recovery qualification;
624 MHz remains an arithmetic candidate only. No new car package or writer was prepared.

[Detailed baseline and limits](../docs/CLOCK-BASELINE-2026-11-18.md).
Related: [[clock-recovery-2026-11-18]], [[sync2-auto-magic]].
