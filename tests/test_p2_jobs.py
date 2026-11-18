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

    def test_config_with_measure_starts_the_loggers_last_and_fetches_on_the_second_visit(self):
        job = Job(SERIAL, "akcfg", params={"screen": "800,480,15", "decoder": "hardware", "measure": 1800})
        script = autokit_config_script(job)
        logs = f'"\\SyncExtendedPack\\_s2am\\load\\{job.id}'
        self.assertIn(f"logs = {logs}\"", script)
        # they run from copies in the log folder, so the job folder can be written again meanwhile
        self.assertIn('& "\\s2amdrive.exe", logs & "\\s2amdrive.exe", TRUE)', script)
        self.assertIn('Run(logs & "\\s2amwatch.exe", "1800 " & logs)', script)
        self.assertIn('Run(logs & "\\s2amdrive.exe", "1800 load " & logs)', script)
        self.assertLess(script.index('WriteFile(ak & "\\usehwdec", "")'), script.index("s2amdrive.exe"))
        self.assertLess(script.index('ProcExists("AutoKit.exe")'), script.index("s2amdrive.exe"))
        # the second visit: the copies sit between "it ran before" and Exit, ahead of any change
        replay = script[script.index("replayed.txt"):script.index("ak = ")]
        self.assertIn(f'Copy({logs}\\drive.log", out & "\\drive.log", TRUE)', replay)
        self.assertIn("Exit", replay)
        self.assertNotIn("s2amdrive.exe", replay)
        balanced(self, script)
        plain = autokit_config_script(Job(SERIAL, "akcfg", params={"screen": "800,480,15", "decoder": "hardware"}))
        self.assertNotIn("s2amdrive", plain)
        self.assertNotIn("drive.log", plain)
        for seconds in (59, 14401, "1800", True):
            with self.subTest(seconds), self.assertRaises(ValueError):
                autokit_config_script(Job(SERIAL, "akcfg", params={"screen": "800,480,15", "decoder": "hardware",
                                                                    "measure": seconds}))

    def test_logger_duration_is_bounded(self):
        self.assertIn('\\s2amwatch.exe", "60 " & out)', logger_script(Job(SERIAL, "log", params={"seconds": 60})))
        for seconds in (5, 901, "60"):
            with self.subTest(seconds), self.assertRaises(ValueError):
                logger_script(Job(SERIAL, "log", params={"seconds": seconds}))

    def test_drive_logger_runs_both_programs_for_at_most_four_hours(self):
        script = logger_script(Job(SERIAL, "log", params={"seconds": 14400, "drive": True}))
        self.assertIn('\\s2amwatch.exe", "14400 " & out)', script)
        self.assertIn('\\s2amdrive.exe", "14400 " & out)', script)
        self.assertNotIn("RunWait", script)
        balanced(self, script)
        self.assertNotIn("s2amdrive", logger_script(Job(SERIAL, "log", params={"seconds": 60})))
        for params in ({"seconds": 14401, "drive": True}, {"seconds": 3600}):
            with self.subTest(params), self.assertRaises(ValueError):
                logger_script(Job(SERIAL, "log", params=params))


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

    def test_microphone_alone_leaves_the_rest_and_restores(self):
        self.car.put(f"{AUTOKIT_CE}\\screenconfig", b"800,480,10")
        self.run_job("inventory")
        self.assertIn("microphone car", self.status())
        configured, _, imported = self.run_job("autokit-config", "--mic", "box")
        self.assertIn("applied", imported)
        self.assertTrue(self.car.exists(f"{AUTOKIT_CE}\\useboxmic"))
        self.assertEqual(self.car._resolve(f"{AUTOKIT_CE}\\screenconfig").read_bytes(), b"800,480,10")
        self.assertTrue(self.car.exists(f"{AUTOKIT_CE}\\usehwdec"))
        self.assertIn("microphone box", self.status())
        back, _, _ = self.run_job("autokit-config", "--mic", "car")
        self.assertFalse(self.car.exists(f"{AUTOKIT_CE}\\useboxmic"))
        self.run_job("autokit-config", "--restore", back.id)
        self.assertTrue(self.car.exists(f"{AUTOKIT_CE}\\useboxmic"))
        self.run_job("autokit-config", "--restore", configured.id)
        self.assertFalse(self.car.exists(f"{AUTOKIT_CE}\\useboxmic"))

    def test_microphone_script_backs_up_before_it_writes(self):
        script = autokit_config_script(Job(SERIAL, "akcfg", params={"mic": "box"}))
        guard = script.index('If (NOT FileExists(bk & "\\useboxmic.absent"))')
        self.assertLess(guard, script.index('WriteFile(ak & "\\useboxmic", "")'))
        self.assertNotIn("screenconfig\", ", script.split("If (FileExists(ak")[0])
        self.assertIn('Delete(ak & "\\useboxmic")',
                      autokit_config_script(Job(SERIAL, "akcfg", params={"mic": "car"})))
        with self.assertRaises(ValueError):
            autokit_config_script(Job(SERIAL, "akcfg", params={"mic": "phone"}))

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

    def test_load_logger_writes_to_the_car_so_the_stick_can_leave(self):
        job = Job(SERIAL, "log", params={"seconds": 1800, "load": True})
        script = logger_script(job)
        self.assertIn(f'logs = "\\SyncExtendedPack\\_s2am\\load\\{job.id}"', script)
        self.assertLess(script.index("MkDir(logs)"), script.index("s2amwatch.exe"))
        self.assertIn('\\s2amwatch.exe", "1800 " & logs)', script)
        self.assertIn('\\s2amdrive.exe", "1800 load " & logs)', script)
        self.assertNotIn('.exe", "1800 " & out', script)
        self.assertNotIn('load " & out', script)
        self.assertNotIn("RunWait", script)
        balanced(self, script)
        for other in ("drive", "native"):
            with self.subTest(other), self.assertRaises(ValueError):
                logger_script(Job(SERIAL, "log", params={"seconds": 1800, "load": True, other: True}))

    def test_collect_copies_the_logs_from_the_car_to_the_stick(self):
        logger = Job(SERIAL, "log", params={"seconds": 1800, "load": True})
        script = logger_script(Job(SERIAL, "log", params={"collect": logger.id}))
        folder = f"\\SyncExtendedPack\\_s2am\\load\\{logger.id}"
        for name in ("drive.log", "watch.log", "autokit-hwlog-live-01.log", "guard-live-99.log"):
            self.assertIn(f'If (FileExists("{folder}\\{name}"))', script)
            self.assertIn(f'Copy("{folder}\\{name}", out & "\\{name}", TRUE)', script)
        self.assertNotIn(".exe", script)
        balanced(self, script)
        with self.assertRaises(ValueError):
            logger_script(Job(SERIAL, "log", params={"collect": "..\\windows"}))

    def test_a_long_copied_log_shows_its_start_and_end(self):
        path = self.tmp / "autokit-hwlog-live-01.log"
        path.write_bytes("".join(f"line {n}\r\n" for n in range(1, 501)).encode("utf-16-le"))
        lines = cli._log_text(path).splitlines()
        self.assertEqual(len(lines), 201)
        self.assertEqual((lines[0], lines[19], lines[-1]), ("line 1", "line 20", "line 500"))
        self.assertIn("300 lines left out", lines[20])
        self.assertEqual(lines[21], "line 321")

    def test_drive_logger_ships_both_programs_and_its_report_counts_what_came_back(self):
        job, work, imported = self.run_job("logger", "--drive")
        self.assertIn("applied", imported)
        folder = work / "payload" / job.job_dir.lstrip("/")
        self.assertTrue((folder / "s2amdrive.exe").is_file())
        self.assertIn('\\s2amdrive.exe", "14400 " & out)', (folder / "s2amjob.mscr").read_text())
        report = self.cli("report", "--serial", SERIAL, job.id)[1]
        for text in ("[drive.log", "load|cpu 41%|memory 60%", "[screens] 1 screenshots",
                     "[skins.txt] 1 screen files copied", "0 failed; complete|1 files",
                     "[files.txt] 2 folders and files listed", "[watch.log"):
            self.assertIn(text, report)

    def test_load_logger_then_collect_brings_the_logs_home_on_a_second_stick(self):
        job, work, imported = self.run_job("logger", "--load")
        self.assertIn("applied", imported)
        self.assertEqual(job.params["seconds"], 1800)
        self.assertTrue((work / "payload" / job.job_dir.lstrip("/") / "s2amdrive.exe").is_file())
        self.assertTrue(self.car.exists(f"\\SyncExtendedPack\\_s2am\\load\\{job.id}\\drive.log"))
        self.assertNotIn("load|cpu", self.cli("report", "--serial", SERIAL, job.id)[1])
        collect, work, imported = self.run_job("logger", "--collect", job.id)
        self.assertIn("applied", imported)
        self.assertFalse((work / "payload" / collect.job_dir.lstrip("/") / "s2amdrive.exe").exists())
        report = self.cli("report", "--serial", SERIAL, collect.id)[1]
        for text in ("[drive.log", "load|cpu 41%|memory 60%", "[watch.log"):
            self.assertIn(text, report)
        for text in ("[screens]", "[skins.txt]", "[files.txt]"):
            self.assertNotIn(text, report)

    def test_config_with_measure_then_the_same_stick_again_brings_the_logs_home(self):
        work = self.tmp / "measure"
        code, out = self.cli("job", "autokit-config", "--decoder", "hardware", "--measure", "--serial", SERIAL,
                             "--no-pack", "--work", str(work))
        self.assertEqual(code, 0, out)
        job = Job.from_json((work / "job.json").read_text())
        self.assertEqual(job.params, {"screen": "800,480,15", "decoder": "hardware", "measure": 1800})
        for name in ("s2amwatch.exe", "s2amdrive.exe"):
            self.assertTrue((work / "payload" / job.job_dir.lstrip("/") / name).is_file())
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.assertEqual(stick.differences(self.stick, work / "install.bin", job), [])
        self.assertEqual((self.stick / "SyncExtPack" / "installed.bin").read_bytes(), stick.STAY)
        self.assertEqual(stick._status(self.stick / "s2am" / "reports" / job.id, self.stick / "SyncExtPack"),
                         ("pending", False))  # the stand-in is not a run
        self.car.insert(self.stick, work, job)
        self.assertTrue((self.stick / "SyncExtPack" / "install.bin").is_file())  # still there: it runs again
        report = self.stick / "s2am" / "reports" / job.id
        self.assertTrue(self.car.exists(f"\\SyncExtendedPack\\_s2am\\load\\{job.id}\\drive.log"))
        self.assertTrue(self.car.exists(f"{AUTOKIT_CE}\\usehwdec"))
        self.assertFalse((report / "drive.log").exists())
        self.car.insert(self.stick, work, job)  # the second visit
        self.assertTrue((report / "replayed.txt").is_file())
        self.assertTrue((report / "drive.log").is_file())
        self.assertTrue((report / "watch.log").is_file())
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn("applied", imported)
        self.assertIn("load|cpu 41%", self.cli("report", "--serial", SERIAL, job.id)[1])
        # imported: its record has left the stick, so the stick is used up and cannot run again
        self.assertFalse((self.stick / "SyncExtPack" / "install.bin").exists())
        self.assertNotEqual((self.stick / "SyncExtPack" / "installed.bin").read_bytes(), stick.STAY)
        runs = self.car.runs
        self.car.insert(self.stick, work, job)
        self.assertEqual(self.car.runs, runs)
        # its undo measures too, and a collect job can fetch either one later
        undo, undo_work, _ = self.run_job("autokit-config", "--restore", job.id, "--measure", "600")
        self.assertEqual(undo.params, {"restore": job.id, "measure": 600})
        self.assertTrue(self.car.exists(f"\\SyncExtendedPack\\_s2am\\load\\{undo.id}\\drive.log"))
        _, _, collected = self.run_job("logger", "--collect", undo.id)
        self.assertIn("applied", collected)

    def test_a_measuring_stick_whose_script_never_reported_is_not_called_unused(self):
        work = self.tmp / "silent"
        self.cli("job", "autokit-config", "--decoder", "hardware", "--measure", "--serial", SERIAL,
                 "--no-pack", "--work", str(work))
        job = Job.from_json((work / "job.json").read_text())
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        updater = self.stick / "SyncExtPack"
        self.assertEqual(stick._status(self.stick / "s2am" / "reports" / job.id, updater), ("pending", False))
        (updater / "install_log.txt").write_text("Install successfully completed!\n")  # ran, no report
        self.assertEqual(stick._status(self.stick / "s2am" / "reports" / job.id, updater),
                         ("processed-no-report", False))

    def test_a_running_autokit_stops_a_measuring_config_before_anything_starts(self):
        self.car.autokit_running = True
        job, _, imported = self.run_job("autokit-config", "--decoder", "hardware", "--measure")
        self.assertFalse(self.car.exists(f"\\SyncExtendedPack\\_s2am\\load\\{job.id}\\drive.log"))
        self.assertNotIn("applied", imported.replace("not applied", ""))

    def test_collect_needs_a_load_logger(self):
        job, _, _ = self.run_job("logger")
        code, out = self.cli("job", "logger", "--collect", job.id, "--serial", SERIAL, "--no-pack",
                             "--work", str(self.tmp / "nope"))
        self.assertNotEqual(code, 0)
        self.assertIn("not a logger --load job", out)

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
