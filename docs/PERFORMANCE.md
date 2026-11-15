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
5. What clock speed the processor runs at, and how hot it gets. The logger records the clock
   from 2026-11-14 (not yet run in the car), and no temperature.
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

**Step 2: try the levers, one per visit,** each with its own undo stick. After the measurement,
the first two are the ones to try first:

| Lever | What changes | How | Risk |
|---|---|---|---|
| Hardware decoding | The video leaves the processor. The decoding is the biggest single cost, and the chip has a hardware decoder | `autokit-config --decoder hardware` (exists). **Tried in the car 2026-11-15: no effect on the load** (`akcfg-9b10`, measured with `akcfg-f021`; undo `akcfg-da1b`) | Its code path was made for other chips, so the picture may go black. `--restore` undoes it |
| Frame rate | 10 frames per second instead of 15: a third less decoding, and frames don't queue up | `autokit-config --screen 800,480,10` (exists) | A less smooth picture |
| NEON | AutoKit's faster path, if its check is what holds it back | Not known yet: first find out how AutoKit checks | Unknown |
| AutoKit's priority | AutoKit's video (252) runs at 251 or 250 while CarPlay is alone on the screen: 251 is still below `Desktop.exe` (250), 250 shares with it. Never above it: a busy video there could keep Ford's screens from ever coming up, and their coming up is what ends the boost. Back to 252 as soon as SYNC or anything else is on the screen; JasonACT's runner on XDA sets thread priority too | `runner-guard --boost 251` (written 2026-11-15, **not tried in the car**); `--boost off` undoes it, `--off` too | Can slow Ford's screens behind it, so it needs testing with calls, climate and the parking sensors. Try 251 first, then 250 |
| A faster decoder build | AutoKit's three decoder files, FFmpeg 2.6.9, built again for this processor, without NEON. In an emulator, AutoKit's own build needs about 1.25 times as many instructions per frame. The picture is identical on the test videos. The decoder files themselves are not in this repository yet | `s2am job decoder --from FOLDER` (written 2026-11-15, **not tried in the car**). AutoKit must be closed: restart SYNC and insert the stick before opening AutoKit. Build the undo stick at the same time | AutoKit does not start, or crashes. `s2am job decoder --restore JOB` undoes it. If a run is cut short, AutoKit may not start until the undo stick has run |
| Flash quality | Ford's screens drawn at a lower quality setting, which may cost less to draw | New, a small patch in the frame | Rougher text. Whether Ford's player honours the setting is not known |
| Lighter screens | Fewer and simpler things to draw | sync-redesign, plan step S7 | Slow work, screen by screen |

## A possible lever: a faster processor clock (overclocking)

**Proposed 2026-11-14 by the car's owner, who accepts the risk. The measuring is built. No change
to the clock has been built or tried.**
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
  through the clock controller (CCM, at `0x73FD4000`). Both can only be reached from inside the
  kernel. Whether a driver of ours loads there on SYNC is not known.
- **The memory's clock may come from the same generator** (the clock controller's `CBCDR`
  register, bit 30). If it does, changing PLL1 changes the memory's clock too, and SYNC stops at
  once. This has to be read before anything is changed.
- The change itself: raise the core voltage if needed, move the processor to a second clock
  source, set PLL1, wait until it is steady, move back. The 800 MHz parts of this chip are
  specified at 1.10 V (1.05 to 1.15 V). The car parts are specified for 600 MHz.
- Ford's own power saving may set the clock back, and the power chip keeps its settings while
  SYNC sleeps. So "a restart brings back Ford's clock" holds for the clock, but the voltage must
  be put back by us.

**The order, one visit each:**

1. **Baseline, with nothing changed.** The clock, the voltage and the processor's own answer,
   next to the hardware-decoding test. Stop if the power chip cannot be read.
2. **The car's own start-up settings and system files, copied read-only** (planned 2026-11-15:
   `s2am job registry --root 'HKLM\Drivers' --fetch '\Windows\boot.rgu' ...`). They show which
   drivers handle the clock and the power chip, and whether Freescale's own speed-step driver
   is there. Nothing from Ford is needed: it is all on the car.
3. **A read-only driver.** It only reads the clock controller and PLL1, and shows whether our
   code can run in the kernel at all. Stop if the memory's clock hangs on PLL1.
4. **A rehearsal with the stock values.** Go through the whole change and back, ending at the
   same clock. Stop on any difference.
5. **About 5% up, for a few minutes,** parked, with as little writing to storage as possible, and
   back down before SYNC sleeps. Stop on any fault, or if nothing gets quicker.

If the baseline shows 600 MHz, the first aim is the 800 MHz that the same chip is sold for. If
it shows 800 MHz, anything more is beyond what any version of the chip is specified for.

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
