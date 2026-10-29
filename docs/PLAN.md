# iPhone on a 2016 Ford Mondeo Mk5 (SYNC 2), plan

Written 2026-10-29. Research by two Fable agents (web), two read-only Codex passes (local code), and Claude (verification and binary inspection).
Constraint from the owner: **no boxes and no hardware add-ons; software only.**

**Decision (owner, 2026-10-29): route 4B first.** That means real iPhone CarPlay through one Carlinkit USB dongle plus our software. The dongle is the wired CPC200-CCPM, which is the model SYNC 2 owners have run; the CPC200-CCPA is the wireless option. Once that works, add **Android Auto** through the same dongle and AutoKit, replacing MirrorLink mirroring. Use whichever Android version is easiest. Android 10 is fine, because the dongle runs real Android Auto rather than mirroring.

Progress: the sound patch (`tools/patch_waveout.py`) and the fail-closed pack builder (`tools/make_pack.py`) are built and tested off the car. See the README.

## 1. Verdict

**Real CarPlay with zero added hardware is not possible on SYNC 2.** Three hardware requirements block it:

| CarPlay needs | SYNC 2 has | Source |
|---|---|---|
| An Apple MFi authentication chip that answers the iPhone's CarPlay challenge | No usable one. Reusing the iPod chip that SYNC 2 may carry for iAP has never been done. It would mean rebuilding Apple's closed CarPlay stack on WinCE: months of reverse engineering with low odds. | 9to5Mac, Fable report |
| **Wired:** a USB port that can switch roles, so the iPhone becomes the USB host | The USB ports sit behind an ordinary hub, and an ordinary hub cannot reverse roles. This is why SYNC 3 retrofits need a "CarPlay-compliant" hub. | Apple developer forums, Acroname, CyanLabs |
| **Wireless:** 5 GHz Wi-Fi advertising Apple's CarPlay beacon | A 2011-era Wi-Fi module, client or gateway mode (whether it can do 5 GHz is unverified) | Apple wireless CarPlay test guide, Ford support |

**The smallest piece of hardware that removes all three blockers** is a Carlinkit USB dongle (CPC200-CCPA, wired and wireless, about 400 SEK; or CPC200-CCPM, wired only). It is the size of a USB stick, plugs into the existing armrest USB port and needs no installation. It carries the Apple chip and the Wi-Fi, and everything after it is software: the AutoKit host app on SYNC 2, plus the fixes below.

