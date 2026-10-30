# Phase 2 plan: Android Auto, and CarPlay that starts by itself

Planned 2026-10-29 by a Fable + Codex mini-panel and merged by Claude. Fable did the web
research and XDA field reports. Codex did static analysis of AutoKit, SyncAppsRunner and the
installer. Both start **after Phase 1 works** (CarPlay with sound, `s2am` reports), and every
step is one `s2am` job stick with a check in the car.

## What we know

**Android Auto**
- WinCE AutoKit (build `2022.02.15-5897`) has an Android Auto mode. It tells the dongle which
  mode to use (`/etc/android_work_mode`: AA = 1, CarPlay = 2). On SYNC 2, AA has connected, but
  with a picture that was too big. The XDA fix was: *"CarlinKit remembers last used resolution.
  Set it to 800x480 with software decoding."* (Fable [S], XDA SyncExtPack thread)
- AutoKit reads plain files next to `AutoKit.exe` when it starts (Codex, `AutoKit.exe+0x47a48`):
  - **`screenconfig`** holds `width,height,fps` in ASCII (fallback 800×480 at 15 fps);
  - **`usehwdec`** selects hardware decoding: present = hardware, absent = software. Its
    `hwdec_*` markers come from MediaTek builds;
  - `fullscreen`, `autoconnect`, `useboxmic`, `audio_volume` and `audiopriority` are presence
    markers or settings.

  So **resolution and decoder can be set with a job stick.**
- **Phone:** Google's help page now requires **Android 11 or newer for wired Android Auto**
  (raised from 9 in October 2026; Fable [C]). No USB debugging is needed.
- **Sound:** the dongle hands AA audio to AutoKit the same way as CarPlay, so the sound patch
  should apply [I]. **Microphone:** the wired dongle has none (`useboxmic` is hidden in the
  UI), so Google Assistant and calls may lack a mic until the SYNC mic route is proven.
- **Dongle firmware:** AutoKit flashes the dongle if `Auto_Box_Update.img` sits in its folder.
  A wrong or interrupted image kills the dongle, so **s2am must never ship or leave that file**.

**CarPlay that starts by itself**
- The phone plugs into the **dongle**, not into SYNC. The USB driver (`ceusbbox.dll`) only
  reports the dongle itself arriving or leaving, so **a watcher cannot see the phone on its
  own**. AutoKit itself broadcasts state messages (`_UIGEAR_BOX_NOTIFY_`), and those are the
  way to notice a phone; their meanings are not mapped yet.
- WinCE AutoKit has **no auto-start option**. Its "Manual/Auto connection" is wireless reconnect.
- Launch command (Codex, `AutoKitPlugin.dll+0x440`):
  `\SyncExtendedPack\Apps\Tools\SyncAppsRunner.exe \SyncExtendedPack\Apps\Media\AutoKit\AutoKit.exe`.
  A second launch toggles AutoKit's visibility (the `SyncAppsRunnerMutex` mutex plus an event).
  When AutoKit exits, the runner gives the screen back to SYNC.
- **How UpdateService stays loaded:** it is a Windows CE **service**. The installer creates
  `HKLM\Services\UPDATESVC` (`Dll=UpdateService`, `Prefix=UPD`, `Order=10`), so no
  `HKLM\Init` entry is needed. That is the proven way to have something running from boot.
- **Exit freeze (confirmed in the car on 2026-10-30):** tapping AutoKit's Exit button left the
  screen frozen, with no adapter connected. The power/volume knob + Seek-Up soft reset brought
  SYNC back with nothing lost. An XDA member (JasonACT, May 2022) published an improved
  SyncAppsRunner with source. It catches crashes, clicks to give focus back to SYNC, and sets
  thread priority. It fixes the frozen touchscreen after leaving AutoKit, but not auto-start.
  SyncExtPack's own `SyncAppsRunner_Eject.exe` (the `PatchEject` unit) is **not** that fix: it
  is a cut-down runner without the RAC sound routing, so it would mute AutoKit.

## Android Auto: phases (no new native code)

