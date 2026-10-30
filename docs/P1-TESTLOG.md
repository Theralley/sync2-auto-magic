# Phase 1 test log

Fill one copy per car session. Test IDs match [P1-RUNBOOK.md](P1-RUNBOOK.md).

| Field | Value |
|---|---|
| Date / time | |
| Car | 2016 Ford Mondeo Mk5 |
| SYNC software (About SYNC) | 3.__ build _____ |
| APIM serial | ________ (keep private; do not post publicly) |
| iPhone model / iOS | |
| Adapter | CarlinKit wired, firmware: |
| Pack built (UTC) / install before | |
| sync2-auto-magic commit | |

## Session 1: install

| Step | Result (yes / no / note) |
|---|---|
| 1.2 Installer.jpg → restart | |
| 1.4 "Install successfully completed!" | |
| 1.5 Apps shows AutoKit, Total Commander, Reboot (**G1**) | |
| install_log.txt kept | |

## Session 2: CarPlay

| Test | Result | Notes |
|---|---|---|
| T1 time to AutoKit / to CarPlay (**G2**) | __ s / __ s | |
| T2 touch works, correct position | | |
| T3 music through speakers (**G3**) | | SYNC source shown: |
| T4 navigation voice / music ducks | | |
| T5 Siri hears you (**G4**) | | button used: |
| T6 call both ways | | |
| T7 map scrolling: smooth / choppy / slideshow | | |
| T8 exit AutoKit → SYNC touch OK (**G5**) | | soft reset needed? |
| T9 engine off and on → touch OK | | |

### If there was no sound

| Variant | Picture | Sound |
|---|---|---|
| Patched AutoKit, BT source selected | | |
| Stock AutoKit (`*.orig` swapped back) | | |

## Session 3: inventory

| Step | Result |
|---|---|
| Job stick → "Install successfully completed" | |
| `s2am stick import` status | |
| `s2am status` shows AutoKit and the menu (**G6**) | |

## Anything else

-

---

# 2026-10-30: first car session (developer's car)

| Field | Value |
|---|---|
| Car | 2016 Ford Mondeo Mk5, 8" SYNC 2 |
| SYNC software | CCPU 3.10.16180.EA (EU), navigation 5.67.6, map F10 |
| APIM serial | (private) |
| Sticks | SanDisk Cruzer Micro 2 GB, FAT32 / MBR |
| Adapter | not delivered yet |
| sync2-auto-magic | the commit after b4b8ca0 that adds `docs/MORTSCRIPT.md` |

**Starting point.** A previous owner had installed SyncExtPack in August 2022. The Apps menu
showed MirrorLink, Video Player, Navitel and Reboot, and none of them opened. The inventory
explained why: only Navitel's files and plugin were left (84.5 MB), and the shared launcher
`Apps\Tools\SyncAppsRunner.exe` was gone. UpdateService was still resident, so job sticks
worked without a reinstall.

| Step | Result |
|---|---|
| Inventory job, first try | Stopped with "'If' without 'EndIf'" (MortScript bug, see [MORTSCRIPT.md](MORTSCRIPT.md)); no report |
| Inventory job after the fix | Applied, report imported (**G6** for the old install) |
| Remove Video Player (`--purge`) | Applied, verified; SYNC restarted by itself |
| Remove MirrorLink + Navitel in one job (`--purge`) | Applied, verified; 125 MB freed |
| App pack via `bootstrap prepare --apps-only` (AutoKit, Total Commander, Reboot) | Installed; Apps shows AutoKit, Total Commander, Reboot (**G1**) |
| Total Commander opens | Yes |
| Reboot restarts SYNC | Yes |
| AutoKit opens | Yes: "connect the AutoPlay box" screen, in **Chinese** (stock `lang` = 0x0804) |
| `autokit-config --lang english` | Applied; AutoKit shows English |
| Final inventory | AutoKit installed, all three audio modules **patched**, language English, video defaults |
| T8 leave AutoKit with its Exit button (**G5**) | **Fails**: the screen stays frozen. Soft reset (power/volume knob + Seek-Up ⏭, about 10 s) brings SYNC back, with nothing lost |

**Open:** CarPlay (T1–T7) and the sound fix wait for the adapter. G5 needs a fix; see
[P2-AA-AUTOSTART-PLAN.md](P2-AA-AUTOSTART-PLAN.md), AS-2.
