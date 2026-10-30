# Troubleshooting: symptom → cause → fix

Search this page for what you see on the screen or in the terminal. Every entry was met in a
real car or a real build, unless it says otherwise. The car results are in
[P1-TESTLOG.md](P1-TESTLOG.md).

**Soft reset (use it whenever SYNC is stuck):** with the car in Park, hold the
**power/volume knob and Seek-Up (next track, ⏭)** for about 10 seconds, until the screen goes
black. SYNC restarts and nothing is uninstalled. If that does not work: engine off, lock the
car, wait 10 minutes.

---

## In the car

### Leaving AutoKit freezes the screen
- **Seen:** 2026-10-30, Mondeo Mk5, SYNC 3.10, no adapter connected. Tapping AutoKit's
  **Exit** (Chinese 退出) leaves the screen frozen; the SYNC buttons do nothing.
- **Cause:** not known yet. Either AutoKit hangs while closing, or it closes and the launcher
  (`SyncAppsRunner.exe`) never hands the screen back to SYNC.
- **Fix now:** soft reset (above). To avoid it, leave AutoKit with *Reboot* instead of Exit.
- **Next:** a logger stick records AutoKit's process and the active window, once a second,
  while you tap Exit (`s2am job logger --seconds 300`). That log decides between JasonACT's
  improved runner and our own ([P2 plan](P2-AA-AUTOSTART-PLAN.md), AS-2a/AS-2). SyncExtPack's
  `SyncAppsRunner_Eject.exe` is **not** the fix: it lacks the sound routing.

### AutoKit is in Chinese
- **Seen:** 2026-10-30. The waiting screen reads 请使用车机USB接口 连接 AutoPlay 盒 ("connect the
  AutoPlay box to the car's USB port"); 退出 means Exit, and the globe icon is the language.
- **Cause:** AutoKit's folder holds a 4-byte file `lang` with a Windows language code. The stock
  file is 0x0804, Simplified Chinese. `PAL2.dll` maps the code to
  `\Temp\riddlebox\<Language>.lng`.
- **Fix:** installs made with s2am since 30 October 2026 start in English (the stock file is
  kept as `lang.orig`). For an older install, run `s2am job autokit-config --lang english
  --serial S` (0x0409). It keeps a backup, and `--restore <job>` undoes it. Verified in the car.

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
