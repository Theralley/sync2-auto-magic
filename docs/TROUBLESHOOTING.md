# Troubleshooting: symptom → cause → fix

Search this page for what you see on the screen or in the terminal. Every entry was met in a
real car or a real build, unless it says otherwise. The car results are in
[P1-TESTLOG.md](P1-TESTLOG.md).

**Soft reset (use it whenever SYNC is stuck):** with the car in Park, hold the
**power/volume knob and Seek-Up (next track, ⏭)** for about 10 seconds, until the screen goes
black. SYNC restarts and nothing is uninstalled. If that does not work (it did not, twice, after
leaving AutoKit): **switch the car off and open and close the driver's door**, then start again.
That brought SYNC back every time. Last resort: engine off, lock the car, wait 10 minutes.

---

## In the car

### Leaving AutoKit freezes the screen
- **Fixed by the runner guard** (below); verified in the car on 2026-10-30, four Exits, SYNC
  back about 3 s after each.
- **Seen:** 2026-10-30, Mondeo Mk5, SYNC 3.10, no adapter connected. Tapping AutoKit's
  **Exit** (Chinese 退出) leaves the screen frozen; the SYNC buttons do nothing. The soft reset
  did not help twice; switching the car off and opening and closing the driver's door did.
- **Cause (measured in the car with `s2am job logger`):**
  - AutoKit's Exit only **hides** AutoKit. Its own log (`hwlog.log` in its folder) says
    `ManageApp.cpp(531): SW_HIDE`; the process keeps running and keeps answering.
  - The launcher `SyncAppsRunner.exe` hid SYNC's own screen (window class `DESKTOP`) when
    AutoKit started, and gives it back only when AutoKit's **process ends**. So it waits.
    The launcher is SyncExtPack's, not Ford's: it comes with SyncExtPack's app pack
    (`SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe`, 11776 bytes).
  - What stays on the screen is SYNC's empty shell background: a window of class
    `DesktopExplorerWindow` from `mishell.exe`, always visible behind everything.
  - Car off and the door work because SYNC sleeps and, on waking, AutoKit is ended; the
    launcher then gives the screen back within a second. SYNC does not reboot.
- **Without the guard:** car off, driver's door open and closed (above), or leave AutoKit
  with *Reboot* instead of Exit.
- **Fix:** `s2am job runner-guard`. It puts a small guard (`s2am/native/s2amrun.c`) in the
  launcher's place:
  - SyncExtPack's launcher is kept as `SyncAppsRunner.orig.exe` and still does all its own work.
  - It acts only when **nothing usable is on the screen** for 3 s: no visible window at all
    except the shell background. SYNC's screen, the reversing camera, a dialog or the app
    itself all count as usable, so it never acts over them, nor on an app still starting.
  - It then sends the app WM_CLOSE. If nothing becomes usable within 2 s, it ends the app,
    and the launcher gives the screen back.
  - **Written 2026-11-15, not yet in the car:** it also closes an app that has had no visible
    window of its own for 5 s, whatever else is on the screen, in the same way. Here the app
    counts as back only if its own window shows again. This closes the hole found on
    2026-11-15: after Exit the installer's window came up within 2 s, so the screen was never
    empty, the hidden AutoKit kept running, and SYNC's CarPlay button did nothing until SYNC
    restarted. Its log line starts with `hidden|`. Only a window of the app's own starts the
    5 s again: a window of something else that stops the first rule's close does not.
  - Each close looks at the screen once more and sends WM_CLOSE only after that look found the
    app still hidden, to the windows that look found. A close that cannot be done (no handle
    for the app, or the system refuses the wait or the end) is never taken for an end: the
    rule tries again once it holds again, and SYNC gets the screen back as below. The log
    says `close|not possible`, `close|failed` or `terminate|refused`.
  - Tapping the app's icon again while it runs, and SYNC's parking screen, show SYNC over the
    app without hiding the app's window (read from the launcher's code), so neither rule
    closes an app that is only behind SYNC.
  - If SYNC still stays hidden after that, the guard gives it back itself, using the
    launcher's own steps. It does so once for each freeze: once the screen is usable again, a
    later freeze gets its own.
  - If the guard cannot wait for the app's process, it keeps treating the app as running and
    keeps watching. The log then says `error|cannot wait for the app` once, with the error.
  - SyncExtPack's launcher is recognised by its exact size. A damaged backup is rebuilt, and a
    launcher it does not recognise is never replaced.
  - It logs to `\SyncExtendedPack\_s2am\guard.log`; `s2am status` shows the last lines.
  - Undo: `s2am job runner-guard --off`.
  - Optional, off unless asked for: `--boost` lets CarPlay's video run ahead while CarPlay is
    alone on the screen ([PERFORMANCE.md](PERFORMANCE.md)). It does so only while the guard
    holds a handle for AutoKit's process, which is how it knows when AutoKit has ended.
    `--boost off` turns only that off; `--off` takes it away with the guard.
