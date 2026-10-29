"""Tests for the s2am toolkit: windows, jobs, sticks, the fake car loop and the CLI."""
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, pack, stick, window  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import Job, inventory_script, meta, stage  # noqa: E402
from s2am.state import Store, diff, parse_inventory  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "FullPack" / "RemoveExtPack" / "MortScript.exe").exists()
SERIAL = "XV31M13H"
MENU = (b'<?xml version="1.0" ?><root><apps>'
        b'<app name="AutoKit"><native>AutoKitPlugin</native></app>'
        b'<app name="Reboot"><native>RebootPlugin</native></app></apps></root>')


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)


class Window(unittest.TestCase):
    def test_window_end_is_last_second_of_bucket(self):
        now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
        end = window.valid_thru(now)
        self.assertEqual(window.bucket(end), window.bucket(now))
        self.assertNotEqual(window.bucket(end + timedelta(seconds=1)), window.bucket(now))

    def test_unsafe_close_to_boundary(self):
        end = window.valid_thru(datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.assertFalse(window.check(end - timedelta(hours=5))[0])
        self.assertTrue(window.check(end - timedelta(days=5))[0])

    def test_pack_build_refuses_near_boundary_before_running_docker(self):
        end = window.valid_thru(datetime(2026, 10, 29, tzinfo=timezone.utc))
        with mock.patch.object(pack.container, "run") as run:
            with self.assertRaisesRegex(pack.PackError, "window closes"):
                pack.build(Job(SERIAL, "inv"), Path("/nonexistent"), UPSTREAM,
                           now=end - timedelta(hours=1))
            run.assert_not_called()


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Staging(Temp):
    def test_payload_layout_and_meta(self):
        job = Job(SERIAL, "inv")
        work = stage(job, UPSTREAM, self.tmp / "work")
        target = work / "payload" / job.job_dir.lstrip("/")
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         ["MortScript.exe", "job.json", "s2amjob.exe", "s2amjob.mscr"])
        text = (work / "meta.txt").read_bytes().decode("utf-16-le")
        self.assertIn(f"POST_APP={job.job_dir}/s2amjob.exe\n", text)
        self.assertNotIn("NEED_REBOOT", text)
        self.assertEqual(set(job.files), {f"{job.job_dir}/{n}" for n in
                                          ("MortScript.exe", "s2amjob.exe", "s2amjob.mscr")})
        self.assertEqual(Job.from_json((work / "job.json").read_text()).id, job.id)

    def test_runner_is_mortrunner_beside_mortscript(self):
        job = Job(SERIAL, "inv")
        target = stage(job, UPSTREAM, self.tmp / "work") / "payload" / job.job_dir.lstrip("/")
        self.assertEqual((target / "s2amjob.exe").read_bytes(),
                         (UPSTREAM / "FullPack/RemoveExtPack/RemoveExtPack.exe").read_bytes())

    def test_restaging_starts_clean(self):
        job = Job(SERIAL, "inv")
        work = stage(job, UPSTREAM, self.tmp / "work")
        (work / "leftover").write_text("x")
        stage(job, UPSTREAM, work)
        self.assertFalse((work / "leftover").exists())

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            stage(Job(SERIAL, "nope"), UPSTREAM, self.tmp / "work")


