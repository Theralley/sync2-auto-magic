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
from s2am.job import (AUTOKIT_CE, MENU_XML, Job, autokit_config_script, logger_loop,  # noqa: E402
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

    def test_logger_loop_is_bounded_and_read_only(self):
        loop = logger_loop(Job(SERIAL, "log", params={"seconds": 60}))
        self.assertIn("While (i < 60)", loop)
        self.assertIn("Sleep(1000)", loop)
        self.assertNotRegex(loop, r"\b(RegWrite\w*|RegDelete\w*|Delete|DelTree|Run|Kill)\(")
        balanced(self, loop)
        for seconds in (5, 901, "60"):
            with self.subTest(seconds), self.assertRaises(ValueError):
                logger_loop(Job(SERIAL, "log", params={"seconds": seconds}))


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
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

    def test_logger_timeline_keeps_only_changes(self):
        self.car.log_lines = ["start|2026-10-30 12:00:00", "12:00:01|0|desktop.exe|SYNC|CBX1:",
                              "12:00:02|0|desktop.exe|SYNC|CBX1:", "12:00:03|1|AutoKit.exe|AutoKit|CBX1:",
                              "12:00:04|1|AutoKit.exe|AutoKit|CBX1:", "end"]
        job, _, imported = self.run_job("logger", "--seconds", "60")
        self.assertIn("applied", imported)
        report = self.cli("report", "--serial", SERIAL, job.id)[1]
        self.assertIn("12:00:01|0|desktop.exe", report)
        self.assertIn("12:00:03|1|AutoKit.exe", report)
        self.assertNotIn("12:00:02", report)
        self.assertNotIn("12:00:04", report)

    def test_logger_ships_its_own_runner_and_loop(self):
        job, work, _ = self.run_job("logger")
        folder = work / "payload" / job.job_dir.lstrip("/")
        self.assertTrue((folder / "s2amlog.exe").is_file())
        self.assertIn("While (i < 180)", (folder / "s2amlog.mscr").read_text())
        self.assertIn('Run("', (folder / "s2amjob.mscr").read_text())


if __name__ == "__main__":
    unittest.main()
