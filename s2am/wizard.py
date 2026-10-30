"""A guided installer: plain questions, one car trip at a time.

`python3 -m s2am wizard` (or double-click Install-SYNC2.command) walks a non-technical user
through checking the Mac, choosing the USB stick, and every trip to the car. It uses the same
commands as the rest of s2am, so it never does anything the CLI cannot. It never formats a
disk: it explains how to do that in Disk Utility instead.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import apps, bootstrap, cli, container, diskcheck, stick
from .state import Store, home

UPSTREAM_URL = "https://github.com/chr0m1ng/syncextpack"
UPSTREAM_TESTED = "1a1eda0"  # the SyncExtPack commit this project is tested against
PACK_APPS = {"autokit", "total commander", "reboot"}  # what the app pack puts in the menu
SKIP_VOLUMES = {"Macintosh HD", "Recovery", "Preboot", "VM", "Update", "Data"}
SERIAL_HELP = "8 characters, under Settings > General > About SYNC on the car"


class Quit(Exception):
    pass


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


class Wizard:
    def __init__(self, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
                 run: Callable[[list[str]], int] = cli.main, volumes: Path = Path("/Volumes"),
                 info: diskcheck.DiskInfo | None = diskcheck.diskutil_info,
                 upstream: Path = cli.UPSTREAM, any_path: bool = False):
        self.ask, self.say, self.run = ask, say, run
        self.volumes, self.info, self.upstream, self.any_path = volumes, info, upstream, any_path
        self.serial = ""
        self.stick: Path | None = None

    # ---- small helpers -------------------------------------------------------------------

    def prompt(self, question: str) -> str:
        answer = self.ask(question).strip()
        if answer.lower() in ("q", "quit", "exit"):
            raise Quit()
        return answer

    def yes(self, question: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self.prompt(f"{question} [{hint}] ").lower()
            if not answer:
                return default
            if answer in ("y", "yes", "j", "ja"):
                return True
            if answer in ("n", "no", "nej"):
                return False

    def choose(self, question: str, options: list[str]) -> int:
        self.say("")
        self.say(question)
        for number, option in enumerate(options, 1):
            self.say(f"  {number}. {option}")
        while True:
            answer = self.prompt("Type a number and press Enter: ")
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1

    def steps(self, title: str, lines: list[str]) -> None:
        self.say("")
        self.say(f"--- {title} ---")
        for number, line in enumerate(lines, 1):
            self.say(f"  {number}. {line}")

    def cli(self, *argv: str) -> tuple[int, str]:
        """Run an s2am command, showing its output and keeping a copy to read results from."""
        buffer = io.StringIO()
        out = _Tee(sys.stdout, buffer)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.run(list(argv))
        return code, buffer.getvalue()

    def stick_args(self) -> list[str]:
        return ["--any-path"] if self.any_path else []

    # ---- checks before anything else ---------------------------------------------------

    def check_upstream(self) -> None:
        if (self.upstream / "FullPack").is_dir():
            return
        self.say(f"SyncExtPack is not next to this folder (expected {self.upstream}).")
        if not self.yes("Download it now with git (about 300 MB)?"):
            raise Quit()
        subprocess.run(["git", "clone", UPSTREAM_URL, str(self.upstream)], check=True)
        subprocess.run(["git", "-C", str(self.upstream), "checkout", "-q", UPSTREAM_TESTED],
                       check=True)

    def check_docker(self) -> None:
        while True:
            try:
                ok = subprocess.run(container.docker() + ["info"], env=container.docker_env(),
                                    capture_output=True).returncode == 0
            except container.ContainerError:
                ok = False
            if ok:
                return
            self.say("Docker Desktop is not running. Start it (the whale icon in Applications) "
                     "and wait until it says it is running.")
            self.prompt("Press Enter to check again, or type q to quit: ")

    def settings_file(self) -> Path:
        return home() / "wizard.json"

    def ask_serial(self) -> None:
        saved = ""
        try:
            saved = json.loads(self.settings_file().read_text()).get("serial", "")
        except (OSError, ValueError):
            pass
        if saved and self.yes(f"Use the saved car serial {saved}?"):
            self.serial = saved
            return
        while True:
            raw = self.prompt(f"Your APIM serial ({SERIAL_HELP}): ").upper().replace(" ", "")
            serial = raw.replace("O", "0")
            if serial != raw:
                self.say(f"The serial never contains the letter O, so it was read as a zero: {serial}")
            try:
                self.serial = cli._serial(serial)
                break
            except Exception:  # argparse.ArgumentTypeError and friends
                self.say("That does not look right: it must be 8 letters and digits.")
        self.settings_file().parent.mkdir(parents=True, exist_ok=True)
        self.settings_file().write_text(json.dumps({"serial": self.serial}) + "\n")

    def candidate_sticks(self) -> list[tuple[Path, list[diskcheck.Finding]]]:
        found = []
        for volume in sorted(self.volumes.iterdir()) if self.volumes.is_dir() else []:
            if volume.name in SKIP_VOLUMES or volume.is_symlink() or not volume.is_dir():
                continue
            findings = diskcheck.check(volume, self.info)
            if self.info is not None and any("external" in f.message and f.level == "fail"
                                             for f in findings):
                continue  # an internal disk, not a stick
            found.append((volume, findings))
        return found

    def pick_stick(self) -> None:
        while True:
            sticks = self.candidate_sticks()
            good = [v for v, findings in sticks if not diskcheck.failed(findings)]
            for volume, findings in sticks:
                if diskcheck.failed(findings):
                    problems = "; ".join(f.message for f in findings if f.level == "fail")
                    self.say(f"{volume.name}: cannot be used ({problems})")
            if len(good) == 1:
                self.stick = good[0]
                self.say(f"Using the USB stick {self.stick.name}.")
                return
            if good:
                index = self.choose("Which USB stick should be used?", [v.name for v in good])
                self.stick = good[index]
                return
            self.steps("Prepare a USB stick", [
                "Use a USB stick of 32 GB or less. Everything on it will be erased.",
                "Open Disk Utility, choose View > Show All Devices, select the stick itself "
                "(the top line, not the volume).",
                "Click Erase: Name SYNC, Format MS-DOS (FAT), Scheme Master Boot Record.",
                "Leave the stick plugged in."])
            self.prompt("Press Enter when the stick is ready (q to quit): ")

    def stick_back(self, message: str = "Put the stick back in this Mac") -> None:
        while True:
            self.prompt(f"{message}, then press Enter: ")
            if self.stick is not None and self.stick.is_dir():
                return
            self.say("I cannot see the stick yet.")
            if self.candidate_sticks():
                self.pick_stick()
                return

    def clear_updater(self) -> None:
        """Move our own earlier leftovers aside (only known names), so the stick starts clean.

        A job that never ran is withdrawn too, so it cannot run later. Anything else in
        SyncExtPack/ stays, and `bootstrap prepare` then refuses the stick with a message.
        """
        updater = self.stick / "SyncExtPack"
        known = [updater / n for n in stick.UPDATER_FILES if (updater / n).is_file()]
        waiting = sorted((self.stick / "s2am" / "pending").glob("*.json"))
        if not known and not waiting:
            return
        aside = self.stick / "s2am" / "history" / datetime.now(timezone.utc).strftime(
            "%Y%m%d-%H%M%S")
        aside.mkdir(parents=True, exist_ok=True)
        for path in known:
            shutil.move(str(path), str(aside / path.name))
        store = Store()
        for path in waiting:
            shutil.move(str(path), str(aside / path.name))
            try:
                record = store.job(self.serial, path.stem)
                store.save_job(self.serial, path.stem, {**record, "status": "withdrawn"})
            except (OSError, ValueError):
                pass

    # ---- one car trip with a job ------------------------------------------------------------

    def job_trip(self, title: str, job_args: list[str], restarts: bool = False) -> dict | None:
        """Build a job, put it on the stick, send the user to the car, read the report back."""
        self.say(f"\nBuilding the {title} stick. This takes up to a minute (longer the first time).")
        code, output = self.cli("job", *job_args, "--serial", self.serial)
        match = re.search(r"^job (\S+): (.+install\.bin)$", output, re.M)
        if code or not match:
            self.say("Building the stick failed; see the message above.")
            return None
        job_id, workdir = match.group(1), str(Path(match.group(2)).parent)
        code, _ = self.cli("stick", "prepare", str(self.stick), "--job", workdir, *self.stick_args())
        if code:
            self.say("Putting the job on the stick failed; see the message above.")
            return None
        self.steps(f"In the car: {title}", [
            "Start the car and wait until SYNC has fully started.",
            "Insert the USB stick.",
            "Wait for \"Install successfully completed\"."
            + (" SYNC then restarts by itself; wait until it is back." if restarts else ""),
            "Pull the stick out. If nothing happened after 3 minutes, pull it out anyway.",
            "If an error box appears, take a photo of it before you tap OK."])
        self.stick_back()
        self.cli("stick", "import", str(self.stick), *self.stick_args())
        return Store().job(self.serial, job_id)

    def show_status(self) -> None:
        self.cli("status", "--serial", self.serial)

    def latest_menu(self) -> list[str]:
        latest = Store().latest_inventory(self.serial)
        if latest is None:
            return []
        report = Store().report(self.serial, latest[0])
        menu = report / "SyncApps.xml" if report else None
        return [n for n, _, _ in apps.menu_entries(menu.read_bytes()) if n] \
            if menu and menu.is_file() else []

    # ---- the tasks ---------------------------------------------------------------------

    def inventory(self) -> str:
        """"present" (a report came back), "absent" (the stick was not touched) or "unclear"."""
        record = self.job_trip("read what is on SYNC", ["inventory"])
        status = (record or {}).get("status")
        if status in ("applied", "already-applied"):
            self.show_status()
            return "present"
        if status == "pending":  # install.bin is still on the stick: nothing on SYNC read it
            self.say("SYNC did not touch the stick, so it has no SyncExtPack installer yet. "
                     "That is normal before the first install.")
            return "absent"
        self.say("No report came back, but it is not clear why (the job may have stopped with "
                 "an error box). Nothing more is done; see docs/TROUBLESHOOTING.md, or run "
                 "this step again.")
        return "unclear"

    def install(self) -> None:
        seen = self.choose("On the car, press i, then Apps. What is there?", [
            "Only Ford's own items (Install applications/updates, Emergency Assistance)",
            "Extra apps too (for example Reboot, AutoKit, Video Player, MirrorLink, Navitel)",
            "I am not sure"])
        found = "absent" if seen == 0 else self.inventory()
        if found == "unclear":
            return
        if found == "present":
            self.install_apps_only()
        else:
            self.first_install()
        if self.yes("Check the result with one more short car trip (recommended)?"):
            self.inventory()
        self.say("\nDone. Plug the Carlinkit adapter into the car's USB port, connect the phone "
                 "to it, and open i > Apps > AutoKit. If the screen freezes when you leave "
                 "AutoKit, use the soft reset (menu item 4).")

    def install_apps_only(self) -> None:
        menu = self.latest_menu()
        catalog = apps.catalog(self.upstream)
        old = [n for n in menu if n.lower() not in PACK_APPS and n.lower() in catalog]
        if old:
            self.say(f"\nThe Apps menu also has: {', '.join(old)}. Installing replaces the menu "
                     "with AutoKit, Total Commander and Reboot, so these disappear from it.")
            if self.yes("Delete their files too, to free space (one extra car trip)?"):
                self.job_trip("remove old apps", ["remove", *old, "--purge"], restarts=True)
        self.say("\nBuilding the app pack (AutoKit with the sound fix, in English, plus Total "
                 "Commander and Reboot). The first build can take a few minutes.")
        code, _ = self.cli("bootstrap", "prepare", "--serial", self.serial, "--stick",
                           str(self.stick), "--apps-only", *self.stick_args())
        if code:
            self.say("Building the app pack failed; see the message above.")
            raise Quit()
        self.steps("In the car: install the apps", [
            "Start the car and wait until SYNC has fully started.",
            "Insert the USB stick and wait for \"Install successfully completed\".",
            "SYNC restarts. Wait until it is back, then pull the stick.",
            "Press i, then Apps: AutoKit, Total Commander and Reboot should be there."])
        self.stick_back()

    def first_install(self) -> None:
        self.say("\nFirst install. This takes two car trips. Building the install pack first "
                 "(a few minutes the first time).")
        try:
            manifest = bootstrap.build(self.serial, cli.REPO / "build" / "out")
        except bootstrap.BootstrapError as error:
            self.say(f"Building the install pack failed: {error}")
            raise Quit()
        self.clear_updater()  # only after a good build, so a failure leaves the stick as it was
        code, _ = self.cli("bootstrap", "prepare", "--serial", self.serial, "--stick",
                           str(self.stick), "--manifest", str(manifest), *self.stick_args())
        if code:
            self.say("Putting the install pack on the stick failed; see the message above.")
            raise Quit()
        prepared = json.loads((self.stick / bootstrap.RECORD).read_text())
        self.steps("In the car: first trip", [
            "Start the engine (turn Start-Stop off) and wait until SYNC has fully started.",
            "Insert the USB stick.",
            "Go to Settings > Display > Wallpaper > Add, pick the USB stick and select "
            "Installer.jpg. Tap it once and wait.",
            "SYNC shows an installer and restarts. When it is back, pull the stick."])
        self.stick_back()
        try:  # the same stick that was prepared for this car, not another one
            record = json.loads((self.stick / bootstrap.RECORD).read_text())
        except (OSError, ValueError):
            record = {}
        if (record.get("serial"), record.get("pack_install_sha256")) != \
                (prepared["serial"], prepared["pack_install_sha256"]):
            self.say("This is not the stick that was prepared for this car. Put that stick in, "
                     "or start the install again.")
            raise Quit()
        code, _ = self.cli("bootstrap", "finish", str(self.stick), *self.stick_args())
        if code:
            self.say("The rename step failed; see the message above.")
            raise Quit()
        self.steps("In the car: second trip", [
            "Insert the stick again. The installation starts by itself.",
            "Wait for \"Install successfully completed!\". SYNC may restart.",
            "Pull the stick. Press i, then Apps: AutoKit, Total Commander and Reboot should "
            "be there."])
        self.stick_back()

    def remove(self) -> None:
        menu = self.latest_menu()
        if not menu:
            self.say("First I need to see what is on SYNC.")
            if self.inventory() != "present":
                return
            menu = self.latest_menu()
        if not menu:
            self.say("The Apps menu has no apps to remove.")
            return
        self.say("\nApps in the menu:")
        for number, name in enumerate(menu, 1):
            self.say(f"  {number}. {name}")
        picked = self.prompt("Numbers of the apps to remove, separated by commas: ")
        names = [menu[int(n) - 1] for n in re.findall(r"\d+", picked) if 1 <= int(n) <= len(menu)]
        if not names:
            return
        purge = self.yes("Also delete their files (recommended)?")
        args = ["remove", *names] + (["--purge"] if purge else [])
        code, _ = self.cli("job", *args, "--serial", self.serial, "--dry-run")
        if code or not self.yes("Go ahead?"):
            return
        self.job_trip("remove apps", args, restarts=True)

    def help(self) -> None:
        self.steps("SYNC is frozen or acting up", [
            "Park the car.",
            "Hold the power/volume knob and the Seek-Up (next track) button together for "
            "about 10 seconds, until the screen goes black. SYNC restarts; nothing is "
            "uninstalled.",
            "If that does not help: engine off, lock the car, wait 10 minutes.",
            "More answers: docs/TROUBLESHOOTING.md (search for what you see on the screen)."])

    # ---- the main loop ---------------------------------------------------------------------

    def main(self) -> int:
        self.say("sync2-auto-magic: CarPlay and Android Auto for Ford SYNC 2")
        self.say("Answer the questions; type q at any time to stop. Nothing changes in the car "
                 "until you insert a stick there.\n")
        try:
            self.check_upstream()
            self.check_docker()
            self.ask_serial()
            self.pick_stick()
            tasks = [("Install CarPlay / Android Auto (AutoKit)", self.install),
                     ("See what is on my SYNC", self.inventory),
                     ("Remove apps from SYNC", self.remove),
                     ("Help: SYNC is frozen", self.help),
                     ("Quit", None)]
            while True:
                index = self.choose("What do you want to do?", [t[0] for t in tasks])
                if tasks[index][1] is None:
                    return 0
                tasks[index][1]()
        except (Quit, EOFError, KeyboardInterrupt):
            self.say("\nStopped. Run it again any time; nothing is lost.")
            return 0
        except Exception as error:  # a normal user should get a sentence, not a traceback
            self.say(f"\nSomething went wrong: {error}")
            self.say("Nothing changes in the car unless a stick goes in. Run it again, or report "
                     "this at https://github.com/Theralley/sync2-auto-magic/issues")
            return 1


def main(argv: list[str] | None = None) -> int:
    return Wizard().main()
