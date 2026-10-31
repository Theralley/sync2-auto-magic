"""Tests for the safe Phase 2 jobs: autokit-config, snapshot, logger, and `s2am report`."""
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import apps, cli, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am import native  # noqa: E402
from s2am.job import (AUTOKIT_CE, MENU_XML, Job, autokit_config_script, logger_script,  # noqa: E402
                      meta, snapshot_script)

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "FullPack" / "RemoveExtPack" / "MortScript.exe").exists()
SERIAL = "XV31M13H"


def balanced(test, script):
    for start, end in (("If", "EndIf"), ("ForEach", "EndForEach"), ("While", "EndWhile")):
        words = re.findall(rf"^\s*({start}|{end})\b", script, re.M)
        test.assertEqual(words.count(start), words.count(end), start)


class Scripts(unittest.TestCase):
    def test_config_backs_up_before_writing_and_guards_busy(self):
        script = autokit_config_script(Job(SERIAL, "akcfg", params={"screen": "800,480,15",
                                                                     "decoder": "software"}))
        steps = ['If (NOT DirExists(ak))', 'ProcExists("AutoKit.exe")',
                 'Copy(ak & "\\screenconfig", bk & "\\screenconfig", TRUE)',
                 'WriteFile(ak & "\\screenconfig", "800,480,15")', 'Delete(ak & "\\usehwdec")',
                 'Delete(ak & "\\Auto_Box_Update.img")']
        positions = [script.index(s) for s in steps]
        self.assertEqual(positions, sorted(positions))
        balanced(self, script)
        hardware = autokit_config_script(Job(SERIAL, "akcfg", params={"screen": "800,480,30",
                                                                       "decoder": "hardware"}))
        self.assertIn('WriteFile(ak & "\\usehwdec", "")', hardware)

    def test_config_refuses_bad_values(self):
        for params in ({"screen": "800x480", "decoder": "software"},
                       {"screen": "800,480,15", "decoder": "gpu"},
                       {"screen": '800,480,15"', "decoder": "software"}, {"restore": "../x"}):
            with self.subTest(params), self.assertRaises(ValueError):
                autokit_config_script(Job(SERIAL, "akcfg", params=params))

    def test_snapshot_is_read_only(self):
        script = snapshot_script(Job(SERIAL, "snap"))
        self.assertNotRegex(script, r"\b(RegWrite\w*|RegDelete\w*|Delete|DelTree|RmDir|Copy\(xml)")
        self.assertIn('regSubKeys("HKLM", "Services")', script)
        self.assertIn('regValues("HKLM", "Init")', script)
        balanced(self, script)
        self.assertNotIn("NEED_REBOOT", meta(Job(SERIAL, "snap")).decode("utf-16-le"))

    def test_logger_duration_is_bounded(self):
        self.assertIn('\\s2amwatch.exe", "60 " & out)', logger_script(Job(SERIAL, "log", params={"seconds": 60})))
        for seconds in (5, 901, "60"):
            with self.subTest(seconds), self.assertRaises(ValueError):
                logger_script(Job(SERIAL, "log", params={"seconds": seconds}))


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        for patcher in (mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")}),
                        mock.patch.object(native, "binary", return_value=b"MZ stand-in")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put(f"{AUTOKIT_CE}\\AutoKit.exe", b"a" * 10)
        self.car.put(f"{AUTOKIT_CE}\\usehwdec", b"")
        self.car.put(MENU_XML, apps.render_menu([("AutoKit", "AutoKitPlugin", "x.png")]))
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def run_job(self, *args):
        work = self.tmp / f"job{len(list(self.tmp.glob('job*')))}"
        code, out = self.cli("job", *args, "--serial", SERIAL, "--no-pack", "--work", str(work))
        self.assertEqual(code, 0, out)
        job = Job.from_json((work / "job.json").read_text())
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.car.insert(self.stick, work, job)
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        return job, work, imported

    def status(self):
        return self.cli("status", "--serial", SERIAL)[1]

    def test_config_then_restore(self):
        self.run_job("inventory")
        self.assertIn("AutoKit video: screen default (800,480,15), decoder hardware", self.status())
        configured, _, imported = self.run_job("autokit-config", "--screen", "800,480,30")
        self.assertIn("applied", imported)
        self.assertIn("AutoKit video: screen 800,480,30, decoder software", self.status())
        self.run_job("autokit-config", "--restore", configured.id)
        self.assertIn("decoder hardware", self.status())
        self.assertFalse(self.car.exists(f"{AUTOKIT_CE}\\screenconfig"))

    def test_language_alone_leaves_video_settings_and_restores(self):
        self.car.put(f"{AUTOKIT_CE}\\lang", b"\x04\x08\x00\x00")  # stock: Chinese (0x0804)
        self.run_job("inventory")
        self.assertIn("language chinese", self.status())
        configured, work, imported = self.run_job("autokit-config", "--lang", "english")
        self.assertIn("applied", imported)
        self.assertEqual(self.car._resolve(f"{AUTOKIT_CE}\\lang").read_bytes(), b"\x09\x04\x00\x00")
        self.assertFalse(self.car.exists(f"{AUTOKIT_CE}\\screenconfig"))
        self.assertTrue(self.car.exists(f"{AUTOKIT_CE}\\usehwdec"))
        self.assertIn("decoder hardware, language english", self.status())
        self.assertEqual((work / "payload" / configured.job_dir.lstrip("/") / "lang").read_bytes(),
                         b"\x09\x04\x00\x00")
        self.run_job("autokit-config", "--restore", configured.id)
        self.assertEqual(self.car._resolve(f"{AUTOKIT_CE}\\lang").read_bytes(), b"\x04\x08\x00\x00")

    def test_language_script_copies_from_the_job_folder(self):
        script = autokit_config_script(Job(SERIAL, "akcfg", params={"lang": "english"}))
        self.assertIn('\\lang", ak & "\\lang", TRUE)', script)
        guard = script.index('If (NOT FileExists(bk & "\\lang.absent"))')
        self.assertLess(guard, script.index('\\lang", ak & "\\lang", TRUE)'))
        self.assertIn("backup-failed.txt", script[guard:])
        self.assertNotIn("screenconfig\", ", script.split("If (FileExists(ak")[0])
        with self.assertRaises(ValueError):
            autokit_config_script(Job(SERIAL, "akcfg", params={"lang": "klingon"}))
        with self.assertRaises(ValueError):
            autokit_config_script(Job(SERIAL, "akcfg", params={}))

    def test_firmware_image_is_removed_and_reported(self):
        self.run_job("inventory")
        self.car.put(f"{AUTOKIT_CE}\\Auto_Box_Update.img", b"fw")
        job, _, _ = self.run_job("autokit-config")
        self.assertFalse(self.car.exists(f"{AUTOKIT_CE}\\Auto_Box_Update.img"))
        self.assertIn("firmware-image-removed", self.cli("report", "--serial", SERIAL, job.id)[1])

    def test_config_waits_while_autokit_runs(self):
        self.run_job("inventory")
        self.car.running.add("autokit.exe")
        _, _, imported = self.run_job("autokit-config")
        self.assertIn("busy", imported)
        self.assertTrue(self.car.exists(f"{AUTOKIT_CE}\\usehwdec"))

    def test_snapshot_report(self):
        self.car.registry = {"HKLM\\Services\\UPDATESVC": {"Dll": "UpdateService", "Order": "10"},
                             "HKLM\\Drivers\\Active\\12": {"Name": "CBX1:"},
                             "HKLM\\Init": {"Launch50": "explorer.exe"}}
        job, _, imported = self.run_job("snapshot")
        self.assertIn("applied", imported)
        report = self.cli("report", "--serial", SERIAL, job.id)[1]
        for text in ("HKLM\\Services\\UPDATESVC", "UpdateService", "CBX1:", "explorer.exe",
                     "system: 7.0"):
            self.assertIn(text, report)

    def test_logger_report_shows_the_watch_log_and_the_logs_it_copied(self):
        self.car.put(f"{AUTOKIT_CE}\\hwlog.log", b"box_plugout\r\n")
        self.car.put("\\SyncExtendedPack\\_s2am\\guard.log", b"0|start|AutoKit.exe\r\n")
        job, _, imported = self.run_job("logger", "--seconds", "60")
        self.assertIn("applied", imported)
        report = self.cli("report", "--serial", SERIAL, job.id)[1]
        for text in ("[watch.log", "12:00:00.010|proc+|57|AutoKit.exe", "|end",
                     "[guard.log: runner guard log when the stick ran]", "0|start|AutoKit.exe",
                     "[autokit-hwlog.log", "box_plugout"):
            self.assertIn(text, report)

    def test_logger_report_shows_every_numbered_copy_of_autokits_log(self):
        self.car.watch_copies = {
            "autokit-hwlog-live-01.log": "first run SW_HIDE\r\n".encode("utf-16-le"),
            "autokit-hwlog-live-02.log": "\ufeffsecond run\r\n".encode("utf-16-le"),
            "guard-live-01.log": b"1|start|AutoKit.exe\r\n"}
        job, _, imported = self.run_job("logger", "--seconds", "60")
        self.assertIn("applied", imported)
        report = self.cli("report", "--serial", SERIAL, job.id)[1]
        for text in ("[guard-live-01.log: runner guard log, copy 1 the watcher made]", "1|start|AutoKit.exe",
                     "[autokit-hwlog-live-01.log: AutoKit's own log, copy 1", "first run SW_HIDE",
                     "[autokit-hwlog-live-02.log: AutoKit's own log, copy 2", "second run"):
            self.assertIn(text, report)
        self.assertLess(report.index("first run"), report.index("second run"))
        self.assertNotIn("\x00", report)

    def test_a_long_copied_log_shows_its_start_and_end(self):
        path = self.tmp / "autokit-hwlog-live-01.log"
        path.write_bytes("".join(f"line {n}\r\n" for n in range(1, 501)).encode("utf-16-le"))
        lines = cli._log_text(path).splitlines()
        self.assertEqual(len(lines), 201)
        self.assertEqual((lines[0], lines[19], lines[-1]), ("line 1", "line 20", "line 500"))
        self.assertIn("300 lines left out", lines[20])
        self.assertEqual(lines[21], "line 321")

    def test_logger_ships_the_watcher_and_starts_it_in_the_background(self):
        job, work, _ = self.run_job("logger")
        folder = work / "payload" / job.job_dir.lstrip("/")
        self.assertEqual((folder / "s2amwatch.exe").read_bytes(), b"MZ stand-in")
        self.assertFalse((folder / "s2amlog.exe").exists())
        script = (folder / "s2amjob.mscr").read_text()
        self.assertIn('\\s2amwatch.exe", "180 " & out)', script)
        self.assertNotIn("RunWait", script)

if __name__ == "__main__":
    unittest.main()
