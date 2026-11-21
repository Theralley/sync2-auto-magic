"""Tests for the guided installer: scripted answers, a stand-in for the CLI and the car."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import apps, wizard  # noqa: E402
from s2am.state import Store  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "FullPack").is_dir()
SERIAL = "XV31M13H"


class FakeCli:
    """Records every s2am command; plays the car's side when a stick is imported."""

    def __init__(self, tmp: Path, inventory="applied", menu=("Video Player", "Reboot"), ejects=None):
        self.tmp, self.inventory, self.menu = tmp, inventory, list(menu)
        self.ejects = ejects  # where a command that ejects moves the stick to, as if pulled
        self.calls, self.jobs = [], []
        self.fail = None  # a job kind whose stick comes back untouched
        self.unverified = None  # a job kind that ran to its end, but whose check of the car failed

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[0] == "job" and "--dry-run" not in argv:
            job_id = f"20261030-0000{len(self.jobs):02d}-{argv[1][:3]}-abcd"
            self.jobs.append((job_id, argv[1]))
            print(f"job {job_id}: {self.tmp}/jobs/{job_id}/install.bin")
        elif argv[:2] == ["stick", "import"]:
            job_id, kind = self.jobs[-1]
            store = Store()
            status = self.inventory if kind == "inventory" else "pending" if kind == self.fail else "applied"
            applied = status == "applied"
            if applied:
                report = self.tmp / "report"
                shutil.rmtree(report, ignore_errors=True)
                report.mkdir()
                (report / "inventory.txt").write_text("D|\\SyncExtendedPack\\Apps\\Nav\r\n")
                (report / "SyncApps.xml").write_bytes(apps.render_menu(
                    [(n, n.replace(" ", "") + "Plugin", "") for n in self.menu]))
                store.save_report(SERIAL, job_id, report)
            short = {"runner-guard": "guard", "autokit-mic-gate": "akmic", "flash-tune": "flash"}.get(kind, kind)
            check = {"check": {"ok": kind != self.unverified, "text": "x"}} if short in wizard.CHECKED else {}
            store.save_job(SERIAL, job_id, {"id": job_id, "serial": SERIAL, "kind": short, **check,
                                            "status": status,
                                            "imported_utc": f"2026-10-30T00:00:{len(self.jobs):02d}"})
            print(f"{job_id}: {status}")
        elif argv[:2] == ["bootstrap", "prepare"] and "--apps-only" not in argv:
            record = Path(argv[argv.index("--stick") + 1]) / "s2am" / "bootstrap.json"
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps({"serial": argv[argv.index("--serial") + 1],
                                          "pack_install_sha256": "a" * 64}))
        if self.ejects is not None and argv[0] in ("bootstrap", "stick") and \
                not {"--any-path", "--no-eject"} & set(argv):
            stick_path = Path(argv[argv.index("--stick") + 1] if "--stick" in argv else argv[2])
            shutil.move(str(stick_path), str(self.ejects))
        return 0

    def commands(self):
        return [" ".join(c[:2]) for c in self.calls]


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Conversation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        no_docker = mock.patch.object(wizard.Wizard, "check_docker", lambda self: None)
        no_docker.start()
        self.addCleanup(no_docker.stop)
        self.build = mock.patch.object(wizard.bootstrap, "build",
                                       return_value=self.tmp / "out" / "pack.manifest.json")
        self.build.start()
        self.addCleanup(self.build.stop)
        self.volumes = self.tmp / "Volumes"
        (self.volumes / "SYNC").mkdir(parents=True)
        self.said = []

    def talk(self, answers, cli):
        answers = list(answers)

        def ask(question):
            self.said.append(question)
            if not answers:
                raise AssertionError(f"no answer left for: {question}")
            return answers.pop(0)

        w = wizard.Wizard(ask=ask, say=self.said.append, run=cli, volumes=self.volumes,
                          info=None, upstream=UPSTREAM, any_path=True)
        with contextlib.redirect_stdout(io.StringIO()):
            code = w.main()
        self.assertEqual(answers, [], "unused answers")
        return code, "\n".join(self.said)

    def test_serial_with_letter_o_is_read_as_zero_and_saved(self):
        cli = FakeCli(self.tmp)
        code, text = self.talk(["xv3o m13h", "6"], cli)
        self.assertEqual(code, 0)
        self.assertIn("read as a zero: XV30M13H", text)
        saved = json.loads((self.tmp / "home" / "wizard.json").read_text())
        self.assertEqual(saved["serial"], "XV30M13H")
        self.talk(["y", "6"], cli)  # the next run offers the saved serial

    def test_car_with_old_syncextpack_gets_cleanup_and_the_app_pack(self):
        cli = FakeCli(self.tmp, menu=("Video Player", "Navitel", "Reboot"))
        code, text = self.talk([SERIAL, "1", "2", "", "y", "", "", "n", "6"], cli)
        self.assertEqual(code, 0)
        self.assertEqual(cli.commands(), ["job inventory", "stick prepare", "stick import",
                                          "status --serial", "job remove", "stick prepare",
                                          "stick import", "bootstrap prepare"])
        remove = next(c for c in cli.calls if c[:2] == ["job", "remove"])
        self.assertEqual(remove[2:5], ["Video Player", "Navitel", "--purge"])
        self.assertIn("--apps-only", next(c for c in cli.calls if c[0] == "bootstrap"))
        self.assertIn("The Apps menu also has: Video Player, Navitel", text)

    def test_ford_only_menu_goes_straight_to_the_first_install(self):
        cli = FakeCli(self.tmp)
        code, text = self.talk([SERIAL, "1", "1", "", "", "n", "6"], cli)
        self.assertEqual(cli.commands(), ["bootstrap prepare", "bootstrap finish"])
        self.assertNotIn("--apps-only", cli.calls[0])
        self.assertIn("Installer.jpg", text)

    def test_untouched_inventory_stick_means_first_install(self):
        cli = FakeCli(self.tmp, inventory="pending")
        updater = self.volumes / "SYNC" / "SyncExtPack"
        updater.mkdir()
        (updater / "install.bin").write_bytes(b"the inventory nobody ran")
        (updater / "notes.txt").write_text("not ours")
        code, text = self.talk([SERIAL, "1", "3", "", "", "", "n", "6"], cli)
        self.assertEqual(cli.commands(), ["job inventory", "stick prepare", "stick import",
                                          "bootstrap prepare", "bootstrap finish"])
        self.assertIn("did not touch the stick", text)
        self.assertFalse((updater / "install.bin").exists())  # our leftover, moved aside
        self.assertTrue((updater / "notes.txt").exists())      # not ours, left alone
        prepare = next(c for c in cli.calls if c[:2] == ["bootstrap", "prepare"])
        self.assertIn("--manifest", prepare)

    def test_the_first_install_reads_its_record_before_the_stick_is_ejected(self):
        # Without --any-path, as on a real computer: a command that ejects takes the stick away.
        cli = FakeCli(self.tmp, ejects=self.tmp / "pulled")
        stick_dir = self.volumes / "SYNC"

        def eject(path):
            shutil.move(str(path), str(self.tmp / "pulled"))
            return True, ""
        answers = [SERIAL, "1", "1", "", "", "n", "6"]

        def ask(question):
            self.said.append(question)
            if "back in this computer" in question and (self.tmp / "pulled").exists():
                shutil.move(str(self.tmp / "pulled"), str(stick_dir))
            return answers.pop(0)
        with mock.patch.object(wizard.hostos, "eject", side_effect=eject):
            w = wizard.Wizard(ask=ask, say=self.said.append, run=cli, volumes=self.volumes,
                              info=None, upstream=UPSTREAM)
            with contextlib.redirect_stdout(io.StringIO()):
                code = w.main()
        self.assertEqual(code, 0)
        self.assertEqual(cli.commands(), ["bootstrap prepare", "bootstrap finish"])
        self.assertIn("--no-eject", cli.calls[0])
        self.assertIn("stick ejected", self.said)
        self.assertIn("Installer.jpg", "\n".join(self.said))

    def test_unclear_inventory_stops_instead_of_guessing(self):
        cli = FakeCli(self.tmp, inventory="processed-no-report")
        code, text = self.talk([SERIAL, "1", "2", "", "6"], cli)
        self.assertEqual(cli.commands(), ["job inventory", "stick prepare", "stick import"])
        self.assertIn("not clear why", text)

    def test_a_different_stick_is_not_finished(self):
        cli = FakeCli(self.tmp)

        def swap_stick(question):
            if "back in this computer" in question:  # someone brings another car's stick
                (self.volumes / "SYNC" / "s2am" / "bootstrap.json").write_text(
                    json.dumps({"serial": "ABCDEFGH", "pack_install_sha256": "b" * 64}))
            return ""
        answers = iter([SERIAL, "1", "1"])
        w = wizard.Wizard(ask=lambda q: next(answers, None) or swap_stick(q), say=self.said.append,
                          run=cli, volumes=self.volumes, info=None, upstream=UPSTREAM, any_path=True)
        with contextlib.redirect_stdout(io.StringIO()):
            w.main()
        self.assertEqual(cli.commands(), ["bootstrap prepare"])
        self.assertIn("not the stick that was prepared", "\n".join(self.said))

    def test_failed_build_leaves_the_stick_alone(self):
        self.build.stop()
        with mock.patch.object(wizard.bootstrap, "build",
                               side_effect=wizard.bootstrap.BootstrapError("docker stopped")):
            updater = self.volumes / "SYNC" / "SyncExtPack"
            updater.mkdir()
            (updater / "installed.bin").write_bytes(b"old")
            code, text = self.talk([SERIAL, "1", "1"], FakeCli(self.tmp))
        self.build.start()
        self.assertIn("docker stopped", text)
        self.assertTrue((updater / "installed.bin").exists())

    def test_remove_picks_apps_by_number_and_confirms(self):
        cli = FakeCli(self.tmp, menu=("MirrorLink", "Navitel", "Reboot"))
        code, _ = self.talk([SERIAL, "2", "", "3", "1, 2", "y", "y", "", "6"], cli)
        removes = [c for c in cli.calls if c[:2] == ["job", "remove"]]
        self.assertEqual(removes[0][2:], ["MirrorLink", "Navitel", "--purge", "--serial", SERIAL,
                                          "--dry-run"])
        self.assertEqual(removes[1][2:5], ["MirrorLink", "Navitel", "--purge"])

    def test_improve_runs_the_three_jobs_in_order(self):
        cli = FakeCli(self.tmp, menu=("AutoKit", "Total Commander", "Reboot"))
        # serial, improve; no report yet, so an inventory trip first; then yes + stick back, three times
        code, text = self.talk([SERIAL, "5", "", "", "", "y", "", "", "", "", "6"], cli)  # Enter skips the last
        self.assertEqual(code, 0)
        jobs = [c[1:] for c in cli.calls if c[0] == "job"]
        self.assertEqual([j[0] for j in jobs], ["inventory", "runner-guard", "autokit-config", "autokit-mic-gate"])
        self.assertEqual(jobs[2][:3], ["autokit-config", "--screen", "640,384,10"])
        self.assertEqual(cli.commands().count("stick import"), 4)
        self.assertIn("That was all of them", text)
        self.assertEqual(text.count("Restart SYNC: hold"), 3)  # none of the three runs with an app open

    def test_improve_can_skip_a_step(self):
        cli = FakeCli(self.tmp, menu=("AutoKit",))
        self.talk([SERIAL, "5", "", "n", "n", "y", "", "n", "6"], cli)
        self.assertEqual([c[1] for c in cli.calls if c[0] == "job"], ["inventory", "autokit-mic-gate"])

    def test_improve_stops_at_a_step_that_did_not_come_back(self):
        cli = FakeCli(self.tmp, menu=("AutoKit",))
        cli.fail = "runner-guard"
        code, text = self.talk([SERIAL, "5", "", "y", "", "6"], cli)
        self.assertEqual([c[1] for c in cli.calls if c[0] == "job"], ["inventory", "runner-guard"])
        self.assertIn("did not come back as done", text)
        self.assertNotIn("That was all of them", text)

    def test_improve_does_not_call_an_unverified_step_done(self):
        """The script ran to its end ("applied"), but the import's own check of the car failed."""
        for kind, jobs in (("runner-guard", ["inventory", "runner-guard"]),
                           ("autokit-mic-gate", ["inventory", "runner-guard", "autokit-config", "autokit-mic-gate"])):
            with self.subTest(kind=kind):
                self.said.clear()
                shutil.rmtree(self.tmp / "home", ignore_errors=True)
                cli = FakeCli(self.tmp, menu=("AutoKit",))
                cli.unverified = kind
                answers = [SERIAL, "5", ""] + ["y", ""] * (len(jobs) - 1) + ["6"]  # it stops before the rest
                code, text = self.talk(answers, cli)
                self.assertEqual([c[1] for c in cli.calls if c[0] == "job"], jobs)
                self.assertIn("did not come back as done", text)
                self.assertEqual(text.count("Done: "), len(jobs) - 2)
                self.assertNotIn("That was all of them", text)

    def test_improve_needs_a_check_for_the_checked_jobs(self):
        source = (ROOT / "s2am" / "cli.py").read_text()
        self.assertEqual(wizard.CHECKED, ("guard", "akmic", "flash"))
        self.assertEqual(source.count("_keep_check(store, record, next((x for x in lines"), 1)
        self.assertEqual(source.count("_keep_check(store, record, _verify_guard("), 1)
        self.assertEqual(source.count("_keep_check(store, record, _verify_mic_gate("), 1)

    def test_carplay_first_is_only_done_when_chosen_and_checked(self):
        cli = FakeCli(self.tmp, menu=("AutoKit",))
        code, text = self.talk([SERIAL, "5", "", "n", "n", "n", "y", "", "6"], cli)
        jobs = [c[1:] for c in cli.calls if c[0] == "job"]
        self.assertEqual(jobs[1][:5], ["flash-tune", "--prio", "253", "--fast-prio", "253"])
        self.assertIn("not active yet: restart SYNC once more", text)
        self.assertIn(f"flash-tune --undo --serial {SERIAL}", text)  # a command that runs as shown
        self.assertNotIn("{serial}", text)
        self.assertIn("Tried in one car so far", text)
        self.said.clear()
        shutil.rmtree(self.tmp / "home", ignore_errors=True)
        cli = FakeCli(self.tmp, menu=("AutoKit",))
        cli.unverified = "flash-tune"
        code, text = self.talk([SERIAL, "5", "", "n", "n", "n", "y", "", "6"], cli)
        self.assertIn("did not come back as done", text)
        self.assertNotIn("not active yet", text)

    def test_carplay_first_stays_inside_the_tools_limits(self):
        from s2am import flashtune
        flashtune.check({"ThreadPrio256": wizard.FLASH_PRIORITY, "FastThreadPrio256": wizard.FLASH_PRIORITY})

    def test_improve_needs_autokit_on_the_car(self):
        cli = FakeCli(self.tmp, menu=("Video Player", "Reboot"))
        code, text = self.talk([SERIAL, "5", "", "6"], cli)
        self.assertEqual([c[1] for c in cli.calls if c[0] == "job"], ["inventory"])
        self.assertIn("Run the install first", text)

    def test_quit_anywhere(self):
        code, text = self.talk(["q"], FakeCli(self.tmp))
        self.assertEqual(code, 0)
        self.assertIn("nothing is lost", text)

    def test_no_usable_stick_explains_formatting(self):
        shutil.rmtree(self.volumes / "SYNC")
        code, text = self.talk([SERIAL, "q"], FakeCli(self.tmp))
        for step in wizard.hostos.format_steps():  # Disk Utility on a Mac, GNOME Disks on Linux, ...
            self.assertIn(step, text)
        self.assertIn({"Darwin": "Master Boot Record", "Windows": "diskpart"}.get(wizard.hostos.SYSTEM, "MBR / DOS"),
                      text)



