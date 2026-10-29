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
| `s2am` toolkit P0: inventory job sticks, import, `status`, `diff` ([plan](docs/TOOLKIT-PLAN.md)) | Built, tested against a fake SYNC 2; **first car run is P1** |
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
python3 -m unittest discover -s tests              # 67 tests (use the ../syncextpack binaries)
python3 tools/make_pack.py <APIM_SERIAL> --dry-run # stage and patch only
python3 tools/make_pack.py <APIM_SERIAL>           # full build (Docker Desktop must be running)
```

The build writes `build/out/SyncExtPack_<serial>_AutoKit_Explorer_Reboot_audiofix.zip` plus a
manifest with SHA-256 of every USB file and the "install before" date. **The pack key changes
every 30 days, so install it within that window.** Install it following SyncExtPack's
[installation guide](https://github.com/chr0m1ng/syncextpack/blob/main/SYNCEXTPACK_INSTALLATION.md).

## s2am: check and change SYNC 2 from the Mac

Once SyncExtPack is installed, its `UpdateService` runs any `\SyncExtPack\install.bin` on a USB
stick. `s2am` uses that as a job channel. Each job is a MortScript that does its work and
writes a report back onto the stick, so the Mac can tell what is on the car.

```sh
python3 -m s2am window                                   # is it safe to build a pack today?
python3 -m s2am job inventory --serial <APIM_SERIAL>     # build an inventory job
python3 -m s2am stick prepare /Volumes/<STICK> --job build/jobs/<id>
#   car: insert the stick, wait for "Install successfully completed", pull it
python3 -m s2am stick import /Volumes/<STICK>            # read the report back
python3 -m s2am status --serial <APIM_SERIAL>            # apps, plugins, menu, free space
python3 -m s2am diff --serial <APIM_SERIAL>              # what changed since the last report
```

State lives in `~/.s2am/<serial>/` (override with `S2AM_HOME`). Preparing a stick moves earlier
UpdateService files aside so a job cannot replay, and each job also leaves a done marker on the
car. Jobs never touch firmware, boot files or UpdateService. Install, remove and menu jobs come
in P2 and P3.

**Rollback in the car** (Total Commander): the AutoKit folder keeps each original module as
`*.orig`. Rename those back to restore stock AutoKit. If the screen stops reacting, hold
Power + Seek-Up for about 10 s for a soft reset. The last resort is reflashing 3.10 or 3.08
([firmware guide](https://github.com/chr0m1ng/syncextpack/blob/main/FIRMWARE_INSTALLATION.md)).
