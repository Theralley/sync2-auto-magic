# s2am: a Mac toolkit that changes and checks SYNC 2

Plan, 2026-10-29. Fable researched connectivity and proposed a plan. Codex statically analysed SyncExtPack's `UpdateService.dll`, `crypto_pack` and the builder, and proposed an architecture. Claude merged the two.
Goal: from the Mac, **inspect, install, update, remove and roll back** sideloaded SYNC 2 apps, and **check versions and state** with a short loop.

## What the evidence allows

- **There is no network path into the APIM today.** Nobody has published one. WinCE runs no listener by default, and the car's internal Ethernet is not reachable from its Wi-Fi. A Wi-Fi link exists only if we sideload a listener ourselves. ([Hackaday teardown](https://hackaday.io/project/182493))
- **The USB "job stick" channel already exists.** After the first SyncExtPack install, the resident `UpdateService.dll` processes any stick that carries `\SyncExtPack\install.bin` (`UpdateService.dll` offsets in brackets):
  - it creates or overwrites files at any writable path (`CREATE_ALWAYS`, +0x2e1c), and creates directories;
  - it has **no delete primitive**, so deletion has to be done by a POST program;
  - `PRE_APP` runs before extraction and `POST_APP` after (+0x41f8/+0x42c0). It uses `CreateProcessW` with a NULL working directory, **waits indefinitely and ignores the exit code**. Only one PRE and one POST per pack;
  - it writes `\USB Disk\SyncExtPack\install_log.txt`, then tries to rename `install.bin` to `installed.bin`. That rename fails silently if `installed.bin` already exists, and **the same job then replays on the next insertion**;
  - it reads the serial from `DataManager` (`OutboundDIDs.APIMSerial`).
- **Packs are built by the upstream `crypto_pack`, used as-is** (sandboxed in the offline container). A pack is bound to the APIM serial and to a fixed 30-day window (upstream `getMagicNum`), not to 30 days from the build. The format carries no integrity check, so the toolkit hashes everything it stages and verifies the result through the car's report.
- **The menu** is `SyncApps.xml` (editing the XML is enough; the SWF does not need rebuilding). The builder has 5 slots (4 apps plus Reboot), and the SWF shows 9 entries in total. `RemoveExtPack` deletes only `\SyncExtendedPack`; it does not restore the factory state.
- **MortScript** is already in the pack. It has file operations, registry read/write/delete, process run/kill and directory iteration, so jobs can be scripted without a WinCE compiler.
- **FORScan through the Mac Docker chain** (forscan-mac) is read-only plus reset: identity, software version, maybe the serial, As-Built export, and an APIM reset as a remote reboot. **It never writes As-Built over the emulated chain.** It cannot see sideloaded apps.

## Architecture

```
Mac
├── s2am CLI (later a localhost web UI) ─ state store: one snapshot per APIM serial
│     prepare stick ─▶ USB stick ─▶ car (UpdateService runs job) ─▶ report on stick ─▶ import
├── s2am (Python, host or arm64 container): job builder, stick prep, reports, diff
├── builder container (amd64, offline): upstream crypto_pack for every pack, plus the first-time Installer.jpg (swfmill + secureSWF)
└── fsmac sidecar (optional, forscan-mac): read identity/version, APIM reset
```

**A job** is one `install.bin` that carries:
- its payload under `\SyncExtendedPack\_s2am\jobs\<id>\`;
- `POST_APP` = MortScript running `job.mscr`, which does this in order:
  1. **replay guard:** if the job's done marker exists, report "already applied" and stop;
  2. **back up** every target to `\_s2am\backup\<id>\`, including the fact that a file or registry value was absent;
  3. **apply** the change: move, delete, XML edit or registry edit;
  4. **verify** the change;
  5. **write a report** to `\USB Disk\s2am\reports\<id>\`: an inventory of files and sizes, `SyncApps.xml`, the relevant registry keys, `install_log.txt`, and `installed.json` (the toolkit's own version manifest on the car).

When the Mac prepares a stick it also deletes any old `installed.bin`, so jobs cannot replay.

**Operations:** `inventory`, `install <app>`, `update <app>`, `remove <app>`, `menu add|remove|rename`, `rollback <job>`, `reboot`, `status` and `diff` (Mac only, from the last report). Every change gets a dry-run diff first, and **a matching rollback stick is built at the same time**.

**Safety:**
- writes only to an allowlist (`\SyncExtendedPack`, our own `\windows\*Plugin.dll`, menu XML and icons); firmware, boot and `UpdateService` are never touched;
- the serial is checked, and builds near a key-window boundary are refused;
- size and free-space limits are enforced;
- jobs are idempotent, guarded by a done marker;
- the APIM clock is captured in each report.

## Phases (each ends with a check you can see)

| Phase | Build | Check |
|---|---|---|
| **P0 (no car needed): done 2026-10-29**, 67 tests, Codex-reviewed | Job builder (staging folder + META + MortScript) packed by the upstream `crypto_pack` in the container. Stick prepare/import with replay protection. Fake SYNC 2 (simulates UpdateService's copy, POST, log and rename behaviour on a staging folder) for tests: case-insensitive paths, replay, key-window boundaries. `s2am` CLI skeleton and state store. | Tests; a job pack builds in the container |
| **P1 Bootstrap + inventory** | First install (wallpaper trick): base pack plus patched AutoKit, Explorer and Reboot. Then an inventory job stick. | **In the car:** dongle, CarPlay and sound. The report appears on the stick and the Mac's `status` shows AutoKit's files and hashes |
| **P2 Reversible menu edit** | Job: rename a menu entry, reboot; rollback job. | **In the car:** the menu changes, then comes back |
| **P3 App lifecycle** | Install, update and remove a disposable test app, with backups, registry comparison and locked-file handling (reboot, then clean up). | **In the car:** the app appears, updates and disappears; the reports diff cleanly |
| **P4 FORScan sidecar (optional)** | `s2am car id` (version, part numbers, maybe the serial) and `s2am car reset`, both through fsmac. Read-only. | **In the car:** the reset reboots SYNC 2 |
| **P5 Wi-Fi gate, then agent** | Gate: sideload one ARM FTP/HTTP binary in a job; check it starts and that the laptop on the car's Gateway AP can reach it. Only if that works: an authenticated agent, off by default, with an auto-off timer, and the same job IDs and reports over Wi-Fi. | **In the car:** a loop in seconds without the stick |

## Riskiest unknowns (ranked) and the cheap test for each

1. **A file is locked or the power drops mid-job.** AutoKit DLLs are locked while it runs. Test: stage, then reboot, then clean up, and simulate it in the fake filesystem first.
2. **What MortScript actually manages on SYNC 2** (does it run, and can it export the registry and list directories). Test: the P1 inventory job. If it falls short, add a small CE helper (CeGCC).
3. **APIM clock versus the key window.** Test: the report records the APIM time; refuse builds within 2 days of a window boundary.
4. **Menu refresh and capacity.** Test: P2.
5. **Wi-Fi agent feasibility.** Test: the P5 gate (about 30 minutes) before any agent work.
