# Performance: SYNC 2 and CarPlay are very slow

**Open issue, reported 2026-11-04 after the first run of CarPlay.** CarPlay works, but the whole
system is so slow that it is hard to use:

- taps in CarPlay react late;
- CarPlay's picture is choppy and delayed;
- Ford's own screens are slow too.

**Measured 2026-11-14 with CarPlay running: the processor is full.** It was at 100% in 82 of 88
samples while CarPlay ran. The details are in [P1-TESTLOG.md](P1-TESTLOG.md), 2026-11-14.

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
5. What clock speed the processor runs at, and how hot it gets. The logger records neither yet.
6. Why AutoKit finds no NEON, and whether it would be quicker if it did.
7. What `Desktop.exe` does at 60% while it is hidden.

## Plan: measure first, then one change per visit

**Step 1: measure.** Done 2026-11-14 (the numbers above). `s2am job logger --load` records for 30 minutes: the processor's load per
program every 10 s, and the busiest threads with their priorities. It copies no files and no
screens, so it adds next to nothing itself. It writes only its own logs, in s2am's folder on the
car, so the stick can leave and the adapter can take its USB port. `s2am job logger --collect
<that job>` on a second stick fetches the logs.

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

**Step 2: try the levers, one per visit,** each with its own undo stick. After the measurement,
the first two are the ones to try first:

| Lever | What changes | How | Risk |
|---|---|---|---|
| Hardware decoding | The video leaves the processor. The decoding is the biggest single cost, and the chip has a hardware decoder | `autokit-config --decoder hardware` (exists). **Sticks built and rehearsed 2026-11-14** (`akcfg-1063`, undo `akcfg-53a1`), not yet run in the car | Its code path was made for other chips, so the picture may go black. `--restore` undoes it |
| Frame rate | 10 frames per second instead of 15: a third less decoding, and frames don't queue up | `autokit-config --screen 800,480,10` (exists) | A less smooth picture |
| NEON | AutoKit's faster path, if its check is what holds it back | Not known yet: first find out how AutoKit checks | Unknown |
| AutoKit's priority | AutoKit's video runs ahead of `Desktop.exe` while it is on the screen; JasonACT's runner on XDA sets thread priority too | New, in the runner guard | Can starve SYNC behind it, so it needs testing with calls and climate |
| Flash quality | Ford's screens drawn at a lower quality setting, which may cost less to draw | New, a small patch in the frame | Rougher text. Whether Ford's player honours the setting is not known |
| Lighter screens | Fewer and simpler things to draw | sync-redesign, plan step S7 | Slow work, screen by screen |

## A possible lever: a faster processor clock (overclocking)

**Proposed 2026-11-14 by the car's owner, who accepts the risk. Nothing has been built or tried.**
More clock speed helps everything at once: Ford's screens, AutoKit's decoding, the taps. It is
also the only lever here that can damage the hardware, so it comes last, after the cheaper levers
above and after the groundwork below.

**What the logger records today:** load per program and thread, memory, and the system's name.
No temperature and no clock speed (checked in `s2am/native/s2amdrive.c`). Nobody knows yet what
clock this processor runs at, or what it is rated for.

**Where a temperature or a clock speed might come from.** The car's own file list (drive log,
2026-10-31) has these candidates. None has been tried:

| Candidate | What it might give |
|---|---|
| `pmicsdk_mc13892.dll`, `pmicpdk_mc13892.dll` | The driver for the MC13892 power chip that feeds the processor. The chip measures voltages and warns when it is hot. Whether this board gives a temperature on one of its channels is not known |
| `syshealth.exe`, `devhealth.exe`, `devhealthdll.dll` | Ford's own health watch, which may read temperatures |
| `sync2ibdccpu.dll` | Ford's diagnostics for the main processor board |
| The kernel's processor information (`KernelIoControl`, `IOCTL_PROCESSOR_INFORMATION`) | The clock speed the system reports about itself. This may be a fixed number, not the live clock |

No file is named like a frequency-scaling driver. If the processor slows itself down to save
power, that happens inside the kernel.

**The groundwork, in this order:**

1. **Measure without changing anything.** A logger that also records the clock speed and any
   temperature it can read, through a whole drive and a long CarPlay session.
2. **Check that it already runs at its rated speed.** If power saving holds it below that,
   running at the rated speed all the time is the safe first win. That is not overclocking.
3. **Only then try small steps above the rated speed,** with a temperature limit that drops
   back to the normal clock on its own.

**How it would be done.** The processor's clock is set in its clock controller, and a higher clock
usually also needs a higher voltage from the power chip. Ordinary programs on Windows CE 6 can't
reach either, so this needs code that runs inside the kernel, such as a small driver. s2am has
no such code yet.

**Rules if it is ever tried:**

- **Never at start-up.** Set the clock only after SYNC is up and running, so that a restart
  always brings back Ford's clock. A clock that hangs SYNC at start-up could not be undone with
  a stick, because SYNC would never get as far as reading one.
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
