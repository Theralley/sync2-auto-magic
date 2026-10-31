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
  - If SYNC still stays hidden after that, the guard gives it back itself, using the
    launcher's own steps.
  - SyncExtPack's launcher is recognised by its exact size. A damaged backup is rebuilt, and a
    launcher it does not recognise is never replaced.
  - It logs to `\SyncExtendedPack\_s2am\guard.log`; `s2am status` shows the last lines.
  - Undo: `s2am job runner-guard --off`.
- **History:** the first guard (7bf95ed) did nothing in the car, for two reasons found in the
  watch log: the app plugins pass the path with **forward slashes**
  (`/SyncExtendedPack/Apps/Media/AutoKit/AutoKit.exe`), which it did not split, so it never
  recognised AutoKit; and it counted the shell background as "another program in front".
  The second guard fixes both. In the car it sends `WM_CLOSE` about 2 s after Exit, AutoKit
  ends within 0.3 s, and SyncExtPack's launcher shows SYNC again.
- SyncExtPack's `SyncAppsRunner_Eject.exe` is **not** the fix: it lacks the sound routing.
- **Reported upstream:** [chr0m1ng/syncextpack#4](https://github.com/chr0m1ng/syncextpack/issues/4),
  with the cause, this workaround and an offer of a PR for the pack.

### No reverse camera picture while AutoKit is open
- **Seen:** 2026-10-30, with the runner guard, no adapter connected. In reverse, AutoKit's
  screen stayed and the camera picture did not appear.
- **Not the guard:** the watch log shows AutoKit's window visible and on top the whole time,
  so the guard did nothing. AutoKit's own log grew fast at the same time.
- **Cause:** not known yet. The camera picture has no window of its own; AutoKit's full-screen
  window probably covers it.
- **For now:** leave AutoKit (Exit) before reversing. Not tested with the adapter connected.
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
- **Cause:** the job's script stopped before writing anything. Usually the dialog above. The
  installer ignores the script's result.
- **Fix:** see the entry above. Build a fresh job; never re-use the old install.bin.

### Nothing happens when the job stick is inserted
- **Cause:** the car has no SyncExtPack UpdateService (job sticks need it), or the stick's
  `install.bin` was already used and renamed to `installed.bin`.
- **Check:** `s2am stick import` (pending, or processed?). Is `SyncExtPack/install.bin` on the stick?
- **Fix:** with no UpdateService, do the first install (README *Quick start*, the wallpaper
  step). A used stick: prepare a new job; `stick prepare` moves the old files aside.

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
