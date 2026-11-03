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
| Runner guard job (`runner-guard`) | Applied: self-test passed on the car (`toolhelp 1`, `desktop 1`), SyncExtPack's runner kept as `SyncAppsRunner.orig.exe` (11776 B), guard installed (12800 B). AutoKit still opens through it |
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
| Runner guard upgrade job (second guard) | Applied: self-test passed (`toolhelp 1`, `desktop 1`, `background 1`); SyncExtPack's runner stays `SyncAppsRunner.orig.exe` |
| Logger job with the watcher (600 s), then AutoKit opened five times | Recorded until the stick was pulled at 494 s |
| AutoKit, Exit, four times | **Works**: SYNC's screen was back each time, about 3 s after Exit |
| Reverse camera while AutoKit is open | **No camera picture**. Not caused by the guard (see below); open |

What the watch log showed, the same at every Exit:
- AutoKit hid its window (`SW_HIDE`), leaving only the shell background visible.
- About 2 s later the guard logged `stuck|nothing usable on the screen` and sent AutoKit
  `WM_CLOSE`. AutoKit ended within 0.1–0.3 s, so the guard never had to force it.
- SyncExtPack's launcher then ended and showed `DESKTOP` in the same second, as it does after any
  app. The guard's own fallback was never needed.
- The guard now recognises AutoKit (`app 1`) and counts the shell background as nothing
  (`other_windows 0` while AutoKit is hidden).

The reverse camera: during the third opening (13:49–13:50) AutoKit's own log grew from a few
hundred bytes to 258 KB, and AutoKit was briefly slow to answer (1.5–2.3 s, seven times). No
window appeared or disappeared in that time: AutoKit stayed on top and visible, so the guard
did nothing. The camera picture is drawn without a window of its own, and AutoKit's full-screen
window seems to cover it. The 258 KB log was overwritten by the next opening's copy, so what
AutoKit logged is not known yet. The watcher now numbers its copies
(`autokit-hwlog-live-01.log`, `-02.log`, ...): each time AutoKit starts its log over, the next
copy begins, so every run of the log is kept, and `s2am report` shows them all.