class Script(unittest.TestCase):
    def setUp(self):
        self.job = Job(SERIAL, "inv")
        self.script = inventory_script(self.job)

    def test_blocks_are_balanced(self):
        words = re.findall(r"^\s*(ForEach|EndForEach|If|EndIf)\b", self.script, re.M)
        self.assertEqual(words.count("ForEach"), words.count("EndForEach"))
        self.assertEqual(words.count("If"), words.count("EndIf"))

    def test_every_line_has_balanced_quotes_and_ascii(self):
        self.script.encode("ascii")
        for line in self.script.splitlines():
            self.assertEqual(line.count('"') % 2, 0, line)

    def test_car_paths_use_backslashes(self):
        for literal in re.findall(r'"([^"]*)"', self.script):
            if literal.startswith(("\\", "/")):
                self.assertNotIn("/", literal, literal)
        self.assertIn(f"\\SyncExtendedPack\\_s2am\\done\\{self.job.id}.txt", self.script)
        self.assertIn(f"\\USB Disk\\s2am\\reports\\{self.job.id}", self.script)

    def test_errors_never_open_dialogs(self):
        self.assertEqual(self.script.splitlines()[1], 'ErrorLevel("off")')

    def test_done_marker_only_after_inventory_exists(self):
        guard = self.script.index("If (FileExists(inv))")
        self.assertGreater(self.script.index(" applied\")"), guard)
        self.assertGreater(self.script.index(f'WriteFile("\\SyncExtendedPack\\_s2am\\done'), guard)

    def test_replay_guard_comes_before_any_work(self):
        guard = self.script.index("If (FileExists(")
        self.assertLess(guard, self.script.index("inventory.txt"))
        self.assertLess(guard, self.script.index("WriteFile(\"\\SyncExtendedPack"))

    def test_risky_calls_come_last(self):
        risky = min(self.script.index(n) for n in ("FormatTime", "MortScriptVersion", "FreeDiskSpace"))
        self.assertGreater(risky, self.script.index(" applied\")"))

    def test_lines_end_with_crlf(self):
        self.assertTrue(self.script.endswith("\r\n"))
        self.assertNotIn("\n", self.script.replace("\r\n", ""))

    def test_quote_in_string_is_refused(self):
        job = Job(SERIAL, "inv", id='bad"id')
        with self.assertRaises(ValueError):
            inventory_script(job)

    def test_meta_is_utf16_key_value(self):
        text = meta(self.job).decode("utf-16-le")
        self.assertTrue(all("=" in line for line in text.splitlines()))


