# AutoKit's video decoder, rebuilt

AutoKit (the CarPlay / Android Auto app) decodes H.264 in software with three FFmpeg 2.6 DLLs:
`avcodec-56.dll`, `avutil-54.dll`, `avformat-56.dll`. This folder holds the recipe that rebuilds
them for the SYNC 2 processor (i.MX51, Cortex-A8, Windows CE 6) from FFmpeg 2.6.9, and the tests.
No binaries are kept here.

`tools/reproduce.sh` does everything: source, patch, build in a pinned CeGCC container, static
checks, and decode tests in an ARM emulator. It needs Docker, and `STOCK` set to a folder with the
original three DLLs for comparison.

## Variants

| Variant | What it is |
|---|---|
| `default` | ARMv6T2 assembly, no NEON |
| `small` | the switches the original DLLs were built with |
| `neon` | NEON assembly. **Ends AutoKit on the car**, see below |
| `neon-safe` | `neon`, with seven NEON routines left to C (`patches/ffmpeg-2.6.9-neon-aligned-only.patch`) |

## Why plain NEON fails on this car

Measured on the car with `s2am job neon-diagnose` (2026-11-18):

- Switching NEON on works, also in fresh threads and across thread switches.
- **Every unaligned access faults** with `EXCEPTION_DATATYPE_MISALIGNMENT`: NEON loads and stores
  of 16- or 32-bit elements at an address that is not a multiple of the element size, and a plain
  unaligned word load too. Byte-element NEON loads (`vld1.8`) are fine at any address.
- FFmpeg's H.264 NEON code moves 16/32-bit lanes to arbitrary pixel addresses in seven routines:
  the horizontal loop filters (luma, chroma), `chroma_mc4` and `chroma_mc2` (put and avg), and
  `pred8x8_plane`. The `neon` build faulted in one of them before its tenth frame.

`neon-safe` keeps every other NEON routine. In the emulator it is bit-exact on all five test
streams, and the only unaligned accesses left are `vld1.8` and `vpush`/`vpop` of d8-d15 (word
aligned), both of which run on the car.

## Speed on the car

One 640x384 High-profile sample, 89 frames, decoded the way AutoKit calls FFmpeg, nothing else
running:

| Decoder files | Time | Frames a second |
|---|---|---|
| original | 9.6 s | 9.3 |
| `default` | 7.4 s | 12.0 |
| `neon-safe` | 4.8 s | 18.6 |

All three gave the right picture. `neon-safe` has since run CarPlay on the car at 640x384 and at
800x480.

## Trying a build on a car

`s2am job neon-diagnose --decode LABEL=FOLDER --sample FILE` decodes a sample with each set on the
car and changes nothing. `s2am job decoder --from FOLDER --neon-check` installs a set and
`--restore` puts the previous files back.