The freeze and the workaround are reported upstream as
[chr0m1ng/syncextpack#4](https://github.com/chr0m1ng/syncextpack/issues/4), since the launcher
comes with SyncExtPack's app pack.

**Open:** CarPlay (T1–T7) and the sound fix wait for the adapter. The reverse camera while
AutoKit is open needs its own investigation.

# Video Player test (reported 2026-10-31)

One stick (32 GB, FAT32) carried an install job for SyncExtPack's Video Player
(`s2am job install "Video Player"`, 11.7 MB) and six test videos from
`tools/make_test_videos.py` in `/TestVideos`. Parked.

| Step | Result |
|---|---|
| Install job (single app) | Applied; Video Player in the Apps menu and opening. Imported 2026-10-31: menu entry and files verified |
| 800x480 H.264 (files 01–03) | **Play fine** |
| 720p and 1080p (files 04, 05) | Glitch ("bugged") |
| Sound through the car's speakers | **Yes**, in every file |
| Colours | Correct |
| Beep against the white flash | Slightly out of step |

- The files themselves are in step: measured on the Mac, every beep in files 01 and 02 starts
  on the same frame as its flash (0 ms apart). So the offset comes from the player on the car.
- **What it means for AutoKit:** the Video Player sends its sound through `WaveOutHooks.dll`,
  the same route AutoKit's sound fix uses, and starts through the same launcher with the runner
  guard in front. Sound through the speakers is good evidence that this route works on this
  car; it does not prove AutoKit's patched modules work. 800x480 is also the picture size
  `autokit-config` sets, though AutoKit decodes with its own decoder.
- Not noted: left/right, the volume knob, and whether SYNC came back after the player.


# 2026-10-31: drive logger

The 2 GB stick carried `s2am job logger --drive`: the watcher plus the new `s2amdrive.exe`,
for up to four hours. Inserted at 10:12, the car driven, the stick pulled at about 10:34.

| Step | Result |
|---|---|
| Job, then both programs running | Yes; `s2amdrive.exe` started, so every COREDLL function it needs exists on the car |
| System facts | Windows CE 6.0, i.MX51, OEM "Ford Sync GenII", 483 MB memory, screen 800x480 at 16 bits |
| List of every file (`files.txt`) | 18518 entries in 31 s |
| Copy of `\8inchSkins` with SHA-256 (`skins.txt`) | 1253 files, 51 MB, 0 errors, in 11 minutes |
| Processor load every 10 s | Works per program. 95-100% busy during the copy, about 80% after it; `Desktop.exe` about 52% even with a still screen |
| Screenshots | 19 taken, but **only the coloured background shows**: the Flash screens are drawn on a layer a screen copy cannot read |

- The logger itself used about 13% of the processor after the copy, almost all for copying
  the screen once a second. A later version should do that far less often.
- What the files show is written up in
  [sync-redesign's FINDINGS.md](https://github.com/Theralley/sync-redesign/blob/main/docs/FINDINGS.md).

# 2026-10-31: first theme change, and its undo

The 32 GB stick carried `s2am job theme --preset lincoln` (Lincoln's colours on Ford's theme,
plus a read-only fetch of the Bluetooth files); the 2 GB stick its undo,
`theme --restore`. Both were rehearsed first on a simulated SYNC with the car's own files.

| Step | Result |
|---|---|
| Change stick | Applied; SYNC restarted with the new colours. Import: **verified, 5 files byte for byte** |
| How it looked | It worked, but the change is small: Lincoln's colours are muted, and the theme only colours the glow and the area buttons |
| Undo stick | Applied; Ford's colours back. Import: **verified, the original theme is back** |
| Fetched files | 2 of 28: `BTMonitorService.dll` and `AudioConfig.cfg`. The other 26 are most likely built into SYNC's read-only system image, which CE cannot copy as files |

- The first import of the change stick stopped: files fetched from the car keep CE's read-only
  and hidden attributes, which macOS shows as flags and refused to copy into the store. Fixed:
  the import now copies contents only.
- `AudioConfig.cfg` is about navigation voice prompts, not calls, so the call-sound question
  is still open.

# 2026-10-31: jobs prepared for the next car test

Built and rehearsed on a simulated SYNC that holds the car's own files (drive log) in the state
after the Apps menu test. Nothing has gone to the car. Order and checklist (Swedish):
[sync-redesign's BILTEST.md](https://github.com/Theralley/sync-redesign/blob/main/docs/BILTEST.md).

| # | Job | install.bin | Rehearsal |
|---|---|---|---|
| 1 | `theme-fd69`: the Night colours | 1,708,256 bytes | verified, 5 files byte for byte |
| 2 | `appmenu-83d5`: SyncExtPack's own Apps menu back | 183,120 bytes | verified, the original is back |
| 3 | `appmenu-1e46`: our Apps menu with Swedish tiles | 275,480 bytes | verified, 11 files byte for byte |
| 4 | `clean-0831`: s2am's old job folders | 161,536 bytes | only its own folder left; every backup kept |
| undo 3 | `appmenu-1742` | 183,120 bytes | after the cleanup: verified, the original is back |
| undo 1 | `theme-78ed` | 1,703,040 bytes | after the cleanup: verified, Ford's theme back |

- Steps 2 and 3 belong together: an Apps menu job is checked against SyncExtPack's own menu (by
  size), so the Swedish tiles go on in two steps. Run without step 2, step 3 stops itself.
- One job per stick, so each step is one visit. There is no healthy second stick for the undo
  jobs; they go on the same stick after a visit to the Mac.
- Tests: 230 pass (one skipped, as before).

## Same day, 16:00: the Apps menu test imported; sticks for step 1

- The 32 GB stick back from the Apps menu test (`appmenu-a215`): **verified, the new Apps menu
  is on the car (11 files match byte for byte)**, matching the photo of the tiles at 11:43.
- 32 GB stick: step 1, `theme-fd69` (the Night colours); `install.bin` read back identical.
- 2 GB stick, reformatted by Rasmus: the read-only check passes. It now carries the undo,
  `theme-78ed`; `install.bin` identical after writing and again after a remount.

## Same day: R3a prepared, the first of Ford's own screens

`s2am job screen` replaces one of Ford's screens from an allowlist that holds only screens SYNC
loads when they are opened. First: the call history (`Phone\PhoneHistory\PhoneHistory.swf`),
built by sync-redesign's `tools/build_phone_history.py` from the car's own copy: eight pictures
replaced by our icons, every other tag byte for byte. It answers whether SYNC accepts a changed
Ford file.

| Job | install.bin | Rehearsal |
|---|---|---|
| `screen-78f6`: our call history screen | 273,888 bytes | verified, 1 file byte for byte |
| `screen-e9a6`: undo | 271,144 bytes | verified, Ford's screen back |

The rehearsal ran after the other prepared steps, on the same simulated car. A Codex review of
the screen job found no way to write outside the screen's folder, and four things now fixed:
- the undo takes what the job really replaced (the backup its stick brought back), else any
  drive log's copy with the recorded hash, so a newer drive log no longer blocks it, and a
  different Ford version of the same size is put back as it was;
- every swap job checks the stick's copy of the backup as well as the car's before it changes
  anything (steps 1 to 4 were built before this and keep the script proven in the car);
- the new screen must be a whole Flash file (its length as its header says), not only start
  like one.

Tests: 236 pass.

R3b, the same day: the call history with big rows (76 px, three to a page, the name 26 px),
built by `build_phone_history.py --rows`: two numbers in Ford's class changed in place
(rowHeight 50 to 76, visibleRowCount 5 to 3) and the row's layout through FFDec's XML form,
nothing recompiled; every other tag byte for byte and every value read back.

| Job | install.bin | Rehearsal |
|---|---|---|
| `screen-6ffe`: big rows | 273,888 bytes | after R3a and its undo: verified, 1 file byte for byte |
| `screen-4dca`: undo | 271,144 bytes | after the cleanup: verified, Ford's screen back |

In the car: R3a, then its undo (which also proves a screen undo in the car), then R3b.

## Same day: everything in one visit (bundle)

Rasmus asked for one visit instead of one per job. `s2am job bundle` runs jobs already built in
one script, in order, each with its own report folder and done marker, so the import verifies
each as if it had run alone; the first part that stops ends the run.

| Job | Parts, in order | install.bin | Rehearsal |
|---|---|---|---|
| `bundle-1c35` | Night (`theme-fd69`), SyncExtPack's menu back (`appmenu-83d5`), our menu with Swedish tiles (`appmenu-1e46`), R3b (`screen-6ffe`), cleanup (`clean-0831`) | 1,963,648 bytes | every part verified byte for byte; 26 old job folders removed, every backup kept |
| `bundle-8737` | undo all: Ford's call history (`screen-4dca`), SyncExtPack's menu (`appmenu-1742`), Ford's theme (`theme-78ed`) | 1,838,360 bytes | after the bundle: every part verified, the car as before |

The scripts of single jobs are byte for byte as before (checked for all 31 built jobs). A Codex
review found no leaks between parts, and five things now fixed: a part may only stage files
inside its own job folder; a part built on this Mac must match what the store recorded; a
part that ran from another stick keeps its applied record; a part cut short reports
`interrupted`, not `not-run`; a bundle run again marks its parts as run before. Tests: 245 pass.

## Same day: two read-only loggers for the call sound

Rasmus: calls sound boxy, with no bass (narrowband Bluetooth calls?). See
[CALL-SOUND.md](CALL-SOUND.md).

- `tools/hfp_codec.py`: reads an iPhone's Bluetooth log (Apple's logging profile, sysdiagnose)
  and says narrowband (CVSD) or wideband (mSBC), from the car's hands-free features, the codecs
  offered and chosen, and the audio links made. Prints no addresses, numbers or names.
- `s2am job registry` (`reg-72b4` built): `s2amreg.exe`, our own read-only CE program (10 KB,
  COREDLL only), copies SYNC's settings to the stick; secrets are not copied (by name, by the
  key's path, and every binary value over 8 bytes). The job waits at most 90 s.
- A Codex review found seven things, all fixed with tests: secrets under ordinary names, a stale
  completion file after a cut-short run, the Accept command's coding field, failed links counted,
  both size caps, write failures, and a CVSD-only choice. Tests pass.

# 2026-10-31, evening: the first bundle in the car

Rasmus ran both sticks the same evening. Both imported on 2026-11-01:

| Stick | Run | Import |
|---|---|---|
| 32 GB, `bundle-1c35` | 20:55 (car clock), MortScript 4.3.0.15 | every part applied and verified: Night 5 files, SyncExtPack's menu back, our menu 11 files, R3b 1 file, all byte for byte; cleanup removed 20 old job folders and kept the bundle's own |
| 2 GB, `bundle-8737` | 23:49 | every part applied and verified: Ford's call history, SyncExtPack's menu and Ford's theme are back, all byte for byte |

What Rasmus saw:
- After the change stick: **only the Apps menu looked different** (the Swedish names). The Night
  colours are on the car but barely visible: the glow is dimmer and the area buttons a little
  stronger, nothing else (Theme.XML colours only the glow and the area buttons, as with
  Lincoln's colours).
- **The call history (R3b) looked unchanged** when Rasmus opened it. He does not remember how
  many rows it showed, or whether SYNC had restarted first, so it is open whether SYNC drew our
  screen. Theme.XML and the call history are both read only after a restart; the Apps menu is
  read when Apps opens. The next visit decides it, with a photo after the restart.
- **The changed Ford file did not break SYNC:** with R3b on the car SYNC kept running, and the
  undo stick ran normally afterwards.
- Taking the stick out and in again did not install anything. **Expected:** SyncExtPack renames a
  used `install.bin` to `installed.bin`, and every part's done marker stops a second run. A stick
  needs a new job for each visit.
- After the undo, AutoKit was slow to start once, then worked.

Second visit prepared (on Rasmus's attempt to install again), built fresh from the same files and
rehearsed on a simulated SYNC in the car's state after the undo (Ford's theme, SyncExtPack's menu,
Ford's call history, our Swedish tiles left in `Tiles`):

| Job | Parts, in order | install.bin | Rehearsal |
|---|---|---|---|
| `bundle-5dbf` | Night (`theme-ff1b`), our menu with Swedish tiles (`appmenu-fc33`), R3b (`screen-b0eb`); each plans the same change as before | 1,938,704 bytes | every part verified byte for byte |
| `bundle-9ea6` | undo all: `screen-da40`, `appmenu-93e9`, `theme-9156` | 1,838,360 bytes | after the bundle: the car as before |

Both sticks read back identical after writing and after a remount.

# 2026-11-01, morning: the second visit, with photos

Rasmus sent six photos (9:30 to 9:31 on the car's clock): the call history twice, the Apps menu,
the display settings twice. He saw "no change on call history". The photos stay private: they
show names from his phone.

**The call history on the screen is ours (R3b), not Ford's:**
- three tall rows fill the list, where Ford's screen has five rows of 50 px; measured against
  the screen's height in the photo, each row is about 75 px (ours: 76);
- the scroll buttons show thin chevrons, where Ford's show solid white triangles;
- the call marks are our thinner line icons.

So **SYNC draws a changed Ford screen**: eight pictures, two numbers in a class and one sprite's
layout changed, and it loads and runs. That answers the question R3 was there for. Rasmus did
not see a change because the change is small: the frame around the list (left menu, tabs, top
and bottom bars, the gloss on the buttons) is all Ford's.

Also seen: the Apps menu with our Swedish tiles; Settings, Display, with Ford's own day/night
mode set to Auto (that is the screen's brightness, not our Night colours, which only dim the
glow and can't be judged from a photo).

The sticks are not imported yet. The import will confirm that `bundle-5dbf` ran and that
SYNC restarted.

# 2026-11-01, afternoon: the frame, the first start-up file (built, not in the car)

Rasmus: "redesign it to modern and cool ... start building everything". Ford's look is pictures
in the frame, `AppConsole.swf`, which SYNC loads at start-up (sync-redesign R4a). s2am now allows
that one start-up screen (`STARTUP_SCREENS`); Home and the four main areas stay refused.

- A job for it needs `--startup`. The plan records it in the job, and every script writer checks
  it again (also when a bundle writes its parts' scripts). Putting the frame back never needs it.
- A new screen exactly as long as Ford's is refused: the car tells a failed copy (a locked file)
  only by its size.
- Built: `screen-8393` (the restyled frame, 1,027,498 bytes against Ford's 1,088,777) and its
  undo `screen-e9a7`. Rehearsed on a simulated SYNC with the car's own frame: on and off byte for
  byte, the call history untouched, a different frame on the car left alone.
- Codex review (gpt-6-astra, xhigh): the blocker (the flag only in the planner) and two smaller
  points are fixed. **Follow-up:** after a failed copy the script copies the backup back without
  checking that copy; for the frame, the undo stick is the remedy either way.
- `screen-1ef7` and `screen-b5bb` were built before the fix: not to be used.

## Same day, evening: the second visit imported; sticks for the third

| Stick | Import |
|---|---|
| 32 GB, `bundle-5dbf` (run 09:27) | every part applied and verified byte for byte: Night (`theme-ff1b`, 5 files), our menu with Swedish tiles (`appmenu-fc33`, 11 files), R3b (`screen-b0eb`, 1 file) |
| 2 GB, `bundle-9ea6` | not used |

Third visit, built and rehearsed on a simulated SYNC in exactly this state:

| Stick | Job | Parts, in order |
|---|---|---|
| 32 GB | `bundle-8fc9` (4,284,040 bytes) | `theme-4128` (Ford's theme back), `theme-9481` (Night with borderless buttons: System's outline colour set to the button's), `screen-8393` (the restyled frame), last, so an earlier stop leaves the frame alone |
| 2 GB | `bundle-f6bd` (2,795,240 bytes) | `screen-e9a7` (Ford's frame back), `theme-78ec` (Ford's theme back); the menu and R3b stay |

`stick prepare` ejected both sticks without reading them back. Read back by hand after
replugging and again after a remount: identical. `stick prepare` now reads every stick back
itself (after a remount) before it ejects it, and refuses to eject one that differs.

# 2026-11-01, evening: the third visit, the restyled frame in the car

`bundle-8fc9` imported: every part applied and verified byte for byte (`theme-4128` Ford's theme
back, `theme-9481` Night with borderless buttons, `screen-8393` the restyled frame). **SYNC
started with a changed start-up file**; every screen in Rasmus's eight photos works (Home,
Settings, Navigation, the call history, the Apps menu, Climate). The undo stick (`bundle-f6bd`)
was not needed and is unused.

Rasmus: "home good". Not as intended: the clock piece, the bottom tabs and the left-hand menu
buttons come out light, and on Climate a band across the bottom is bright blue (details in
sync-redesign's FINDINGS.md); being traced in Ford's frame code.

Same evening, with Codex: after a failed copy the job now checks the originals it copied back
and stops with `rollback-failed` (use the undo stick now) if they did not go back whole. And
Settings > Display (`Menu/Display/Display.swf`, not at start-up) may now be changed by a screen
job, for a lower Auto dim floor. A new screen exactly as long as Ford's is refused only for a
start-up screen: Ford's screens are stored uncompressed, so a number changed in place keeps the
length, and the import's byte-for-byte check proves the copy.

# 2026-11-02, morning: the fourth visit, the fixed frame and the lower dim floor

The third visit's cause was ours, not Ford's: `swf_bitmaps` wrote 0 into the first byte of
every pixel of a picture without alpha. The format calls that byte reserved; Ford's files hold
0xFF there and the car's player reads it as opacity, so the restyled button strips and corner
bars drew transparent. Fixed in sync-redesign (47ad11d) and the frame rebuilt.

`bundle-8d9d` ran at 07:39 and was imported the same day: every part applied and verified byte
for byte (`screen-0371` Settings > Display with the Auto dim offset from -10, `screen-c492`
Ford's frame back, `screen-f566` the fixed frame). SyncExtPack restarted SYNC after the
install, so Rasmus's eight photos from 07:42 to 07:43 show the fixed frame: buttons and bars
are solid now. The undo stick (`bundle-724f`) was not needed and is unused.

Two findings from the photos:
- **The car's screen shows dark greys far lighter than their numbers.** In the daylight photos
  black reads about 42 of 255, our bars (23,26,32) about 150 and our buttons (38,42,51) about
  210, as light as Ford's own grey frame, which is drawn from the same dark greys (Ford's clock
  piece is (36,36,36), photographed silver on 2026-10-30). Some of it is the phone camera; how
  dark it looks by eye is asked.
- The dimming floor is not tried yet: the offset stood at 0.

Rasmus: "it still feels old/like the old system BUT with some new skins". Next: a near-black
palette (`restyle_frame.py --palette deep`) and the new layouts (Home, then the frame).

## Same day, afternoon: the fifth visit's sticks

Built, rehearsed on a simulated SYNC in the car's state after `bundle-8d9d` (on and off, every
file byte for byte, the rest untouched), written, read back after a remount, labelled and ejected:
- **SYNC:** `bundle-6bce`: Ford's theme back (`theme-ab5f`), the deep theme without glow
  (`theme-bdc9`), Ford's frame back (`screen-d013`), the straight deep frame (`screen-b1e5`),
  Home as four cards (`screen-f9a4`, the second start-up screen).
- **UNTITLED 2:** `bundle-1b62`: Ford's frame (`screen-a2b5`), Ford's Home (`screen-7cee`),
  Ford's theme (`theme-d31d`). Display's dim floor, the Apps menu and R3b stay.

# 2026-11-02, afternoon: the fifth visit, Home as cards

`bundle-6bce` ran at about 16:30 and was imported on 2026-11-03: every part applied and verified
byte for byte (`theme-ab5f` Ford's theme back, `theme-bdc9` the deep theme without glow,
`screen-d013` Ford's frame back, `screen-b1e5` the straight deep frame, `screen-f9a4` Home as
four cards). The undo stick (`bundle-1b62`) was not needed and is unused.

Rasmus, with six photos from 16:35: "still very as the old. looks shit. not even align." What
the photos show is in sync-redesign's FINDINGS.md. Next: version 2, the frame and Home rebuilt
on one grid instead of repainted.
