# Performance: SYNC 2 and CarPlay are very slow

**Open issue, reported 2026-11-04 after the first run of CarPlay.** CarPlay works, but the whole
system is so slow that it is hard to use:

- taps in CarPlay react late;
- CarPlay's picture is choppy and delayed;
- Ford's own screens are slow too.

Nothing has been measured with CarPlay running yet. The causes below are what the earlier logs
point to, not proof.

## What we know

| Fact | Source |
|---|---|
| Windows CE 6.0 on a Freescale i.MX51, a single-core chip, with 483 MB of memory | Drive log, 2026-10-31 |
| Ford's screens run in `Desktop.exe`, on Adobe Flash Lite (`\Windows\flashlite.dll`) | The same log's file list |
| `Desktop.exe` used a steady **53%** of the processor for six minutes | The same log, before any of our screen changes. What the screen showed was not noted |
| The kernel used another 8%. The logger itself used 14%, and is a cost we can avoid | The same log |
| Most screen files run at 15 frames per second, none set a rendering quality | Read from the car's own files |
| AutoKit decodes CarPlay's picture in software: 800x480 at 15 frames per second | `s2am status` |

**The likely picture.** Ford's screens already take over half of the one processor core, and
AutoKit has to decode video on what is left. If `Desktop.exe` keeps working while AutoKit covers
it, the two fight for the same core, and every tap waits behind both.

## What we don't know

1. How much AutoKit uses, and whether `Desktop.exe` keeps its 53% behind it.
2. Whether version 2 of the screens ([sync-redesign](https://github.com/Theralley/sync-redesign))
   is slower or quicker than Ford's. The only number is from before any change.
3. What inside `Desktop.exe` takes the time.
4. Whether AutoKit's hardware decoding works at all on this chip.

## Plan: measure first, then one change per visit

**Step 1: measure.** `s2am job logger --load` records for 30 minutes: the processor's load per
program every 10 s, and the busiest threads with their priorities. It copies no files and no
screens, so it adds next to nothing itself. It only reads from the car.

Parked with the engine running. The stick goes in its usual USB port **before AutoKit is opened**,
so its report also brings AutoKit's log of the last CarPlay run, and it stays in until the end. The
adapter stays in the other port. Then, in this order:

| Minutes | Do | Answers |
|---|---|---|
| 3 | Home, touch nothing | What version 2 costs at rest, against the 53% above |
| 2 | Tap through climate, radio and the menus | What Ford's screens cost in use |
| 3 | The map, touch nothing | What the map adds |
| 2 | AutoKit open, phone not connected | What AutoKit costs alone |
| 3 | CarPlay's home screen, touch nothing | Whether `Desktop.exe` keeps working behind it |
| 5 | CarPlay: Maps with a route, Spotify playing, scroll the map | The worst case, and which threads fight |
| 2 | Exit, then Home | Whether everything goes back to normal |

**Step 2: try the levers, one per visit,** each with its own undo stick:

| Lever | What changes | How | Risk |
|---|---|---|---|
| Frame rate | 10 frames per second instead of 15, so that frames don't queue up | `autokit-config --screen 800,480,10` (exists) | A less smooth picture |
| Hardware decoding | The video leaves the processor | `autokit-config --decoder hardware` (exists) | Its code path was made for other chips, so the picture may go black. `--restore` undoes it |
| AutoKit's priority | AutoKit's video runs ahead of `Desktop.exe` while it is on the screen; JasonACT's runner on XDA sets thread priority too | New, in the runner guard | Can starve SYNC behind it, so it needs testing with calls and climate |
| Flash quality | Ford's screens drawn at a lower quality setting, which may cost less to draw | New, a small patch in the frame | Rougher text. Whether Ford's player honours the setting is not known |
| Lighter screens | Fewer and simpler things to draw | sync-redesign, plan step S7 | Slow work, screen by screen |

**What must keep working:** calls, climate with MAX DEFROST, and the parking sensors. A change that
makes CarPlay quicker but delays any of them does not ship.