class Stick(Temp):
    def stick(self):
        root = self.tmp / "stick"
        (root / "SyncExtPack").mkdir(parents=True)
        return root

    def test_prepare_moves_earlier_updater_files_away(self):
        root = self.stick()
        for name in ("installed.bin", "install_log.txt", "pack_install.bin"):
            (root / "SyncExtPack" / name).write_text(name)
        bin_ = self.tmp / "install.bin"
        bin_.write_bytes(b"pack")
        archive = stick.prepare(root, bin_, Job(SERIAL, "inv"), require_volume=False)
        self.assertEqual(sorted(p.name for p in (root / "SyncExtPack").iterdir()), ["install.bin"])
        self.assertEqual(sorted(p.name for p in archive.iterdir()),
                         ["install_log.txt", "installed.bin", "pack_install.bin"])

    def test_older_pending_job_is_superseded(self):
        root = self.stick()
        bin_ = self.tmp / "install.bin"
        bin_.write_bytes(b"pack")
        first, second = Job(SERIAL, "inv"), Job(SERIAL, "inv")
        stick.prepare(root, bin_, first, require_volume=False)
        stick.prepare(root, bin_, second, require_volume=False)
        self.assertEqual([p.stem for p in (root / "s2am" / "pending").iterdir()], [second.id])

    def test_requires_a_volume_by_default(self):
        with self.assertRaisesRegex(stick.StickError, "/Volumes"):
            stick.prepare(self.stick(), self.tmp / "x", Job(SERIAL, "inv"))


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(Temp):
    """Mac -> stick -> fake car -> stick -> Mac, the way it will run for real."""

    def setUp(self):
        super().setUp()
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\AutoKit.exe", b"x" * 100)
        self.car.put("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\Sub\\a.dll", b"y" * 10)
        self.car.put("\\SyncExtendedPack\\Apps\\Tools\\explorer.exe", b"z" * 5)
        self.car.put("\\Windows\\AutoKitPlugin.dll", b"p" * 7)
        self.car.put("\\8inchSkins\\Ford\\Sync\\Apps\\Info\\SyncApps\\SyncApps.xml", MENU)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def run_job(self):
        job = Job(SERIAL, "inv")
        work = stage(job, UPSTREAM, self.tmp / "jobs" / job.id)
        (work / "install.bin").write_bytes(b"stand-in for crypto_pack output")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        return job, work

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def test_inventory_round_trip(self):
        job, work = self.run_job()
        self.car.insert(self.stick, work, job)
        results = stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual([r["status"] for r in results], ["applied"])
        _, entries, info = Store().latest_inventory(SERIAL)
        paths = {e.path for e in entries}
        self.assertIn("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\AutoKit.exe", paths)
        self.assertIn("\\Windows\\AutoKitPlugin.dll", paths)
        self.assertEqual(info["mortscript"], "4.2")
        self.assertTrue((self.stick / "SyncExtPack" / "installed.bin").exists())
        self.assertTrue((Store().report(SERIAL, job.id) / "install_log.txt").exists())

    def test_replayed_stick_does_not_apply_twice_and_keeps_the_inventory(self):
        job, work = self.run_job()
        (self.stick / "SyncExtPack" / "installed.bin").write_text("left by hand")  # rename will fail
        self.car.insert(self.stick, work, job)
        self.car.insert(self.stick, work, job)
        self.assertEqual(self.car.runs, 2)
        report = self.stick / "s2am" / "reports" / job.id
        self.assertIn("applied", (report / "done.txt").read_text())
        self.assertTrue((report / "replayed.txt").exists())
        results = stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual((results[0]["status"], results[0]["replayed"]), ("applied", True))
        self.assertEqual(Store().latest_inventory(SERIAL)[0], job.id)

    def test_job_that_ran_without_report_keeps_its_log(self):
        job, work = self.run_job()
        updater = self.stick / "SyncExtPack"
        (updater / "install.bin").rename(updater / "installed.bin")
        (updater / "install_log.txt").write_text("Install completed with errors")
        results = stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual(results[0]["status"], "processed-no-report")
        log = Store().report(SERIAL, job.id) / "install_log.txt"
        self.assertIn("errors", log.read_text())

    def test_latest_follows_import_order_not_build_order(self):
        older, older_work = self.run_job()
        newer = Job(SERIAL, "inv")
        newer_work = stage(newer, UPSTREAM, self.tmp / "jobs" / newer.id)
        (newer_work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, newer_work / "install.bin", newer, require_volume=False)
        self.car.insert(self.stick, newer_work, newer)
        stick.import_reports(self.stick, Store(), require_volume=False)
        stick.prepare(self.stick, older_work / "install.bin", older, require_volume=False)
        self.car.insert(self.stick, older_work, older)
        stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual(Store().latest_inventory(SERIAL)[0], older.id)

    def test_wrong_serial_is_not_installed(self):
        job, work = self.run_job()
        FakeCar(self.tmp / "other", "ABCDEFGH").insert(self.stick, work, job)
        results = stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual(results[0]["status"], "pending")

    def test_status_and_diff_from_the_cli(self):
        job, work = self.run_job()
        self.car.insert(self.stick, work, job)
        stick.import_reports(self.stick, Store(), require_volume=False)
        code, out = self.cli("status", "--serial", SERIAL)
        self.assertEqual(code, 0)
        self.assertIn("\\SyncExtendedPack\\Apps\\Media\\AutoKit  2 files, 110 B", out)
        self.assertIn("menu: AutoKit, Reboot", out)
        self.assertIn("plugins: AutoKitPlugin.dll", out)

        self.car.put("\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\Media.exe", b"v" * 3)
        job2, work2 = self.run_job()
        self.car.insert(self.stick, work2, job2)
        stick.import_reports(self.stick, Store(), require_volume=False)
        code, out = self.cli("diff", "--serial", SERIAL)
        self.assertEqual(code, 0)
        self.assertIn("+ \\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\Media.exe (3 B)", out)

    def test_cli_stick_commands(self):
        job = Job(SERIAL, "inv")
        work = stage(job, UPSTREAM, self.tmp / "jobs" / job.id)
        (work / "install.bin").write_bytes(b"pack")
        code, out = self.cli("stick", "prepare", str(self.stick), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        self.car.insert(self.stick, work, job)
        code, out = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertEqual((code, out.strip()), (0, f"{job.id}: applied"))


class UntrustedStick(Temp):
    """A stick is untrusted input: nothing on it may reach outside the store."""

    def setUp(self):
        super().setUp()
        self.stick = self.tmp / "stick"
        (self.stick / "s2am" / "pending").mkdir(parents=True)
        (self.stick / "SyncExtPack").mkdir()
        self.victim = self.tmp / "victim"
        self.victim.mkdir()
        (self.victim / "keep.txt").write_text("precious")

    def pending(self, name, body):
        (self.stick / "s2am" / "pending" / name).write_text(body)

    def test_path_like_ids_and_serials_are_rejected(self):
        good = Job(SERIAL, "inv")
        for job_id, serial in ((str(self.victim), SERIAL), ("../../victim", SERIAL),
                               (good.id, "../victim"), (good.id, str(self.victim))):
            with self.subTest(job_id=job_id, serial=serial):
                self.pending(f"{good.id}.json",
                             f'{{"serial": "{serial}", "kind": "inv", "id": "{job_id}"}}')
                results = stick.import_reports(self.stick, Store(), require_volume=False)
                self.assertEqual(results[0]["status"], "rejected")
                self.assertEqual((self.victim / "keep.txt").read_text(), "precious")

    def test_malformed_job_files_are_rejected(self):
        for body in ("not json", "[]", '{"kind": "inv"}', '{"serial": 5, "kind": "inv", "id": 7}'):
            with self.subTest(body=body):
                self.pending("x.json", body)
                results = stick.import_reports(self.stick, Store(), require_volume=False)
                self.assertEqual(results[0]["status"], "rejected")

    def test_symlinked_install_log_is_not_followed(self):
        job = Job(SERIAL, "inv")
        self.pending(f"{job.id}.json", job.to_json())
        (self.stick / "SyncExtPack" / "installed.bin").write_text("ran")
        (self.stick / "SyncExtPack" / "install_log.txt").symlink_to(self.victim / "keep.txt")
        stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual((self.victim / "keep.txt").read_text(), "precious")
        report = Store().report(SERIAL, job.id)
        self.assertFalse(report and (report / "install_log.txt").exists())

    def test_report_with_symlink_is_rejected(self):
        job = Job(SERIAL, "inv")
        self.pending(f"{job.id}.json", job.to_json())
        report = self.stick / "s2am" / "reports" / job.id
        report.mkdir(parents=True)
        (report / "done.txt").write_text("applied")
        (report / "inventory.txt").symlink_to(self.victim / "keep.txt")
        results = stick.import_reports(self.stick, Store(), require_volume=False)
        self.assertEqual(results[0]["status"], "rejected")
        self.assertIsNone(Store().report(SERIAL, job.id))

    def test_symlinked_stick_folders_are_refused(self):
        shutil.rmtree(self.stick / "s2am")
        (self.stick / "s2am").symlink_to(self.victim)
        with self.assertRaisesRegex(stick.StickError, "symlink"):
            stick.import_reports(self.stick, Store(), require_volume=False)

    def test_store_refuses_escaping_paths(self):
        store = Store()
        for parts in (("..", "x"), (SERIAL, "jobs", "../../x.json"), ("/etc",)):
            with self.subTest(parts=parts), self.assertRaises(ValueError):
                store._inside(*parts)


class WindowLead(unittest.TestCase):
    def test_unsafe_just_after_rollover(self):
        start = window.valid_from(datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.assertEqual(window.bucket(start), window.bucket(start + timedelta(hours=1)))
        self.assertNotEqual(window.bucket(start - timedelta(seconds=1)), window.bucket(start))
        self.assertFalse(window.check(start + timedelta(hours=2))[0])
        self.assertTrue(window.check(start + timedelta(days=3))[0])


class ContainerPaths(unittest.TestCase):
    def test_relative_workdir_is_mounted_as_absolute_path(self):
        from s2am import container
        with mock.patch.object(container.subprocess, "run") as run, \
                mock.patch.object(container, "docker", return_value=["docker"]):
            run.return_value.returncode = 0
            container.run(Path("relative-job"), "true")
        mount = run.call_args[0][0][run.call_args[0][0].index("-v") + 1]
        self.assertTrue(mount.startswith("/"), mount)


class Diff(unittest.TestCase):
    def test_reports_added_removed_and_resized_case_insensitively(self):
        old = parse_inventory("F|\\A\\x.exe|1\r\nF|\\A\\gone.dll|2\r\nD|\\A\r\n")
        new = parse_inventory("F|\\a\\X.EXE|5\r\nF|\\A\\new.dll|3\r\nD|\\A\r\n")
        self.assertEqual(diff(old, new),
                         ["+ \\A\\new.dll (3 B)", "- \\A\\gone.dll", "~ \\a\\X.EXE (1 -> 5 B)"])

    def test_parse_ignores_noise(self):
        self.assertEqual(parse_inventory("garbage\r\nF|\\x|notanumber\r\n")[0].size, None)


class Cli(Temp):
    def test_rejects_bad_serial(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["status", "--serial", "XVO1M13H"])

    def test_diff_with_unknown_or_unsafe_ids_fails_cleanly(self):
        for ids in (["20261029-000000-inv-aaaa", "20261029-000000-inv-bbbb"], ["..", "x"],
                    ["20261029-000000-inv-aaaa"]):
            with self.subTest(ids=ids), contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["diff", "--serial", SERIAL, *ids]), 1)


if __name__ == "__main__":
    unittest.main()
