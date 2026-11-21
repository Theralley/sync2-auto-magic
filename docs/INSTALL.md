# Install guide: CarPlay on your SYNC 2, step by step

*På svenska: [INSTALL.sv.md](INSTALL.sv.md).*

For someone who has never done this before. You do not need to know programming. You need to be
able to install a program on a Mac, double-click a file, answer its questions, and follow steps
in the car.

**Read this first.** This is a pre-release. It works in the developer's car, a 2016 Mondeo, and
CarPlay is slower than in a car that has it built in. The guided installer has been tested on
the Mac, and the very first install through the wallpaper picker is SyncExtPack's own method,
which this project has not yet run in a car itself (the test car already had SyncExtPack). You
change your car's software at your own risk. Nothing here touches the firmware, and reinstalling
SYNC's own software removes everything (see the end of this page).

Set aside an evening: about an hour at the Mac and five to six short visits to the car (one or
two for the install, one for each improvement).

## Words used here

| Word | Meaning |
|---|---|
| **SYNC 2** / MyFord Touch | The screen and computer in your dashboard |
| **APIM** | Ford's name for that computer. Its serial number ties an install pack to your car |
| **SyncExtPack** | A community add-on that lets SYNC 2 run extra apps. This project installs it for you |
| **AutoKit** | Carlinkit's app. It shows CarPlay on the screen when the adapter is plugged in |
| **Stick** | Your USB stick. It carries everything between the Mac and the car |
| **Job** | One small task the stick asks the car to do, such as "install this" or "report what you have" |
| **Soft reset** | Restarting SYNC with the power/volume knob and Seek-Up ⏭ held for about ten seconds |

## 1. Check that your car fits

In the car, open *Settings → General → About SYNC*.

- You need **SYNC 2 / MyFord Touch with the 8" touchscreen**. SYNC 3 already has CarPlay; the
  small screen with buttons is a different system.
- The software version must be **3.08 or 3.10**.
- Write down the **APIM serial**, 8 letters and digits. You will type it in later.

## 2. Get the three things

