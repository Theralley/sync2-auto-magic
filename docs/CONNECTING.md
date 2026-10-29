# Connecting the Mac to SYNC 2

There is **no data cable from the Mac to SYNC 2's USB port**. The Mac reaches SYNC 2 in two
ways: a **USB stick** for anything to do with files and apps, and the **OBD-II port** for
diagnostics.

| Link | Carries | Use it for | Status |
|---|---|---|---|
| **USB stick** (FAT32, MBR, 32 GB or less) | files, `s2am` jobs, reports | install, remove, configure, inventory, logs | ✅ the main path |
| **OBD-II port** + USB OBD adapter + [forscan-mac](https://github.com/Theralley/forscan-mac) | CAN diagnostics with the SYNC module (APIM) | software and part numbers, error codes, As-Built backup, **restarting SYNC** | optional, read-only |
| Wi-Fi (SYNC's own hotspot) | nothing: SYNC 2 has no service listening | a future Wi-Fi agent (TOOLKIT-PLAN P5) | not available |
| USB cable from the Mac to SYNC's USB port | — | — | ❌ **never** |

## Why not a USB cable to SYNC's USB port

- **Both sides are USB hosts.** SYNC 2's USB ports are host-only and sit behind an ordinary hub.
  They have no device mode (no ActiveSync), so a computer plugged in has nothing to talk to. The
  same limitation is why CarPlay needs a dongle or a role-switch hub.
- **USB-A to USB-A cables are dangerous.** They join two 5 V supplies and can damage the Mac's
  port or SYNC's. Do not use one.

## The USB stick (everyday)

```sh
python3 -m s2am stick check /Volumes/SYNC      # FAT32, MBR, 32 GB or less, nothing waiting to run
python3 -m s2am stick prepare /Volumes/SYNC --job build/jobs/<id>
#   car: insert, wait for "Install successfully completed", pull it out
python3 -m s2am stick import /Volumes/SYNC
```

The car's resident UpdateService runs the job and writes the report back onto the stick. One
round trip takes a few minutes.

## The OBD-II port (diagnostics and restart)

- **Where:** under the dashboard on the driver's side, near the steering column.
- **Adapter:** a USB OBD adapter that FORScan supports. On most Fords SYNC sits on the slower
  **MS-CAN** bus, so the adapter has to reach it: an OBDLink EX, or an ELM327 with an
  HS/MS-CAN switch. Plain ELM327 clones often see only HS-CAN.
- **Software:** your [forscan-mac](https://github.com/Theralley/forscan-mac). FORScan runs
  in Docker with wine, the window opens in the browser, and a `socat` bridge carries the
  adapter's serial port into the container.
- **What it gives you:**
  - the APIM's software and part numbers;
  - its error codes;
  - an **As-Built backup** (export it once, and keep it);
  - a **module reset**, which restarts SYNC 2 from the Mac. That is useful when the touchscreen
    freezes after AutoKit.
- **Read-only.** forscan-mac's own README warns against writing As-Built or programming modules
  over its emulated chain, so do that only with FORScan on a real Windows PC.
- OBD cannot see or change apps or files on SYNC; that is what the USB stick is for.

## Possible later: a "live stick" (not built)

A Raspberry Pi Zero 2 W in USB gadget mode can pretend to be a USB stick in SYNC's port while
the Mac drives it over Wi-Fi:

1. The Mac drops a job onto the Pi.
2. The Pi re-presents the drive, so SYNC sees a stick being inserted.
3. UpdateService runs the job, and the Pi passes the report back to the Mac.

That would make a test loop without walking to the car. It is an extra piece of hardware,
so it is only an idea for now.