**The easiest route that needs nothing new is an old Android phone on a cable** (owner's suggestion, section 4A). Android screen mirroring needs no Apple chip. The pack already ships the app for it (EasyConnection), and the community has it working on SYNC 2.

## 2. What the local repos are

| Folder | What it is | Relevant? |
|---|---|---|
| `syncextpack/` (chr0m1ng) | Builds a sideload pack for SYNC 2 (installed through the wallpaper "Installer.jpg" trick). Ships AutoKit 2022 (Carlinkit's WinCE host), VideoPlayer, Navitel, Total Commander, Reboot. | **Yes, the base for everything** |
| `Ford-Sync2-MirrorLink-VideoPlayer-Navitel/` | EasyConnection screen mirroring, **Android only**, with install PDFs and the phone APK link | **Yes for Route A** (old Android phone) |
| `arduino-ford-sync2-map-sdkey/` | Generates the key file for a navigation-map SD card | No |

All three are third-party clones. We never push to them; our own work goes in a new repo of ours.

## 3. New finding: why AutoKit has no sound, and a software fix

Field reports for AutoKit on SYNC 2 say "picture but no sound" (XDA, 2023). Static inspection of the pack explains why:

- SYNC 2 routes app audio through a Ford system API: `RAC.dll` → `RAC_RequestClientID` / `RAC_RequestRouting`.
- The community's working apps reach the speakers through **`WaveOutHooks.dll`**, a shim exporting `waveOutOpenCustom` and similar functions that requests a RAC route. **Their import tables were patched** to call the shim instead of `COREDLL!waveOutOpen`: `Navitel.exe`, VideoPlayer's `quartz.dll`, `voFltFR.dll` and `voPreview.dll` all import `WaveOutHooks.dll`.
- AutoKit's audio sink (`libgstwaveoutsink.dll`, a GStreamer plugin built for SiRF Prima) calls `COREDLL!waveOutOpen` directly, with no RAC route. That gives silence, which matches the reports.
- **Fix hypothesis:** patch the import table of AutoKit's audio sink to use `WaveOutHooks.dll`, the same way VideoPlayer and Navitel were patched. This is a byte-level, reversible patch and needs no compiler. It is unproven until tested on the car.

Other findings:
- `SyncAppsRunner.exe` already closes apps with `WM_CLOSE`, waits 1 s, then calls `TerminateProcess`, and restores the SYNC UI through `SYNC_DESKTOP_SHOW_UI` / the `DESKTOP` window. The send is synchronous and can hang, which is the likely cause of the reported touchscreen lock-up after quitting AutoKit.
- The Carlinkit dongle enumerates as USB `1314:1520` / `1314:1521` (`box.reg`). A watcher service can detect it, as `UpdateService.dll` already does for `install.bin`.
- `create_plugin_dll.py` is **broken**: `struct.pack` gets 30 arguments where 31 are required, and it would emit an empty DLL anyway. Use the shipped `AutoKitPlugin.dll`.
- `packer.py:66` ignores `crypto_pack` failures (fail-open). `crypto_pack_docker.sh:29` interpolates `$*` into `bash -c`.
- The pack key is derived from the APIM serial plus a 30-day time bucket (`magic=0`). **Build and install in the same month.**
- No complete factory rollback exists. `RemovePack` deletes `\SyncExtendedPack` but leaves modified skins and DLLs. Recovery is a soft reset (Power + Seek-Up for 10 s) or a 3.08 ↔ 3.10 firmware reflash.

## 4A. Route A: old Android phone over cable (zero hardware, easiest)

The car gets a modern screen: maps (Waze, Google Maps), Spotify, podcasts and YouTube when parked, mirrored onto the 8" screen with touch. The iPhone stays your phone over SYNC 2 Bluetooth.

- **How it works:** EasyConnection (`MirrorLink_EN_NEW` in the pack) talks to the phone over the USB cable through ADB (`ADB_Driver.dll`) and mirrors its screen. Touches on the car screen are sent back to the phone.
- **Sound:** EasyConnection has no SYNC 2 audio routing (no `WaveOutHooks`/RAC), so sound goes from the Android phone to SYNC 2 over Bluetooth. That matches the forum report "the sound flies over bt… update to 3.10".
- **Phone requirements:** Android 9 or older for touch from the car screen. On Android 10 and later you must operate it on the phone. Some brands (Huawei, ZTE, low-end Xiaomi) do not work. Keep the screen on, run it on the charger, and use a car-launcher app for big buttons.
- **Internet:** the Android phone joins the iPhone's Personal Hotspot.
- **Open question to test:** can SYNC 2 hold the iPhone for calls and the Android phone for music at the same time? If not, music plays from whichever phone is the active SYNC device.
- **Security:** the EasyConnection phone APK comes from a file-share link. Put it only on the dedicated old phone with no personal accounts beyond Maps and Spotify.

Steps:
1. Phase 0 below (firmware version, APIM serial, recovery USB).
2. Build the pack `MirrorLink_EN_NEW Explorer Reboot`, install it, then install the EasyConnection APK on the Android phone and enable USB debugging.
3. Pair the Android phone to SYNC 2 for media audio. Test touch, sound, lag, and quitting back to SYNC 2.
4. Then the software polish we build: auto-launch when the phone is plugged in and a clean return to SYNC 2 when unplugged (same watcher as 2b, keyed on the phone's ADB USB device instead of the dongle), and builder hardening (2c).

## 4B. Route B: real iPhone CarPlay through a USB dongle plus our own software

The goal is to plug in the iPhone and get CarPlay, then unplug it and get normal SYNC 2.

**Phase 0: prepare (no changes to the car)**
1. Read the firmware version under Settings → General → About SYNC; the latest is 3.10 build 16180. Note the APIM serial.
2. Prepare a recovery USB stick (FAT32/MBR, 32 GB or smaller) with the 3.10 and 3.08 packages. Learn the soft reset: Power + Seek-Up held for 10 s.
3. Start our own private repo and a reproducible macOS build (Docker for `crypto_pack`, Java for SWF).

**Phase 1: baseline test on the car (one evening)**
1. Build a minimal pack: `AutoKit VideoPlayer_EN Explorer Reboot`. VideoPlayer is a probe: a 800×480 H.264 test clip shows whether hardware decode and RAC audio work on this car.
2. Plug in the dongle and iPhone. Record picture, frame rate, sound, touch and exit behaviour.
3. **Gate:** if the install or the exit cannot be recovered with the soft reset, stop and reflash.

**Phase 2: the software fixes we build**
- **2a. Audio (highest value):** a Python PE patcher that redirects `libgstwaveoutsink.dll` (and any other AutoKit waveOut user) to `WaveOutHooks.dll`. Keep the originals. Test on the car. **Gate:** if there is still no sound, test the "audio over Bluetooth" setting, then decide whether to continue.
- **2b. Auto-switch and clean exit:** a small native WinCE watcher built with CeGCC in Docker on macOS (or VS2008 + the WEC7 SDK in a VM). It starts AutoKit when the dongle or phone session appears. On disconnect it closes AutoKit with a bounded asynchronous close, then terminates it, then calls `SYNC_DESKTOP_SHOW_UI`.
- **2c. Builder hardening:** fail closed on `crypto_pack` errors, validate serial and month, produce a dry-run file manifest with SHA-256, remove the shell injection, retire the broken DLL generator.

**Phase 3 (stretch): smoother video**
AutoKit decodes in software (ffmpeg) because its hardware-decode files target MediaTek and SiRF. VideoPlayer's `h264decdll.dll` uses a hardware engine (`pvr_mved1.dll`). If Phase 1 shows that hardware decode works on this APIM, explore a host that uses it. That host would be a port of the open-source FastCarPlay (C++, GPL-3). This is a large job, so it only starts if Phases 1–2 succeed.

## 5. Free iPhone improvements today, and the AirPlay idea

- **Phone-side, today, free:** hold the steering-wheel voice button for about 2 s to start Siri Eyes Free. Turn on iPhone Settings → Bluetooth → (i) for the car → Show Notifications, so SYNC reads incoming texts. An iOS Shortcuts automation on "Bluetooth connected: SYNC" can start Driving Focus, music, and Maps or Waze.
- **R&D option, AirPlay screen mirror:** the iPhone joins SYNC 2's own Wi-Fi hotspot (Gateway AP mode) and a sideloaded receiver shows the phone screen. Open-source AirPlay receivers (UxPlay, RPiPlay) need no Apple chip. This is mirroring, not CarPlay: you cannot touch it from the car screen, the phone stays unlocked, and porting to WinCE is a large job with the same decode and audio unknowns. Not recommended unless hardware stays absolutely ruled out.

## 6. Ruled out by the owner (for reference)

- LVDS "decoder" box (about €260): manual toggle, AUX-quality sound, mixed reviews.
- SYNC 3 retrofit (€400–700 in parts + FORScan): native CarPlay, but it replaces SYNC 2. Mid-2016+ Mondeo parts fit, and the as-built and climate-screen setup is the hard part.

## Sources

- XDA SyncExtPack builder thread; XDA MyFord Touch hack thread p.100 (reports of no sound, crash on exit, and "sound over BT on 3.10")
- [Apple developer forums: CarPlay session and USB role switch](https://developer.apple.com/forums/thread/732990) · [WWDC 2017 wireless CarPlay](https://devstreaming-cdn.apple.com/videos/wwdc/2017/717tmz5rl6c2t2k/717/717_developing_wireless_carplay_systems.pdf?dl=1) · [Acroname: hubs cannot do CarPlay role reversal](https://acroname.com/blog/usb-hub-or-usb-switch) · [Wireless CarPlay test guide (5 GHz)](https://www.scribd.com/document/977207654/Wireless-Performance-Test-Guide-R6) · [9to5Mac: MFi for CarPlay](https://9to5mac.com/?p=357022)
- [Ford: SYNC 2 Wi-Fi client/gateway](https://ford.ie/support/how-tos/sync/sync-2/how-to-connect-to-wi-fi-using-sync-2) · [Ford: Siri Eyes Free on MyFord Touch](https://www.ford.com/support/how-tos/sync/sync-with-myford-touch/how-to-use-your-iphone-and-siri-eyes-free-with-myford-touch) · [Ford: iPhone texts on MyFord Touch](https://www.ford.com/support/how-tos/sync/sync-with-myford-touch/receiving-iphone-text-messages-with-sync-with-myford-touch)
- [CyanLabs: SYNC 2 → 3 retrofit](https://community.cyanlabs.net/t/sync-2-to-sync-3-upgrade-questions/20861) · [Ford Europe: SYNC 3 on Mondeo, July 2016](https://media.ford.com/content/fordmedia/feu/en/news/2016/07/14/ford-reduces-running-costs-and-improves-connectivity-for-mondeo-.html) · [Navinc LVDS interface](https://legacy.navinc.nl/7772)
