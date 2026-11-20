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

    def __init__(self, tmp: Path, inventory="applied", menu=("Video Player", "Reboot")):
        self.tmp, self.inventory, self.menu = tmp, inventory, list(menu)
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
            short = {"runner-guard": "guard", "autokit-mic-gate": "akmic"}.get(kind, kind)
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

    def test_unclear_inventory_stops_instead_of_guessing(self):
        cli = FakeCli(self.tmp, inventory="processed-no-report")
        code, text = self.talk([SERIAL, "1", "2", "", "6"], cli)
        self.assertEqual(cli.commands(), ["job inventory", "stick prepare", "stick import"])
        self.assertIn("not clear why", text)

    def test_a_different_stick_is_not_finished(self):
        cli = FakeCli(self.tmp)

        def swap_stick(question):
            if "back in this Mac" in question:  # someone brings another car's stick
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
        code, text = self.talk([SERIAL, "5", "", "", "", "y", "", "", "", "6"], cli)
        self.assertEqual(code, 0)
        jobs = [c[1:] for c in cli.calls if c[0] == "job"]
        self.assertEqual([j[0] for j in jobs], ["inventory", "runner-guard", "autokit-config", "autokit-mic-gate"])
        self.assertEqual(jobs[2][:3], ["autokit-config", "--screen", "640,384,10"])
        self.assertEqual(cli.commands().count("stick import"), 4)
        self.assertIn("That was all of them", text)
        self.assertEqual(text.count("Restart SYNC: hold"), 3)  # none of the three runs with an app open

    def test_improve_can_skip_a_step(self):
        cli = FakeCli(self.tmp, menu=("AutoKit",))
        self.talk([SERIAL, "5", "", "n", "n", "y", "", "6"], cli)
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
                answers = [SERIAL, "5", ""] + ["y", ""] * (len(jobs) - 1) + ["6"]
                code, text = self.talk(answers, cli)
                self.assertEqual([c[1] for c in cli.calls if c[0] == "job"], jobs)
                self.assertIn("did not come back as done", text)
                self.assertEqual(text.count("Done: "), len(jobs) - 2)
                self.assertNotIn("That was all of them", text)

    def test_improve_needs_a_check_for_the_checked_jobs(self):
        self.assertEqual(wizard.CHECKED, ("guard", "akmic"))
        source = (ROOT / "s2am" / "cli.py").read_text()
        self.assertEqual(source.count("_keep_check(store, record, _verify_guard("), 1)
        self.assertEqual(source.count("_keep_check(store, record, _verify_mic_gate("), 1)

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
        self.assertIn("Format MS-DOS (FAT), Scheme Master Boot Record", text)


if __name__ == "__main__":
    unittest.main()
