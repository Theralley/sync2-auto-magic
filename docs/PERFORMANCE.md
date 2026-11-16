# Performance: SYNC 2 and CarPlay are very slow

**Open issue, reported 2026-11-04 after the first run of CarPlay.** CarPlay works, but the whole
system is so slow that it is hard to use:

- taps in CarPlay react late;
- CarPlay's picture is choppy and delayed;
- Ford's own screens are slow too.

**Measured 2026-11-14 with CarPlay running: the processor is full.** It was at 100% in 82 of 88
samples while CarPlay ran. The details are in [P1-TESTLOG.md](P1-TESTLOG.md), 2026-11-14.

## Next useful tests, November 16

The [development update](PROGRESS-2026-11-16.md) brings the decoder, priority and clock tracks
up to date. The immediate next step is **identify the decoder actually installed**, followed by
separate decoder and scheduling comparisons at the existing **640×384/10/software** setting.

The first native inspection completed in the car and found stock active DLLs, stock backups
and correctly staged candidate DLLs. The revised decoder installation then returned without
its report again. The same Maps/Spotify test worked, but the owner noticed no improvement.
Neither the installer success message nor that subjective result proves which DLLs are active.

Independent source and exact-binary analysis confirmed a reporting defect: MortScript's
`DelTree` can remove the empty parent report folder when a requested child does not exist.
Cleanup now checks child existence and recreates the report directory. A fresh
[read-only native inspection](DECODER-INSPECTION.md) targets the latest installation. It does
not repeat the swap or apply a priority/frequency change. The matching decoder undo remains
available. Current prepared test packages expire **November 17, 10:35 Swedish time**; rewriting
the sticks does not extend that window.

### Verify the custom decoder

The non-NEON candidate uses about 20% fewer emulated instructions on the existing test material
with matching pictures. That is not a measured CarPlay speed improvement. After active files
are identified and the install/report path is verified, compare original and candidate:

1. Restart SYNC, warm up for two minutes, then use the same phone, adapter and Maps/Spotify
   sequence for 5–8 minutes. Keep resolution, frame rate, software decoding and priority fixed.
2. Verify the candidate DLLs after installation, then repeat the same restart, warm-up and
   workload. Record picture lag, repeated tap response and audio interruptions.
3. Check picture, sound, exit/reopening and access to Ford's screens. Existing microphone and
   parking-popup failures remain baseline issues. If the candidate regresses, use its matching undo.

The decoder package does not itself start a load logger. Use matched load recordings for a
quantitative comparison. CPU sampling does not measure frame rate or tap latency; film repeated
interactions for those. Test 800×480 separately if a repeatable benefit is established.

### Compare foreground priority

The existing 640×384 trace puts the busiest AutoKit thread at priority 252, with about 36% CPU
on average. The main Desktop thread used about 17% at priority 250, sometimes 248. The next
comparison targets **250**, rather than the previously proposed 251, using the foreground guard.

`runner-guard --boost 250 --measure 600` can request a ten-minute load recording. Compare it
with boost disabled under the same decoder/settings/workload. Check the guard log for both
raising and restoring priority when AutoKit loses the foreground; `--boost off` disables the
boost. Ford's required processes remain running. No car result for this comparison exists yet.

The sampler runs below normal priority and may be delayed by boosted runnable work. Check
actual timestamps and missing intervals before comparing CPU samples; the intended ten-second
cadence is not guaranteed. More CPU share does not by itself prove better responsiveness.

### NEON and clock work