class OtherComputers(unittest.TestCase):
    """What changes when the installer runs on Linux (issue #5) or Windows (issue #6)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        for name in ("SYNC", "Data", "Recovery"):
            (self.tmp / name).mkdir()
        self.said = []

    def wizard(self, answers=(), info=None):
        answers = list(answers)
        return wizard.Wizard(ask=lambda question: answers.pop(0), say=self.said.append,
                             run=lambda argv: 0, volumes=self.tmp, info=info, upstream=UPSTREAM)

    def test_macos_own_volume_names_are_skipped_only_on_macos(self):
        with mock.patch.object(wizard.hostos, "SYSTEM", "Darwin"):
            self.assertEqual([v.name for v, _ in self.wizard().candidate_sticks()], ["SYNC"])
        with mock.patch.object(wizard.hostos, "SYSTEM", "Linux"):  # a stick may well be called Data
            self.assertEqual([v.name for v, _ in self.wizard().candidate_sticks()], ["Data", "Recovery", "SYNC"])

    def test_a_linux_computer_without_its_tools_stops_before_any_stick_is_judged(self):
        with mock.patch.object(wizard.hostos, "SYSTEM", "Linux"), \
                mock.patch.object(wizard.hostos, "linux_problems", return_value=[wizard.hostos.TOO_OLD]):
            with self.assertRaises(wizard.Quit):
                self.wizard(info=lambda target: {}).check_linux()
        self.assertIn("util-linux 2.35", self.said[0])

    def test_a_ready_linux_computer_and_a_mac_go_on(self):
        with mock.patch.object(wizard.hostos, "SYSTEM", "Linux"), \
                mock.patch.object(wizard.hostos, "linux_problems", return_value=[]):
            self.wizard(info=lambda target: {}).check_linux()
        with mock.patch.object(wizard.hostos, "SYSTEM", "Darwin"), \
                mock.patch.object(wizard.hostos, "linux_problems", side_effect=AssertionError("not on a Mac")):
            self.wizard(info=lambda target: {}).check_linux()
        self.assertEqual(self.said, [])

    def test_missing_x86_emulation_is_said_and_stops_unless_the_user_goes_on(self):
        docker_up = mock.patch.object(wizard.subprocess, "run",
                                      return_value=mock.Mock(returncode=0))
        problem = mock.patch.object(wizard.container, "emulation_problem", return_value="needs emulation")
        with docker_up, problem, mock.patch.object(wizard.container, "docker", return_value=["docker"]):
            with self.assertRaises(wizard.Quit):
                self.wizard(["n"]).check_docker()
            self.wizard(["y"]).check_docker()
        self.assertIn("Note: needs emulation", self.said)

    def test_windows_offers_its_drives_by_letter(self):
        good = {"FilesystemName": "MS-DOS FAT32", "TotalSize": 31440961536, "Internal": False, "Ejectable": True,
                "BusProtocol": "USB", "SystemMounts": [], "WholeDiskContent": wizard.diskcheck.MBR,
                "WritableVolume": True, "FreeSpace": 30000000000}
        facts = {"C:\\": {**good, "Internal": True, "Ejectable": False, "SystemMounts": ["Windows itself"]},
                 "E:\\": good}
        # folders play the drives here; what the wizard calls them comes from hostos.display
        drives = {self.tmp / "Data": "C:", self.tmp / "SYNC": "E:"}
        facts = {str(self.tmp / "Data"): facts["C:\\"], str(self.tmp / "SYNC"): facts["E:\\"]}
        with mock.patch.object(wizard.hostos, "SYSTEM", "Windows"), \
                mock.patch.object(wizard.hostos, "volumes", return_value=list(drives)), \
                mock.patch.object(wizard.hostos, "display", side_effect=lambda path: drives[path]), \
                mock.patch.object(wizard.hostos, "volume_id", return_value="1234ABCD"):
            w = wizard.Wizard(ask=lambda question: "", say=self.said.append, run=lambda argv: 0,
                              info=lambda target: facts[target], upstream=UPSTREAM)
            self.assertEqual([v for v, _ in w.candidate_sticks()], [self.tmp / "SYNC"])  # C: is no stick
            w.pick_stick()
        self.assertEqual((w.stick, w.stick_id), (self.tmp / "SYNC", "1234ABCD"))
        self.assertIn("Using the USB stick E:.", self.said)

    def test_a_windows_stick_whose_serial_cannot_be_read_is_not_used(self):
        good = {"FilesystemName": "MS-DOS FAT32", "TotalSize": 31440961536, "Internal": False, "Ejectable": True,
                "BusProtocol": "USB", "SystemMounts": [], "WholeDiskContent": wizard.diskcheck.MBR,
                "WritableVolume": True, "FreeSpace": 30000000000}
        with mock.patch.object(wizard.hostos, "SYSTEM", "Windows"), \
                mock.patch.object(wizard.hostos, "volumes", return_value=[self.tmp / "SYNC"]), \
                mock.patch.object(wizard.hostos, "volume_id", return_value=None):
            w = wizard.Wizard(ask=lambda question: "", say=self.said.append, run=lambda argv: 0,
                              info=lambda target: good, upstream=UPSTREAM)
            (stick_found, findings), = w.candidate_sticks()
        self.assertTrue(wizard.diskcheck.failed(findings))
        self.assertIn("volume serial", findings[-1].message)

    def test_a_stick_back_under_another_letter_is_found_by_its_volume_serial(self):
        serials = {self.tmp / "SYNC": "1234ABCD", self.tmp / "Data": "99990000"}
        w = self.wizard([""])
        with mock.patch.object(wizard.hostos, "volume_id", side_effect=lambda path: serials.get(path)):
            w.use_stick(self.tmp / "SYNC")
            serials = {self.tmp / "SYNC": "99990000", self.tmp / "Recovery": "1234ABCD"}  # letters moved
            w.stick_back()
        self.assertEqual(w.stick, self.tmp / "Recovery")
        self.assertIn("The stick is back as Recovery.", self.said)

    def test_a_serial_that_cannot_be_read_when_the_stick_is_chosen_keeps_it_unchosen(self):
        good = {"FilesystemName": "MS-DOS FAT32", "TotalSize": 31440961536, "Internal": False, "Ejectable": True,
                "BusProtocol": "USB", "SystemMounts": [], "WholeDiskContent": wizard.diskcheck.MBR,
                "WritableVolume": True, "FreeSpace": 30000000000}
        reads = iter(["1234ABCD", None, "1234ABCD", "1234ABCD"])  # listed, chosen (fails), listed, chosen
        answers = iter(["", "q"])
        with mock.patch.object(wizard.hostos, "SYSTEM", "Windows"), \
                mock.patch.object(wizard.hostos, "volumes", return_value=[self.tmp / "SYNC"]), \
                mock.patch.object(wizard.hostos, "volume_id", side_effect=lambda path: next(reads)):
            w = wizard.Wizard(ask=lambda question: next(answers), say=self.said.append, run=lambda argv: 0,
                              info=lambda target: good, upstream=UPSTREAM)
            w.pick_stick()
        self.assertEqual((w.stick, w.stick_id), (self.tmp / "SYNC", "1234ABCD"))
        self.assertIn("could not read its volume serial", "\n".join(self.said))

    def test_another_drive_never_takes_the_place_of_the_stick(self):
        serials = {self.tmp / "SYNC": "1234ABCD"}
        w = self.wizard(["", "q"])
        with mock.patch.object(wizard.hostos, "volume_id", side_effect=lambda path: serials.get(path)):
            w.use_stick(self.tmp / "SYNC")
            serials = {self.tmp / "SYNC": "99990000", self.tmp / "Data": "55550000"}  # a good stick took E:
            with self.assertRaises(wizard.Quit):
                w.stick_back()
        self.assertEqual((w.stick, w.stick_id), (self.tmp / "SYNC", "1234ABCD"))
        self.assertIn("volume serial 1234ABCD", self.said[-1])

    def test_drives_windows_cannot_list_stop_the_installer(self):
        with mock.patch.object(wizard.hostos, "volumes", side_effect=wizard.hostos.HostError("no PowerShell")):
            w = wizard.Wizard(ask=lambda question: "", say=self.said.append, run=lambda argv: 0,
                              info=lambda target: {}, upstream=UPSTREAM)
            with self.assertRaises(wizard.Quit):
                w.candidate_sticks()
        self.assertIn("no PowerShell", self.said[0])

    def test_git_missing_is_said_before_anything_is_downloaded(self):
        w = wizard.Wizard(ask=lambda question: "y", say=self.said.append, run=lambda argv: 0,
                          volumes=self.tmp, info=None, upstream=self.tmp / "nothing-here")
        with mock.patch.object(wizard.shutil, "which", return_value=None), \
                mock.patch.object(wizard.subprocess, "run", side_effect=AssertionError("nothing may run")):
            with self.assertRaises(wizard.Quit):
                w.check_upstream()
        self.assertIn("git", self.said[-1])

    def test_the_undo_command_is_the_one_this_computer_uses(self):
        done = next(entry[3] for entry in wizard.IMPROVEMENTS if entry[1] == "CarPlay first")
        self.assertIn("{python} -m s2am job flash-tune --undo", done)


if __name__ == "__main__":
    unittest.main()