| What | Notes |
|---|---|
| A **Carlinkit wired adapter** of the "AutoKit" type, made for Android head units | For example [this one](https://www.amazon.se/dp/B0919JS1K3). Not a "wired-to-wireless" adapter (2Air, U2W, Mini Ultra, 3.0/4.0/5.0): those only work in cars that already have CarPlay |
| A **USB stick**, 32 GB or smaller | It will be erased if it needs formatting. FAT32, which the installer checks |
| A **Mac** | Linux is implemented and unit-tested, but not yet tried with a real stick on a Linux desktop or in a car: see [On Linux](#on-linux) ([#5](https://github.com/Theralley/sync2-auto-magic/issues/5)). Windows likewise, newer still: see [On Windows](#on-windows) ([#6](https://github.com/Theralley/sync2-auto-magic/issues/6)) |

### Formatting the stick (only if the installer asks)

The stick must be FAT32 with a "Master Boot Record". The installer checks this and never
erases anything itself. If it says the stick is not usable:

1. Open **Disk Utility** (press ⌘-Space and type its name).
2. In its *View* menu choose **Show All Devices**.
3. Select the stick itself, the top line with the maker's name, not the indented line under it.
4. Click **Erase**: name `SYNC`, format **MS-DOS (FAT)**, scheme **Master Boot Record**.

Everything on the stick is deleted. Check twice that you picked the stick and not another disk.

### On Linux

New and not yet tried with a real stick or in a car
([#5](https://github.com/Theralley/sync2-auto-magic/issues/5)). Reports are welcome. You need:

- A desktop that mounts USB sticks by itself under `/media/<you>/` or `/run/media/<you>/`
  (GNOME, KDE, Xfce and most others do).
- Python 3, util-linux 2.35 or newer (`lsblk`, `findmnt`; Ubuntu 22.04, Debian 11, Fedora 32 or
  later) and udisks2 (`udisksctl`).
- [Docker Engine](https://docs.docker.com/engine/install/) with your user in the `docker`
  group, or rootless Docker. Podman has not been tried.
- An x86-64 computer, or an ARM one with x86-64 emulation (Debian and Ubuntu:
  `sudo apt install qemu-user-static binfmt-support`).

The installer only takes a stick on the USB bus, and never a disk that also holds the running
system (swap, `/`, `/boot`, `/home`). To format a stick: open **Disks** (GNOME Disks), select
the stick in the list on the left, choose *Format Disk* in the menu with partitioning
**Compatible with all systems and devices (MBR / DOS)**, then **+** to add one partition over
all of it: name `SYNC`, type **For use with all systems and devices (FAT)**. Open the stick
once in your file manager so it is mounted. Start the installer with `./install-sync2.sh` in a
terminal in the project folder; everything after that is the same as on a Mac.

### On Windows

Newer than Linux, and not yet tried with a real stick or in a car
([#6](https://github.com/Theralley/sync2-auto-magic/issues/6)). Reports are welcome. You need:

- Windows 10 or 11.
- [Python](https://www.python.org/downloads/) 3.9 or newer. In its installer, tick **Add
  python.exe to PATH**.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), started and running. It
  sets up WSL 2 itself if it asks to.
- [Git for Windows](https://git-scm.com/download/win), only if the installer is to download
  SyncExtPack for you.

The installer only takes a drive on the USB bus, and never the disk Windows starts from. Windows
lets only an administrator remount a stick, so the check after writing reads the stick through
Windows' file cache; the installer says so when that happens.

To format a stick: in **This PC**, right-click the stick and choose **Format**: file system
**FAT32**, volume label `SYNC`, **Quick Format**, then **Start**. Format keeps the stick's
partition table. If the check then says the partition scheme is not MBR, open **Command Prompt**
as administrator and run `diskpart`. Then, **after checking the disk number against the stick's
size**: `list disk`, `select disk N`, `clean`, `convert mbr`, `create partition primary`,
`format fs=fat32 quick label=SYNC`, `assign`. Selecting the wrong disk erases it.

Start the installer by double-clicking **`Install-SYNC2.bat`** in the project folder. If Windows
says it protected your PC, choose *More info*, then *Run anyway*. Everything after that is the
same as on a Mac. In the Terminal commands below, `python3` is `py -3` on Windows, and the
stick is its drive letter, such as `E:\`, where they say `/Volumes/SYNC`.

## 3. Prepare the Mac

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it. Wait
   until it says it is running. It builds the install pack in a sealed box, so third-party
   tools never run directly on your Mac.
2. Download this project: on the [project page](https://github.com/Theralley/sync2-auto-magic)
   press the green **Code** button, then **Download ZIP**, and unzip it.
3. Plug in the USB stick.

## 4. Run the guided installer

1. Open the unzipped folder and **double-click `Install-SYNC2.command`**. If macOS refuses,
   right-click it and choose *Open*.
2. Choose **Install CarPlay / Android Auto**.
3. Answer its questions: your APIM serial, which USB stick, and what the *Apps* menu in the car
   shows today. If SyncExtPack is missing on the Mac it offers to download it.
4. It builds the pack, writes it to the stick and checks every file. The first build takes a
   few minutes.
5. Follow what it tells you to do in the car. It is one of two routes:
   - **A car without extra apps (most cars):** two visits. First you pick `Installer.jpg` as a
     wallpaper under *Settings → Display → Wallpaper → Add*, and SYNC restarts. Back at the Mac
     the installer prepares the stick for the second visit, where the install runs by itself.
   - **A car that already has SyncExtPack** (extra apps like Reboot or Video Player): one
     visit. Insert the stick and wait.
6. In the car, always: engine running, Start-Stop off, wait until SYNC has finished starting
   before the stick goes in, and leave the stick in until **"Install successfully completed"**.

**How you know it worked:** *i → Apps* in the car shows **AutoKit**, **Total Commander** and
**Reboot**, and the installer on the Mac says "Done". Type `q` at
any question to stop; nothing is lost.

## 5. First CarPlay

1. Plug the Carlinkit adapter into the car's USB port.
2. Connect your iPhone to the adapter with its cable.
3. Press **i → Apps → AutoKit**. CarPlay appears after a few seconds.

**How you know it worked:** the CarPlay home screen is on the car's display, it reacts to
touch, and music plays through the car's speakers.

Do not leave AutoKit with its Exit button yet: do step 6 first, or the screen can freeze (the
fix for a frozen screen is at the end).

## 6. Make CarPlay better: four improvements

Run the installer again (double-click `Install-SYNC2.command`) and choose
**Make CarPlay better (after the install)**. It offers four changes, asks before each one, and
sends you to the car once per change:

| Change | What you get |
|---|---|
| **The runner guard** | Leaving CarPlay returns to SYNC in a few seconds instead of freezing the screen |
| **A smaller CarPlay picture** | Clearly faster. The picture sits in the middle of the screen with a black frame |
| **The car's microphone** | Siri and phone calls hear you |
| **CarPlay first** | Much smoother CarPlay: it goes before Ford's own screens when the processor is full. Ford's screens, including the parking-sensor and camera pictures, may react more slowly while CarPlay is busy. Tried in one car so far, so the installer only does it if you type `y`. Restart SYNC once more afterwards; it takes effect then |

None of them can run while an app from the Apps menu is open, and AutoKit's Exit button
only hides it. So before each stick goes in, restart SYNC (hold the power/volume knob and
Seek-Up ⏭ together for about ten seconds, and wait until it is back) and do not open AutoKit. The
installer reminds you each time.

**How you know it worked:** in the car you see "Install successfully completed". Back at the
Mac the installer reads the stick and says "Done: ..." for that change. If a change does not
come back as done it stops there and tells you; nothing else is changed.

<details>
<summary><b>Prefer the Terminal? The same jobs as commands</b></summary>

Go to the project folder (type `cd `, drag the folder into the Terminal window, press Return).
Replace `YOURSERIAL` and the stick's name with yours.

```sh
python3 -m s2am job runner-guard --serial YOURSERIAL
python3 -m s2am job autokit-config --screen 640,384,10 --serial YOURSERIAL
python3 -m s2am job autokit-mic-gate --serial YOURSERIAL
python3 -m s2am job flash-tune --prio 253 --fast-prio 253 --serial YOURSERIAL
```

One job per visit to the car, with SYNC restarted and no app opened before the stick goes in.
After each command the tool prints a line starting with `next:`;
run it with your stick's name, go to the car, and import the stick afterwards:

```sh
python3 -m s2am stick prepare /Volumes/SYNC --job build/jobs/<the id it printed>
python3 -m s2am stick import /Volumes/SYNC
```
</details>

### Undo

Each change can be put back with one more stick, from the Terminal in the project folder:

```sh
python3 -m s2am job runner-guard --off --serial YOURSERIAL            # SyncExtPack's own launcher back
python3 -m s2am job autokit-config --restore JOB_ID --serial YOURSERIAL  # the picture as it was
python3 -m s2am job autokit-patched --serial YOURSERIAL               # AutoKit without the microphone change
python3 -m s2am job flash-tune --undo --serial YOURSERIAL             # Ford's screens first again (restart SYNC after)
```

`JOB_ID` is the id the tool printed when it built the picture job. It looks like
`20261120-144720-akcfg-7846`, and the folder `~/.s2am/YOURSERIAL/jobs` has one file per job.

## If something goes wrong

- **Nothing happens when the stick goes in:** SYNC was not ready. Pull it, wait until SYNC has
  fully started, insert it again.
- **The screen is frozen:** switch the car off, open and close the driver's door, then start
  again. Or hold the power/volume knob and Seek-Up ⏭ together for about ten
  seconds. Nothing is uninstalled by either.
- **Anything else:** search [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for the words on the
  screen. Every entry there was met in a real car.
- **Take it all away:** reinstall SYNC software 3.08 or 3.10 with SyncExtPack's
  [firmware guide](https://github.com/chr0m1ng/syncextpack/blob/main/FIRMWARE_INSTALLATION.md).

## What to expect

CarPlay runs, with Maps, music, Siri and calls. It is slower than in a modern car, because
SYNC 2's processor decodes the video in software. With "CarPlay first" the owner of the one car
tested found it much smoother. In calls the other side hears an echo. The
parking sensors' pop-up does not show while AutoKit is open, so leave AutoKit before you
reverse. The current state of all of this is in the [README](../README.md).

If you get it working, or stuck, please
[open an issue](https://github.com/Theralley/sync2-auto-magic/issues) with your model, year and
SYNC version. Reports from other cars are what this project needs most.