NEON needs a separate instruction/context-switch probe before a NEON decoder trial.
NXP documents [NEON multimedia support for i.MX51](https://www.nxp.com/docs/en/supporting-information/ANDROID.pdf),
and the [candidate's D0–D31 context routines](CLOCK-FIRMWARE-ANALYSIS-2026-11-16.md#neon-follow-up-evidence)
provide a basis for the probe. Neither establishes live Ford compatibility or AutoKit detection.

The hardware-decoder flag and 800×480/10 have already been tried without a CPU-load improvement.
The standalone clock reader failed at mapping with error 87. A separate temporary read-only
clock-driver prototype has passed host tests and a server build; it still needs review and car
validation. No installable CPU-frequency trial is available. See the
[clock research goal](PROGRESS-2026-11-16.md#goal-3-a-controlled-overclock-experiment).

## What we know

| Fact | Source |
|---|---|
| Windows CE 6.0 on a Freescale i.MX51, a single-core chip, with 483 MB of memory | Drive log, 2026-10-31 |
| Ford's screens run in `Desktop.exe`, on Adobe Flash Lite (`\Windows\flashlite.dll`) | The same log's file list |
| `Desktop.exe` used a steady **53%** of the processor for six minutes | The same log, before any of our screen changes. What the screen showed was not noted |
| The kernel used another 8%. The logger itself used 14%, and is a cost we can avoid | The same log |
| Most screen files run at 15 frames per second, none set a rendering quality | Read from the car's own files |
| AutoKit decodes CarPlay's picture in software: 800x480 at 15 frames per second | `s2am status` |
| **With CarPlay running, the processor is at 100%.** AutoKit takes about 58%, the kernel 19%, `Desktop.exe` 16% | Load log, 2026-11-14, 88 samples |
| Most of AutoKit's share is one thread, probably the video decoding, at priority 252. `Desktop.exe`'s main thread runs at 250, above it | The same log |
| `Desktop.exe` drops to about 12% behind CarPlay. With AutoKit in front but CarPlay stopped, it ran at about 60% for ten minutes | The same log |
| AutoKit's log says `IsHaveNeon() = 0`, although the i.MX51's Cortex-A8 core has NEON | AutoKit's log, 2026-11-14 |
| The car has Freescale's hardware video decoder files (`vpu.dll`, `mx51_vpu_dec_*.dll`) | The car's file list, 2026-10-31 |
| Memory is not short: 141-183 MB free | Load log, 2026-11-14 |
| **The processor runs at 600 MHz.** The kernel states it, and timing loops measured 599-600 MHz | Load log, 2026-11-15, four samples on Ford's Home |
| Windows CE reports neither NEON nor VFP3. CE 6.0 may have no flag for them, so this is not proof about the chip | The same log |
| **`usehwdec` (hardware decoding) changes nothing:** 99% in total, AutoKit 58%, the same one thread | Load log, 2026-11-15, 50 samples with CarPlay |
| Freescale's power-chip library does not load into an ordinary program (error 193) | The same log |
| 10 frames per second instead of 15: the same 99% and 58% | Load log, 2026-11-15, 28 samples |
| **AutoKit's 58% is what is left over, not what decoding costs:** its decoding thread has the lowest priority (252) and the processor is full whatever the setting | The three runs at 800x480 |
| **A smaller picture helps: at 640x384 the processor is below 95% in 14 of 34 samples**, AutoKit 42%. AutoKit does not stretch it: black frame around | Load log, 2026-11-15, `akcfg-9ccd` |

**The picture.** CarPlay alone fills the one processor core. Decoding the video in software
takes the biggest share, and every tap and frame waits in the queue behind it. Ford's screens
take only about 12% while CarPlay runs, so making them lighter would help CarPlay little. Making
the decoding cheaper would help a lot.

## What we don't know

1. ~~How much AutoKit uses, and whether `Desktop.exe` keeps its 53% behind it.~~ Answered
   2026-11-14: AutoKit about 58%, and `Desktop.exe` drops to about 12%.
2. Whether version 2 of the screens ([sync-redesign](https://github.com/Theralley/sync-redesign))
   is slower or quicker than Ford's. The only number is from before any change.
3. What inside `Desktop.exe` takes the time.
4. Whether AutoKit's hardware decoding works at all on this chip.
5. How hot the processor gets, its active core voltage, and how the memory clock is sourced.
   The processor clock was measured at 600 MHz in the car on 2026-11-15; temperature is unmeasured.
6. Why AutoKit finds no NEON, and whether it would be quicker if it did.
7. What `Desktop.exe` does at 60% while it is hidden.

## Plan: measure first, then one change per visit

**Step 1: measure.** Done 2026-11-14 (the numbers above). `s2am job logger --load` records for 30 minutes: the processor's load per
program every 10 s, and the busiest threads with their priorities. It copies no files and no
screens, so it adds next to nothing itself. It writes only its own logs, in s2am's folder on the
car, so the stick can leave and the adapter can take its USB port. `s2am job logger --collect
<that job>` on a second stick fetches the logs. `s2am job autokit-config --measure` does both
with one stick: it starts the same recording after its change, and fetches the logs when the
stick is inserted a second time.

Parked with the engine running:

1. Insert the first stick **before AutoKit is opened**, so its report also brings AutoKit's log of
   the last CarPlay run. Wait for "Install successfully completed" and pull it.
2. Put the adapter in the same port. SYNC does not restart, and the logger is running.
3. Do the steps below, in order.
4. Pull the adapter, insert the second stick, wait for "Install successfully completed", pull it.

| Minutes | Do | Answers |
|---|---|---|
| 3 | Home, touch nothing | What version 2 costs at rest, against the 53% above |
| 2 | Tap through climate, radio and the menus | What Ford's screens cost in use |
| 3 | The map, touch nothing | What the map adds |
| 2 | AutoKit open, phone not connected | What AutoKit costs alone |
| 3 | CarPlay's home screen, touch nothing | Whether `Desktop.exe` keeps working behind it |
| 5 | CarPlay: Maps with a route, Spotify playing, scroll the map | The worst case, and which threads fight |
| 2 | Exit, then Home | Whether everything goes back to normal |

**Step 2: try the levers, one per visit,** each with its own undo stick. The current order is
given above; this table also preserves the already tested options:

| Lever | What changes | How | Risk |
|---|---|---|---|
| Hardware decoding | The video leaves the processor. The decoding is the biggest single cost, and the chip has a hardware decoder | `autokit-config --decoder hardware` (exists). **Tried in the car 2026-11-15: no effect on the load** (`akcfg-9b10`, measured with `akcfg-f021`; undo `akcfg-da1b`) | Its code path was made for other chips, so the picture may go black. `--restore` undoes it |
| Frame rate | Requests 10 frames per second instead of 15 | `autokit-config --screen 800,480,10`. **Tried November 15: no measured CPU-load improvement**; actual frame admission/queueing was not measured | Some audio interruptions were observed; no proven decoding-cost reduction |
| NEON | AutoKit's faster path, if its check is what holds it back | Not known yet: first find out how AutoKit checks | Unknown |
| AutoKit's priority | AutoKit's video (252) runs at 251 or 250 while CarPlay is alone on the screen: 251 is still below `Desktop.exe` (250), 250 shares with it. Never above it: a busy video there could keep Ford's screens from ever coming up, and their coming up is what ends the boost. Back to 252 as soon as SYNC or anything else is on the screen; JasonACT's runner on XDA sets thread priority too | `runner-guard --boost 250 --measure 600` (**next comparison; not tried in the car**); `--boost off` undoes it, `--off` too | Can slow Ford's screens behind it, so it needs testing with calls, climate and the parking sensors. Compare boost off against 250 at the same decoder and resolution |
| A faster decoder build | AutoKit's three decoder files, FFmpeg 2.6.9, built again for this processor, without NEON. In an emulator, AutoKit's own build needs about 1.25 times as many instructions per frame. The picture is identical on the test videos. The decoder files themselves are not in this repository yet | `s2am job decoder --from FOLDER` (**installation attempted; latest active DLL identity and performance unverified**). AutoKit must be closed: restart SYNC and insert the stick before opening AutoKit. Build the undo stick at the same time | AutoKit does not start, or crashes. `s2am job decoder --restore JOB` undoes it. If a run is cut short, AutoKit may not start until the undo stick has run |
| Flash quality | Ford's screens drawn at a lower quality setting, which may cost less to draw | New, a small patch in the frame | Rougher text. Whether Ford's player honours the setting is not known |
| Lighter screens | Fewer and simpler things to draw | sync-redesign, plan step S7 | Slow work, screen by screen |

## A possible lever: a faster processor clock (overclocking)

**Proposed 2026-11-14 by the car's owner, who accepts the risk. The measuring is built. No change
to the clock has been built or tried.**
The [clock-method investigation](CLOCK-METHOD.md) now includes a compiled `s2am job pmic`
diagnostic for voltage presets through the existing driver, plus the evidence needed to
distinguish an existing operating-point selector from missing platform support. Both readers
completed in the car on November 16: SW1 presets are 1050/1050/700 mV, and 104/116 active
driver references resolve. No CPU-frequency selector was discovered; see the
[capture findings](CLOCK-CAPTURE-2026-11-16.md).
The [datasheet comparison](CLOCK-METHOD.md#datasheet-comparison-for-a-small-experiment)
considers 620–630 MHz as a hypothetical small experiment: +3.3–5.0% ideal CPU capacity.
It establishes no usable setting or voltage margin; the PMIC's ±50 mV output tolerance means
the 1.05 V preset alone cannot demonstrate extra margin over the automotive 1.00 V nominal.
More clock speed helps everything at once: Ford's screens, AutoKit's decoding, the taps. It is
also the only lever here that can damage the hardware, so it comes last, after the cheaper levers
above and after the groundwork below.

**What the logger records.** Since 2026-11-14 the load logger also writes, every 10 s, a `clock`
line, and at its start what the processor says about itself. First run in the car 2026-11-15: **600 MHz, stated and measured**; the power chip was not read, so the core voltage is still unknown:

| What | How | How good |
|---|---|---|
| The clock speed | Two timing loops that differ by 32 one-cycle steps a round; the time between them gives the clock | A few percent. It shows 600 against 800 MHz, and whether the clock changes with load |
| The core voltage | The normal setting of the MC13892 power chip's output SW1, read through Freescale's own library on the car (`pmicSdk_mc13892.dll`) | The value the chip is set to, not a measurement of the rail. The chip has two more settings for the same output, and which one is in use is not known |
| What the processor is | The system's own answer (`IOCTL_PROCESSOR_INFORMATION`) and its feature bits, NEON among them | As good as Ford's system fills it in |
| The power chip's set-up | Its switcher and regulator registers and how its measuring is set up, read once. Never its measuring results: reading those moves the chip on under Ford's driver | Raw values, for planning |

**No temperature yet.** The i.MX51 has no temperature sensor of its own. The power chip can
measure its own temperature, but taking that reading means changing how the chip's measuring is
set up, and Ford's software may be using it. The logger reads that set-up first. A probe taped
to the box would say more about the processor than the power chip's temperature does.

**What changing the clock takes** (checked with Codex against Freescale's documents, 2026-11-14;
the register values are from the documents, not yet read from this car):

- The processor's clock comes from the chip's first clock generator (PLL1, at `0x83F80000`),
  through the clock controller (CCM, at `0x73FD4000`). Direct register access needs a suitable
  privileged platform interface. Whether Ford exposes one, or accepts a driver of ours, is
  not established by the registry capture.
- **The memory's clock may come from the same generator** (the clock controller's `CBCDR`
  register, bit 30). If it does, changing PLL1 changes the memory's clock too, and SYNC stops at
  once. This has to be read before anything is changed.
- The change needs a verified platform transition, including clock-source switching and any
  rail coordination. Consumer-grade parts specify 1.10 V nominal (1.05–1.15 V) through 800 MHz;
  automotive and industrial parts specify 1.00 V nominal (0.95–1.10 V) through 600 MHz.
  The fitted grade remains unidentified. These rows do not supply an overclock voltage curve.
- Ford's power policy may overwrite a requested clock, and PMIC settings can persist through
  sleep. The actual reset/suspend behavior and restoration of the full clock/rail baseline
  must be established for the deployed implementation.

**Earlier November 14 investigation sequence** (the current implementation and trial decision
are governed by [CLOCK-METHOD.md](CLOCK-METHOD.md) and [CLOCK-OUTCOMES.md](CLOCK-OUTCOMES.md)):

1. **Baseline, with nothing changed.** The clock, the voltage and the processor's own answer,
   next to the hardware-decoding test. Stop if the power chip cannot be read.
2. **The car's own start-up settings and system files, copied read-only** (planned 2026-11-15:
   `s2am job registry --root 'HKLM\Drivers' --fetch '\Windows\boot.rgu' ...`). They show which
   drivers handle the clock and the power chip, and whether Freescale's own speed-step driver
   is there. Nothing from Ford is needed: it is all on the car.
   **Done in the car 2026-11-15** (job `reg-c6e2`, the start-up registry files).
   **Evidence audit:** the registry reports 676 keys, 2,614 values and 137 withheld values.
   There are **116 active-device entries: 106 named and 10 unnamed**, not 107 running drivers.
   Every active device's `Key` reference was withheld by the exporter's generic credential
   filter. A complete traversal therefore did not give a complete map to driver definitions.
   No explicit DVFC/speed-step driver or CPU frequency selector was found in the captured text.
   `CPM0:` matches CriticalProcessMonitor (`CritProcMonDrv.dll`); `PMI1:` matches the MC13892
   PMIC driver (`pmicpdk_mc13892.dll`). These identities do not enumerate their interfaces.
   `cspddk.dll` is configured at boot with order 0 and flags `0x1000` (`DEVFLAGS_BOOTPHASE_1`);
   this does not establish which clock operations Ford's build exposes.
   Six of 21 requested files copied (registry files and `ceconfig.h`). Fifteen program files
   are absent from the report. The fetch script records neither source attributes nor copy
   errors and skips a failed `FileExists` check, so ROM-module copy restrictions are a plausible
   explanation, **not a verified cause**. This capture does not prove that custom kernel code
   is the only possible clock-control route.

   **November 16 follow-up:** the corrected exporter ran in the car and recovered 104 active
   references; 12 remain withheld. No explicit CPU selector or frequency table was found.
   **Next evidence:** resolve the remaining identities and inspect exact clock/power module
   implementations, especially CSPDDK and AutoPM. Add per-file attributes and error reporting
   before drawing conclusions from missing binaries.
   Freescale's [i.MX51 CE 6.0 BSP reference manual, chapters 7 and 9](https://community.nxp.com/pwmxy87654/attachments/pwmxy87654/imx-processors/9897/1/481-WCE600_MX51_ER_1104_ReferenceManual.pdf)
   describes CSPDDK clock services and a `dvfc_mc13892.dll` driver with `DVF1:`/`DVF2:` power
   interfaces. Those are reference-BSP facilities, **not confirmed Ford interfaces**. No calls
   to them have been made. Core voltage and the CPU/memory clock relationship remain unknown.
3. **A read-only driver.** It only reads the clock controller and PLL1, and shows whether our
   code can run in the kernel at all. Stop if the memory's clock hangs on PLL1.
4. **A rehearsal with the stock values.** Go through the whole change and back, ending at the
   same clock. Stop on any difference.
5. **About 5% up, for a few minutes,** parked, with as little writing to storage as possible, and
   back down before SYNC sleeps. Stop on any fault, or if nothing gets quicker.

The baseline is 600 MHz. Another i.MX51 variant's 800 MHz rating does not qualify this car's
part for that frequency. Any proposed target needs the actual part's rating and measured
clock, voltage and thermal conditions; the current evidence does not establish a usable target.

**Rules if it is ever tried:**

- **Never at start-up.** A future experiment must avoid persistent boot changes. Restoration
  after reset still requires evidence for the complete clock/rail state; a restart is not a
  demonstrated recovery guarantee. An undo stick requires functioning USB/update services.
- **Watch the temperature the whole time,** and drop back on the first sign of trouble.
- **The test drive is long, in summer heat as well as now.** The box sits behind the dashboard.

**The risk:**

- **Freezes and crashes.** The screen carries climate, calls and the parking-sensor pop-up, and
  a frozen SYNC takes them all with it until it restarts.
- **Damaged storage.** Files written while the processor is unstable can come out corrupt. If
  that hits SYNC's own system files, SYNC may stop starting at all, and then it needs a
  workshop.
- **Heat.** Extra clock and voltage mean extra heat. That can shorten the box's life, or trip
  Ford's own protection, if there is any.

**What must keep working:** calls, climate with MAX DEFROST, and the parking sensors. A change that
makes CarPlay quicker but delays any of them does not ship.