- **History:** the first guard (7bf95ed) did nothing in the car, for two reasons found in the
  watch log: the app plugins pass the path with **forward slashes**
  (`/SyncExtendedPack/Apps/Media/AutoKit/AutoKit.exe`), which it did not split, so it never
  recognised AutoKit; and it counted the shell background as "another program in front".
  The second guard fixes both. In the car it sends `WM_CLOSE` about 2 s after Exit, AutoKit
  ends within 0.3 s, and SyncExtPack's launcher shows SYNC again.
- SyncExtPack's `SyncAppsRunner_Eject.exe` is **not** the fix: it lacks the sound routing.
- **Reported upstream:** [chr0m1ng/syncextpack#4](https://github.com/chr0m1ng/syncextpack/issues/4),
  with the cause, this workaround and an offer of a PR for the pack.

### SYNC 2 or CarPlay is very slow
- **Seen:** 2026-11-04, the first run of CarPlay. Taps in CarPlay react late, its picture is
  choppy, and Ford's own screens are slow too.
- **Measured 2026-11-14:** with CarPlay running, the processor is at 100% nearly all the time.
  AutoKit's software video decoding takes the biggest share.
- **Status:** open. Everything known, and the plan, is in [PERFORMANCE.md](PERFORMANCE.md).

### A call over CarPlay does not work
- **Seen:** 2026-11-14, a call at 12:06 with CarPlay running. In the owner's words: the
  microphone and phone do not work.
- **Cause:** not known. The wired adapter has no microphone of its own, so AutoKit has to take
  the sound from SYNC's microphone. AutoKit's log says nothing about the microphone. SYNC's own
  hands-free service may hold the microphone, or AutoKit may not open it on this system.
- **For now:** don't rely on CarPlay for calls. Whether SYNC's own Bluetooth phone works while
  CarPlay runs, or only after Exit with the cable out, has not been tested yet. Test it before
  you depend on it.

### CarPlay does not come back after switching to the radio
- **Seen:** 2026-11-14. The radio was started while CarPlay played music. The music then played
  on the radio, and CarPlay's music would not start until the cable was pulled out and put back
  in. After that CarPlay did not start again.
- **In the logs:** at 12:18 CarPlay's picture stream stopped while AutoKit stayed in front. At
  12:44 AutoKit's window disappeared and the runner guard closed it. Which of the two was the
  radio is not certain, because the time was not noted.
- **What brought it back, if the stop at 12:18 was the radio:** switching the car off and on.
  AutoKit started again by itself and CarPlay ran.
- **Cause:** not known. Probably SYNC and AutoKit both claim the sound when the source changes.

### No parking-sensor pop-up while AutoKit is open
- **Seen:** 2026-10-30 with the runner guard and no adapter, and again on 2026-11-04 with CarPlay
  running. In reverse, AutoKit's screen stayed and the pop-up did not appear. Whether the
  sensors' beeps were heard was not noted.
- **Not the guard:** on 2026-10-30 the watch log shows AutoKit's window visible and on top the
  whole time, so the guard did nothing. AutoKit's own log grew fast at the same time.
- **Cause:** not known yet. The pop-up has no window of its own; AutoKit's full-screen window
  probably covers it.
- **For now:** leave AutoKit (Exit) before reversing. The test car has no reverse camera, so a
  camera picture is untested; expect the same.
- **To find out more:** run a logger job, open AutoKit and reverse. The watcher keeps every
  run of AutoKit's log as a numbered copy (`autokit-hwlog-live-01.log`, ...).

### AutoKit is in Chinese
- **Seen:** 2026-10-30. The waiting screen reads 请使用车机USB接口 连接 AutoPlay 盒 ("connect the
  AutoPlay box to the car's USB port"); 退出 means Exit, and the globe icon is the language.
- **Cause:** AutoKit's folder holds a 4-byte file `lang` with a Windows language code. The stock
  file is 0x0804, Simplified Chinese. `PAL2.dll` maps the code to
  `\Temp\riddlebox\<Language>.lng`.
- **Fix:** installs made with s2am since 30 October 2026 start in English (the stock file is
  kept as `lang.orig`). For an older install, run `s2am job autokit-config --lang english
  --serial S` (0x0409). It keeps a backup, and `--restore <job>` undoes it. Verified in the car.

### Video Player: a video glitches, or the sound runs off the picture
- **Seen:** reported 2026-10-31, with the test videos from `tools/make_test_videos.py`. The
  800x480 H.264 files played fine; the 720p and 1080p files glitched. In the sync test the beep
  came slightly off the white flash.
- **Cause:** larger videos are more than the player manages on SYNC 2. The sync offset is the
  player's: in the files every beep starts on the same frame as its flash (measured on the Mac).
- **Fix:** convert videos to 800 pixels wide, H.264, before copying them, for example
  `ffmpeg -i in.mp4 -vf scale=800:-2 -c:v libx264 -profile:v baseline -c:a aac out.mp4`
  (`-2` keeps the proportions).

### The colours look wrong after a theme job, or SYNC acts up
- **Fix:** insert the theme job's undo stick (`s2am job theme --restore <job>`, built together
  with the change). It carries Ford's original files itself and SYNC restarts with them.
- The full ladder, down to reinstalling SYNC 3.10, is in
  [sync-redesign's RECOVERY.md](https://github.com/Theralley/sync-redesign/blob/main/docs/RECOVERY.md).

### The import says `rollback-failed`
- **Cause:** a new file did not copy whole, and copying the originals back failed too. The car
  may have a damaged file.
- **Fix:** use the job's undo (restore) stick now. If the screen stays dark, insert it anyway
  and wait two minutes.

### The import says `interrupted` or `not-verified` (theme, Apps menu, screen or decoder job)
- **`interrupted`:** the job began changing the car's files and did not finish (power cut,
  stick pulled), or it found its own backup on the car from such a run. The car may hold a mix
  of old and new files. **Fix:** build and insert the job's undo stick, as the import says
  (`s2am job <kind> --restore <job>`). It carries the originals itself.
- **`not-verified`:** the files the car holds are not byte for byte what the Mac expects: the
  new ones after a job that ran to the end, or the originals after a job that rolled back (a
  copy can go wrong and keep its length, and the car checks sizes only). A job run again from a
  stick that holds no copy of the run that finished it (another stick, or one whose own run was
  cut short) reads the same until the stick it finished from is imported.
  **Fix:** the same undo stick. For a decoder job, AutoKit may not start until it has run.
- **`failed` with "verified: the originals are back":** a new file did not copy whole, and the
  originals the job put back were checked byte for byte. Nothing more to do.
- **`failed`, and `s2am report --serial <serial> <job>` shows `old-report.txt`:** the stick still
  held files from an earlier run of the job (its stop markers or its copies of the car's files),
  and the car could not delete them. They would speak for this run, so it stopped before it
  changed anything. **Fix:**
  import the stick, then prepare the job on another stick and insert that one.
- **An undo (restore) job that is `interrupted`:** prepare its stick again on the Mac
  (`s2am stick prepare` with the same restore job) and insert it. Inserting the old stick again
  does nothing: UpdateService has used it up. If the restore itself is `not-verified`, build a
  new restore job instead: the car counts the old one as done.

### The new Apps menu shows nothing, or a tile starts the wrong app
- **Fix:** insert its undo stick (`s2am job apps-menu --restore <job>`). It carries SyncExtPack's
  original `SyncApps.swf` itself; SYNC restarts with the old list. The tile pictures stay in
  `Tiles\` and do nothing. The rest of SYNC is not affected: the Apps menu loads only when
  you open Apps.

### A bundle stopped half-way
- **What the import says:** the bundle `stopped`; one part says why (`stale`, `failed`, `rollback-failed`), the
  parts after it `not-run`, the parts before it `applied` and verified.
- **Fix:** the parts before it are on the car, each with its backup. Keep them, or insert the
  undo bundle (or a part's own undo stick). Plan the stopped part again after a drive log.
- **`interrupted`:** a part started and did not finish (power cut, stick pulled). Insert the
  undo bundle: each undo carries the originals itself.

### A rebuilt Ford screen does not open or looks wrong
- **Fix:** insert its undo stick (`s2am job screen --restore <job>`). It carries Ford's original
  screen itself; SYNC restarts with it. Only screens SYNC loads when they are opened are ever
  changed (the call history first), so the rest of SYNC, the climate and the camera are not
  affected.

### An app in the Apps menu does nothing when tapped
- **Seen:** 2026-10-30. A previous owner's MirrorLink, Video Player, Navitel and Reboot showed
  in the menu, but nothing happened on tap: no error, no freeze.
- **Cause:** the menu file (`SyncApps.xml`) survived, but the apps' plugins and files did
  not. Above all, the shared launcher `\SyncExtendedPack\Apps\Tools\SyncAppsRunner.exe` was
  gone, and every app starts through it. A later SYNC update had probably wiped part of the
  old install.
- **Check:** an inventory job. `s2am status` lists the plugins and app folders that are actually
  there.
- **Fix:** remove the dead entries (`s2am job remove A B C --purge`), then install the app pack
  (`s2am bootstrap prepare --apps-only`), which brings back SyncAppsRunner.exe.

### A MortScript error dialog appears when a job stick runs
- **Seen:** 2026-10-30, the first inventory stick: **"'If' without 'EndIf'"**, line 46. After you
  tap OK, SYNC still says "Install successfully completed!", but the stick has no report.
- **Cause:** a bug in the car's MortScript 4.3.0.15. A line that is only a keyword (`EndIf`,
  `Exit`, …) can be dropped. Details in [MORTSCRIPT.md](MORTSCRIPT.md).
- **Fix:** built into `s2am`: keywords are written as `EndIf()`, and every script is checked
  against the car's rules before a stick is built. If you still see a dialog, photograph it, tap
  OK, and import the stick.

### "Install successfully completed!", but `stick import` says `processed-no-report`
- **Meaning:** the installer consumed the package, but no recognized job result was returned.
  The installer ignores the script's result. A pre-parse error can cause this, but the status
  alone does not identify the cause or prove the car stayed unchanged.
- **Check:** preserve/import the return and record the screen message and current app behavior.
  A two-line installer log is also normal on successful jobs. Investigate the missing script
  report before retrying; see the known MortScript dialog above.
- **Seen:** the November 16 decoder return had the exact prepared pack but no job report
  directory. Its launcher/interpreter matched a successful clock job, and script structural
  checks passed. Installation remains unverified; there is no confirmed fix yet.
- **Independent follow-up:** UpdateService ignores POST_APP creation failure/exit status, and
  MortRunner silently returns zero on missing script or interpreter launch failure. A new
  [native inspection job](DECODER-INSPECTION.md) collects evidence without that launch chain;
  those code paths are possible causes, not proof of what happened in this run.

### Nothing happens when the job stick is inserted
- **Inserted right after SYNC started?** If the stick goes in too soon after starting the car or
  restarting SYNC, SYNC does not pick it up. Pull it out, wait until SYNC has finished starting,
  and insert it again. Reported by the car's owner, 2026-11-15; how long SYNC needs is not measured.
- **Cause:** the car has no SyncExtPack UpdateService (job sticks need it), or the stick's
  `install.bin` was already used and renamed to `installed.bin`.
- **Check:** `s2am stick import` (pending, or processed?). Is `SyncExtPack/install.bin` on the stick?
- **Fix:** with no UpdateService, do the first install (README *Quick start*, the wallpaper
  step). A used stick: prepare a new job; `stick prepare` moves the old files aside.
- **Seen:** 2026-10-31, the first bundle: taken out and put back, the used stick did nothing.
  That is the protection working, not a fault.

### SYNC restarted after a job
- **Expected** for jobs that change the Apps menu (remove, install, undo) and for the app pack.
  Wait until SYNC is fully back before you pull the stick.

### AutoKit opens but says to connect the "AutoPlay box"
- **Expected** without the Carlinkit adapter. It is the screen that waits for the adapter.

### Uninstall: no button on SYNC
- SYNC has no uninstall option for these apps. **The stick is the uninstaller:**
  `s2am job remove "Name" --purge`, put it on a stick, insert it.

---

### A logger stick recorded only its first line
- **Seen:** 2026-10-30, the first logger (a MortScript loop): `log.txt` held `start|...` and
  nothing else. The loop had **hung**, not ended: its process was still running half an hour
  later and went away only when SYNC rebooted.
- **Fix:** built in. The logger job now runs a compiled watcher (`s2amwatch.exe`) instead.

## On the Mac

### `stick check`: `FAIL file system: ExFAT`
- **Cause:** Disk Utility's default format. SYNC 2 needs FAT32.
- **Fix:** erase as **MS-DOS (FAT)** with the **Master Boot Record** scheme. A 2 GB stick became
  FAT32, which is fine.

### `eject failed … Unmount was dissented by PID … loginwindow`
- **Cause:** macOS (Finder or Spotlight) still had the stick open. The job is on the stick anyway.
- **Fix:** eject it in Finder before you pull it.

### The stick ejects before you can look at it
- `stick prepare` ejects by default. Use `--no-eject` to check the files first, then
  `diskutil eject`.

### A pack builds, but the car unpacks nothing
- **Cause:** `crypto_pack -p` was given a folder without a trailing slash.
- **Fix:** built into `s2am` (`payload/`). Every pack is also unpacked on the Mac and compared
  before you get it.

### `too close to a key window boundary` / a pack expired
- Packs are keyed to the serial and a 30-day window. `s2am window` shows when the current one
  ends. Build again after that date.

### The serial looks wrong
- The APIM serial has 8 characters and **never the letter O**: a round character is a zero.

### `… is not in the Apps menu`
- Removal and install are planned from the last inventory. Run a new inventory job if the car
  has changed since, and use the names exactly as `s2am status` prints them.

---

## Collecting information for a bug report

1. Photograph any dialog **before** tapping OK.
2. Keep the stick as it is and run `s2am stick import /Volumes/STICK`, then
   `s2am report --serial S` and `s2am status --serial S`.
3. Note your SYNC version (*Settings → General → About SYNC*) but **not** your serial or VIN.
4. [Open an issue](https://github.com/Theralley/sync2-auto-magic/issues) with the symptom
   wording from this page, so the next person can find it.
