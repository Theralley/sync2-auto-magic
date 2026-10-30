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

### Same day, second visit: the freeze, twice

| Step | Result |
|---|---|
| Logger job (MortScript loop, 300 s), then AutoKit, Exit | The loop wrote its first line and nothing more, so it recorded nothing. Exit froze the screen again. **The soft reset did not work this time**; the car had to be switched off and the driver's door opened and closed |
| Runner guard job (`runner-guard`) | Applied: self-test passed on the car (`toolhelp 1`, `desktop 1`), Ford's runner kept as `SyncAppsRunner.orig.exe` (11776 B), guard installed (12800 B). AutoKit still opens through it |
| AutoKit, Exit, with the guard | **Still frozen**; same recovery (car off, door open and closed) |

The guard's own log stays on the car (`\SyncExtendedPack\_s2am\guard.log`) and was not on
either stick, because both reports were written before the test. So it is not yet known
whether the guard acted.

**Next:** the MortScript loop is replaced by a compiled watcher, `s2amwatch.exe`, which
records processes, windows in Z order, whether SYNC's DESKTOP is shown, and whether AutoKit
still answers messages, twice a second. It copies the guard's log and AutoKit's own
`hwlog.log` to the stick whenever they change. Every inventory now also copies `hwlog.log`.

### Same day, third visit: the watcher finds the cause

| Step | Result |
|---|---|
| Logger job with the compiled watcher (600 s), AutoKit, Exit at 11:20:54 | Recorded everything (see below). Frozen until the car was switched off |
| Logger job after the restart (60 s) | SYNC normal; collected the guard's log once more |

What the watch log showed:
- AutoKit started at 11:19:23 and showed its window 4 s later; SYNC's `DESKTOP` was hidden.
- At Exit, AutoKit's window was hidden (`hwlog.log`: `SW_HIDE`), its process kept running
  and kept answering messages. Only `mishell.exe`'s `DesktopExplorerWindow` stayed visible.
- Nothing changed on the screen for six minutes. At 11:26:43, when SYNC woke after the car was
  switched off, AutoKit's process ended and `DESKTOP` was shown in the same second.
- The guard logged `app 0` throughout: it never recognised AutoKit (forward slashes in the
  path), and the shell background counted as "another program in front". Both are fixed in
  the second guard.
- The first logger's MortScript process from the morning was still running: it had hung.
- Switching the car off does not reboot SYNC; it sleeps and wakes.

### Same day, fourth visit: the second guard works (G5)

| Step | Result |
|---|---|
| Runner guard upgrade job (second guard) | Applied: self-test passed (`toolhelp 1`, `desktop 1`, `background 1`); Ford's runner stays `SyncAppsRunner.orig.exe` |
| Logger job with the watcher (600 s), then AutoKit opened five times | Recorded until the stick was pulled at 494 s |
| AutoKit, Exit, four times | **Works**: SYNC's screen was back each time, about 3 s after Exit |
| Reverse camera while AutoKit is open | **No camera picture**. Not caused by the guard (see below); open |

What the watch log showed, the same at every Exit:
- AutoKit hid its window (`SW_HIDE`), leaving only the shell background visible.
- About 2 s later the guard logged `stuck|nothing usable on the screen` and sent AutoKit
  `WM_CLOSE`. AutoKit ended within 0.1–0.3 s, so the guard never had to force it.
- Ford's launcher then ended and showed `DESKTOP` in the same second, as it does after any
  app. The guard's own fallback was never needed.
- The guard now recognises AutoKit (`app 1`) and counts the shell background as nothing
  (`other_windows 0` while AutoKit is hidden).

The reverse camera: during the third opening (13:49–13:50) AutoKit's own log grew from a few
hundred bytes to 258 KB, and AutoKit was briefly slow to answer (1.5–2.3 s, seven times). No
window appeared or disappeared in that time: AutoKit stayed on top and visible, so the guard
did nothing. The camera picture is drawn without a window of its own, and AutoKit's full-screen
window seems to cover it. The 258 KB log was overwritten by the next opening's copy, so what
AutoKit logged is not known yet.

**Open:** CarPlay (T1–T7) and the sound fix wait for the adapter. The reverse camera while
AutoKit is open needs its own investigation.