| Step | Job / action | Check in the car |
|---|---|---|
| AA-0 | Phone: **Samsung S24, Android 16** (OK) (needs a USB-A→USB-C cable from the adapter) | — |
| AA-1 (built) | Job `autokit-config`. It backs up AutoKit's flag files, writes `screenconfig = 800,480,15`, removes `usehwdec` (software decoding) and refuses to leave any `Auto_Box_Update.img`. A matching undo job restores them | `s2am status` shows the new settings |
| AA-2 | Plug in the Android phone and open AutoKit | Picture fills 800×480? All four corners tappable? Photograph it |
| AA-3 | Music, navigation, a call, Google Assistant | Sound through the speakers (patch)? Microphone? |
| AA-4 | A/B with job sticks: 15 vs 30 fps, software vs hardware decoding | Smoothness and flicker |
| AA-fallback | If host settings are not enough: run Carlinkit's Android AutoKit app on the phone with an OTG cable and set the dongle to software decoding at 800×480 | Repeat AA-2 |

## Auto-start: phases

Step AS-5 is the only risky one. Everything before it disappears at the next restart.

| Step | Job / action | Check in the car |
|---|---|---|
| AS-0 (built) | Read-only **snapshot** job (`s2am job snapshot`): `HKLM\Services`, `HKLM\Init`, `HKLM\Drivers\Active`, versions | Report imported; recovery card checked |
| AS-1 (built) | **Logger** (`s2am job logger`), MortScript, started by a job and gone after a restart. Every second for 3 minutes, it writes `Drivers\Active`, AutoKit's window state and its process to the stick while you plug and unplug the phone | Does anything visible change when the phone, not the dongle, connects? |
| AS-1b (built) | `s2am job logger --native` (also runs on its own if MortScript sees nothing): a small native logger (CeGCC in Docker) that records AutoKit's `_UIGEAR_BOX_NOTIFY_` messages | A map of state number to meaning |
| AS-2a | **Diagnose the freeze** with the logger (`s2am job logger`): insert, open AutoKit, tap Exit, wait, soft reset, import. The log shows whether `AutoKit.exe` hangs on exit or exits while SYNC never takes the screen back | One log, before and after Exit |
| AS-2 (built) | **Fix the freeze**: `s2am job runner-guard` puts our CeGCC guard (`s2am/native/s2amrun.c`) in SyncAppsRunner.exe's place. Ford's runner is kept as `.orig.exe` and started by the guard. The guard closes an app that hid itself while SYNC stays hidden, and shows SYNC with the runner's own steps if needed. Self-test before the swap; `--off` undoes it | Leaving AutoKit returns to SYNC (P1 tests T8/T9); `s2am status` shows the guard log |
| AS-3 | **Trial watcher** (gone after a restart): keeps AutoKit loaded but hidden, brings it forward on phone connect, gives SYNC back on unplug. It handles fast replugging and refuses double launches | Plug in = CarPlay; unplug = SYNC, ten times in a row |
| AS-4 | Rollback rehearsal: undo AS-2 and AS-3 and confirm the Phase 1 state | `s2am diff` shows the baseline |
| AS-5 | **Start from boot** as a CE service registered like UPDATESVC. It waits 60 s first and does nothing if `\USB Disk\NOAUTOSTART` exists | Cold starts with and without phone and dongle |

**Before AS-5:** a broken boot entry might prevent SYNC from ever reaching UpdateService, and
then no job stick can repair it. The recovery is the NOAUTOSTART stick and, failing that, the
3.10 recovery stick from the P1 runbook. AS-5 needs its own Codex review and an explicit
go-ahead from you.

**Native code (set up):** ENLYZE's CeGCC 9.3.0 image (`ghcr.io/enlyze/windows-ce-build-environment-arm`,
MIT), pinned by digest. `s2am native build` compiles `s2am/native/*.c` and checks each binary:
ARM machine type, Windows CE GUI subsystem, and COREDLL.dll as the only import. The first
car proof is `s2am job native-hello`.

## Risks, ranked

1. **Boot start (AS-5):** a failure there cannot be undone with a stick. Mitigations: delay,
   NOAUTOSTART, the recovery stick, and doing it last.
2. **Seeing the phone:** if AutoKit's notifications don't reveal a phone session, auto-start
   falls back to "AutoKit always loaded but hidden".
3. **Touch and focus after AutoKit exits:** JasonACT's runner, and Power+Seek-Up.
4. **AA picture and smoothness:** software decoding on a 600 MHz CPU may be choppy.
5. **Microphone for Assistant and calls:** unproven on SYNC 2.
6. **Dongle firmware:** never flash; s2am refuses the file.
7. **Phone too old:** Android 11+ is required.

## What we need from you

- ~~Android version~~: Samsung S24, Android 16, fine for Android Auto.
- For AS-2: JasonACT's runner is an XDA attachment (page 87 of the MyFord Touch hack thread),
  and downloading it may need an XDA account.
