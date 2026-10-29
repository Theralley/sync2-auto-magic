# sync2-auto-magic

CarPlay (and later Android Auto) on a 2016 Ford Mondeo Mk5 with the SYNC 2 (MyFord Touch) screen.
It uses one Carlinkit USB dongle (CPC200-CCPM wired or CPC200-CCPA wireless) and Carlinkit's AutoKit app, sideloaded through
[SyncExtPack](https://github.com/chr0m1ng/syncextpack). This repo holds the software fixes that
make it usable. The upstream clones next to it (`../syncextpack` and others) are never modified.

See [docs/PLAN.md](docs/PLAN.md) for the research, the decision and the roadmap.

## Status

| Piece | State |
|---|---|
| Sound: route AutoKit's audio through SYNC 2 (`tools/patch_waveout.py`) | Built, 28 tests pass, checked with `pefile` and `llvm-objdump`, reviewed by Codex. **Not yet tried in the car.** |
| Pack builder (`tools/make_pack.py`): patched AutoKit, fails if any step fails, runs in a container | Built; needs the car's APIM serial |
| Auto-launch on plug-in and clean exit back to SYNC 2 | Planned (needs a WinCE toolchain) |
| Android Auto with the same dongle | After CarPlay works |

## Why AutoKit is silent on SYNC 2, and the fix

SYNC 2 plays an app's sound only after the app asks Ford's audio router (`RAC.dll`) for a route.
The community's VideoPlayer and Navitel do that through `WaveOutHooks.dll`. Their modules were
patched (with IIDKing) to import it, and the ARM import thunk for `waveOutOpen`/`waveOutClose`
was pointed at `waveOutOpenCustom`/`waveOutCloseCustom`. AutoKit calls COREDLL's `waveOutOpen`
directly, so it gets no route and no sound. `patch_waveout.py` applies the same patch to
`AutoKit.exe`, `libgstwaveoutsink.dll` and `libgstwaveform.dll`.

## Usage

The tools read SyncExtPack's files from a clone next to this repo. Clone it first, then run
the commands below:

```sh
git clone https://github.com/chr0m1ng/syncextpack ../syncextpack   # tested at 1a1eda0
```

```sh
python3 -m unittest discover -s tests              # tests (use the ../syncextpack binaries)
python3 tools/make_pack.py <APIM_SERIAL> --dry-run # stage and patch only
python3 tools/make_pack.py <APIM_SERIAL>           # full build (Docker Desktop must be running)
```

The build writes `build/out/SyncExtPack_<serial>_AutoKit_Explorer_Reboot_audiofix.zip` plus a
manifest with SHA-256 of every USB file and the "install before" date. **The pack key changes
every 30 days, so install it within that window.** Install it following SyncExtPack's
[installation guide](https://github.com/chr0m1ng/syncextpack/blob/main/SYNCEXTPACK_INSTALLATION.md).

**Rollback in the car** (Total Commander): the AutoKit folder keeps each original module as
`*.orig`. Rename those back to restore stock AutoKit. If the screen stops reacting, hold
Power + Seek-Up for about 10 s for a soft reset. The last resort is reflashing 3.10 or 3.08
([firmware guide](https://github.com/chr0m1ng/syncextpack/blob/main/FIRMWARE_INSTALLATION.md)).
