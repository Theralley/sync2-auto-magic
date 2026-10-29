# Phase 1 runbook: first install, CarPlay test, first inventory

Car: 2016 Ford Mondeo Mk5, 8" SYNC 2, software probably 3.10. Phone: iPhone.
Adapter: CarlinKit wired AutoKit adapter ([Amazon.se B0919JS1K3](https://www.amazon.se/dp/B0919JS1K3)).
Reviewed by Codex (2026-10-29). Budget **about 2 hours** at the car, engine running.

## Goals: what counts as success

| # | Goal | Pass when |
|---|---|---|
| G1 | SyncExtPack installed | *i → Apps* shows **AutoKit**, **Total Commander** and **Reboot** |
| G2 | CarPlay picture and touch | the CarPlay home screen shows on SYNC 2 and taps work |
| G3 | **Sound** (the audio patch) | CarPlay music plays through the car speakers, and the A/B test shows the patch is the reason |
| G4 | Microphone | Siri hears you, or a test call works both ways |
| G5 | Clean exit | after leaving AutoKit, the SYNC touchscreen still responds, also after the car has been switched off and on |
| G6 | First `s2am` report | `s2am status` lists AutoKit's files **and** the Apps menu from the copied `SyncApps.xml` |

Missing G1 stops the session. G2–G5 are measurements: a "no" is still a useful result.

## Before the car (at home)

### 1. Sticks (Windows 11 or Mac)

You need **two sticks** of 32 GB or less:
- **stick A** for SyncExtPack and the jobs;
- **stick B** for recovery (step 3).

Formatting erases a stick.

1. File Explorer → *This PC* → right-click the stick → **Format…**
2. File system **FAT32**, allocation unit *Default*, label `SYNC`, tick *Quick Format* → **Start**.
3. Press **Win+X**, choose *Disk Management*, right-click the stick's *Disk N* label →
   *Properties* → *Volumes*. *Partition style* must be **Master Boot Record (MBR)**.

If it says GPT, open an administrator terminal and run `diskpart`. Then, **after checking the
disk number against the stick's size**: `list disk` → `select disk N` → `clean` → `convert mbr`
→ `create partition primary` → `format fs=fat32 quick label=SYNC` → `assign`. Selecting the wrong
disk erases it.

Then on the Mac run **`python3 -m s2am stick check /Volumes/SYNC`**. It must show no ✗. It checks:
- FAT32, MBR, 32 GB or less, external, writable;
- that no firmware-update files or waiting `install.bin` are on the stick.

### 2. Read the car (any time, 2 minutes)

On SYNC 2: *Settings → General → About SYNC*. **Photograph the screen.** It shows the
**APIM serial** (8 characters) and the **software version**. SyncExtPack recommends 3.10; note
exactly what it says.

### 3. Recovery stick (stick B)

Get the **3.10 update package for your region** (see SyncExtPack's
[firmware guide](https://github.com/chr0m1ng/syncextpack/blob/main/FIRMWARE_INSTALLATION.md)) and
unpack it onto stick B. Keep it **unplugged** until you need it: its `autoinstall.lst` starts a
firmware update as soon as it goes in. Read Ford's own
[SYNC 2 update instructions](https://www.ford.co.uk/content/dam/guxeu/uk/owners/resources-support/sync-support/update/SYNC_2_InstGuide.pdf)
and keep a copy on the phone, offline.

### 4. Build (Mac, with the serial, Docker Desktop running)

```sh
python3 -m s2am window                     # must say "safe to build" (exit code 0)
python3 -m s2am bootstrap prepare --serial SERIAL --stick /Volumes/SYNC   # stick A, stage one
python3 -m s2am job inventory       --serial SERIAL   # session 3
python3 -m s2am job autokit-stock   --serial SERIAL   # A/B test in session 2
python3 -m s2am job autokit-patched --serial SERIAL   # A/B test in session 2
```

The current window closes **2026-11-17 09:35 UTC**. Builds are refused within 2 days of that
and for 12 hours after it. **Build and install inside the same window.** The APIM clock may be
off, so do not build at the edges.

### 5. Bring

- the Mac (the rename step, the job sticks, reading reports), stick A and stick B
- the adapter and a cable from it to the iPhone (Lightning, or USB-C for iPhone 15 and later)
- the phone, charged
- **fuel and a healthy battery**; turn **Auto-Start-Stop off** so the engine keeps running

## Session 1: install (about 20 minutes)

| Step | Do | Check | If not |
|---|---|---|---|
| 1.1 | Start the engine and turn off Start-Stop. Wait until SYNC 2 has fully loaded | Home screen | — |
| 1.2 | Insert stick A. *Settings → Display → Wallpaper → Add →* the USB stick → **Installer.jpg**. Tap once and wait. | SYNC shows the installer, then **restarts** | See *Install problems* below |
| 1.3 | After SYNC has fully restarted, pull the stick. On the Mac: **`python3 -m s2am bootstrap finish /Volumes/SYNC`**. It checks the build, renames `pack_install.bin` to `install.bin`, and ejects. | Prints "ready" | Do not rename by hand; the command's checks stop a wrong or expired pack |
| 1.4 | Put the stick back in | Installation window with progress, then **"Install successfully completed!"**; it may restart | See *Install problems* below |
| 1.5 | *i → Apps* | **AutoKit, Total Commander, Reboot** are listed (**G1**). Photograph them. | Missing apps: open Reboot, check again, then stop |
| 1.6 | Pull the stick and keep `SyncExtPack/install_log.txt` | — | — |

### Install problems

- **Never** pull a stick, switch off, or soft-reset while an installation window is showing
  progress. Files are being overwritten.
- **Nothing happens after selecting Installer.jpg** (no window within 5 minutes): pull the
  stick. On the Mac, run `s2am stick check` and check the serial and window. Try **once** more
  after a SYNC restart.
- **"Completed with errors"**: keep the stick unchanged and bring it home. The log is on it.
- **Window stuck with no progress for 30 minutes**: photograph it. Only then soft-reset
  (Power + Seek-Up). Running the same stick again rewrites every file, so an interrupted install
  repairs itself on the next complete run.
- **SYNC unusable**: use the recovery stick (below).

## Session 2: CarPlay (about 40 minutes)

Before each test condition, **restart SYNC** (*Apps → Reboot*). Turn **Bluetooth off on the
iPhone** for T1–T7, so sound cannot come over Bluetooth. Use the **same song at the same volume**
throughout.

Plug the adapter into the USB port, connect the iPhone to the adapter, unlock the iPhone and
allow CarPlay. Then *i → Apps → AutoKit*.

| Test | Do | Record |
|---|---|---|
| T1 | Wait for the picture | Seconds until the AutoKit screen, and until CarPlay (**G2**) |
| T2 | Tap Music and Maps | Does touch work? Is the position right? |
| T3 | Play the test song; turn the volume knob | **Sound from the speakers?** Which SYNC source is shown? (**G3**) |
| T4 | Start navigation in Maps | Is the spoken direction heard? Does the music duck? |
| T5 | Siri: CarPlay's Siri button, then the steering-wheel voice button | Does Siri hear you? (**G4**) |
| T6 | Call voicemail | Audio in both directions? |
| T7 | Scroll the map | Smooth, choppy, or slideshow? |
| T8 | Leave AutoKit (its home/exit button) | Does SYNC respond to touch? (**G5**) If not: **Power + Seek-Up (⏭) for 10 s** |
| T9 | Engine off, open the door, wait 2 minutes, start again | Does touch still work everywhere? |

### A/B test: is the patch really the reason? (do it whatever T3 showed)

The installed pack runs the **patched** modules. Swap all three modules with a job stick, so
nobody has to rename files by hand:

1. Restart SYNC (do not open AutoKit). On the Mac:
   `s2am stick prepare /Volumes/SYNC --job build/jobs/<akstock id>`. Insert the stick and wait
   for "completed". Pull it. Then `s2am stick import` and `s2am status`, which must say
   **"AutoKit audio modules: stock (all 3)"**.
2. Restart SYNC and repeat T1–T3 → that is the **stock** result.
3. Run the `autokit-patched` job the same way. `status` must say **"patched (all 3)"**. Restart
   SYNC and repeat T1–T3.

| Patched | Stock | Meaning |
|---|---|---|
| sound | none | **the patch works** |
| sound | sound | the patch is not needed |
| none | none | inconclusive; try Bluetooth (below) |
| none | sound | the patch breaks it; stay on stock |

If an import says **busy**, AutoKit was still running: restart SYNC and insert the same stick
again. The job has not run yet.

**Bluetooth variant (after the A/B test):** pair the iPhone with SYNC and select the BT audio
source, then repeat T3. A forum report says sound came "over BT" on 3.10.

## Session 3: first inventory (about 5 minutes)

```sh
python3 -m s2am stick prepare /Volumes/SYNC --job build/jobs/<inventory id>
#   car: insert the stick, wait for "Install successfully completed", pull it
python3 -m s2am stick import /Volumes/SYNC
python3 -m s2am status --serial SERIAL
```

**G6 passes only** if `status` lists AutoKit's files **and** a menu (not "missing from the
report"). `processed-no-report` means only that the installer ran: MortScript wrote nothing.
Keep the stick; `install_log.txt` is saved in `~/.s2am`.

## Recovery card

| Situation | Action |
|---|---|
| Touchscreen does not respond | **Power + Seek-Up (⏭) for 10 s**, car in Park (some cars ignore this) |
| That does not help | Engine off, lock the car for 10 minutes, start again |
| AutoKit misbehaves | Run the `autokit-stock` job stick, or in Total Commander copy the `*.orig` files over the live ones |
| SYNC unusable | **Recovery stick B** (3.10): insert it, the update starts by itself; follow Ford's instructions. This restores Ford's software, but may **not** remove every SyncExtPack file. |

## What to bring back

Fill in [P1-TESTLOG.md](P1-TESTLOG.md). Also bring photos of *About SYNC* and the Apps menu,
`install_log.txt`, a 20-second video of CarPlay running, and stick A (for `s2am stick import`).

## P1 prep tools (built)

| Tool | Checks |
|---|---|
| `s2am stick check` | FAT32 · MBR · 32 GB or less · external · writable · free space · USB bus · no firmware autorun files · no waiting `install.bin` · no symlinks |
| `s2am bootstrap prepare` | stick check · key window · runs `make_pack` · serial, apps and expiry from the manifest · exactly the 4 files, none empty · archive and every file on the stick verified by SHA-256 · refuses a used stick unless `--force` (old files moved aside) · ejects |
| `s2am bootstrap finish` | the stick was prepared · `pack_install.bin` hash unchanged · not expired · no `install.bin` yet · old `installed.bin`/log moved aside · renames, re-verifies, ejects |
| `s2am job autokit-stock / autokit-patched` | swaps all three audio modules (skips if AutoKit is running), then writes a full inventory; `status` reports which variant is active |

**Lead for after P1:** an XDA member (JasonACT, May 2022) published an improved
`SyncAppsRunner` with source (WTFPL). It catches app crashes, clicks to give focus back to the
SYNC screen when an app exits, and can raise an app's thread priority. That targets G5 and
maybe T7. The runner bundled in SyncExtPack is the older one. Evaluate it if T8 or T9 fail.
