"""One install collects both clock-investigation reports without changing settings."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from s2am import cli, job, native, stick
from s2am.fakecar import FakeCar

SERIAL = "XV31M13H"


class Clock(unittest.TestCase):
    def test_module_profile_has_no_registry_capture_or_hardware_mutation(self):
        task = job.Job(SERIAL, "clock", params={"modules": True})
        script = job.clock_script(task)
        self.assertEqual(script.count('\\s2ampmic.exe", out)'), 1)
        self.assertEqual(script.count('\\s2ammodules.exe", out)'), 1)
        self.assertNotIn("s2amreg.exe", script)
        self.assertIn('If (FileExists(out & "\\modules-done.txt"))', script)
        self.assertNotRegex(script, r"\b(RegWrite\w*|RegDelete\w*|Reset|Kill|RunWait|Delete|DelTree)\(")
        self.assertNotIn("NEED_REBOOT", job.meta(task).decode("utf-16-le"))
        with self.assertRaises(ValueError):
            job.clock_script(job.Job(SERIAL, "clock", params={"modules": "yes"}))

    def test_module_profile_stages_and_imports_only_its_requested_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with mock.patch.dict(os.environ, {"S2AM_HOME": str(folder / "home")}), \
                    mock.patch.object(native, "binary", side_effect=lambda name: name.encode()):
                work = folder / "job"
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["job", "clock", "--modules", "--serial", SERIAL,
                                               "--no-pack", "--work", str(work)]), 0)
                task = job.Job.from_json((work / "job.json").read_text())
                self.assertEqual(task.params, {"modules": True})
                payload = work / "payload" / task.job_dir.lstrip("/")
                self.assertFalse((payload / "s2amreg.exe").exists())
                for name in ("s2ampmic.exe", "s2ammodules.exe"):
                    self.assertEqual((payload / name).read_bytes(), name.encode())
                (work / "install.bin").write_bytes(b"stand-in pack")
                usb = folder / "stick"
                usb.mkdir()
                stick.prepare(usb, work / "install.bin", task, require_volume=False)
                FakeCar(folder / "car", SERIAL).insert(usb, work, task)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.main(["stick", "import", str(usb), "--any-path"])
                self.assertIn("NOT complete: PMIC report", out.getvalue())
                self.assertIn("NOT complete: module report", out.getvalue())
                self.assertNotIn("s2amreg.exe", out.getvalue())

    def test_script_runs_both_helpers_once_and_has_no_settings_or_restart_actions(self):
        task = job.Job(SERIAL, "clock", params={"roots": ["HKLM\\Drivers", "HKLM\\Services"], "depth": 8})
        script = job.SCRIPTS["clock"](task)
        self.assertEqual(script.count('\\s2ampmic.exe", out)'), 1)
        self.assertEqual(script.count('\\s2amreg.exe",'), 1)
        self.assertLess(script.index("s2ampmic.exe"), script.index("s2amreg.exe"))
        self.assertIn('FileExists(out & "\\pmic-done.txt")', script)
        self.assertIn('FileExists(out & "\\registry-done.txt")', script)
        self.assertNotRegex(script, r"\b(RegWrite\w*|RegDelete\w*|Reset|Kill|RunWait|Delete|DelTree)\(")
        self.assertNotIn("NEED_REBOOT", job.meta(task).decode("utf-16-le"))

    def test_invalid_registry_request_is_rejected_before_staging(self):
        with self.assertRaises(ValueError):
            job.SCRIPTS["clock"](job.Job(SERIAL, "clock", params={"roots": ['HKLM\\Bad"'], "depth": 8}))

    def test_staged_payload_and_import_keep_both_diagnostic_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with mock.patch.dict(os.environ, {"S2AM_HOME": str(folder / "home")}), \
                    mock.patch.object(native, "binary", side_effect=lambda name: name.encode()):
                work = folder / "job"
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["job", "clock", "--serial", SERIAL, "--no-pack", "--work", str(work)]), 0)
                task = job.Job.from_json((work / "job.json").read_text())
                self.assertEqual(task.params["depth"], 8)
                self.assertIn("HKLM\\Drivers", task.params["roots"])
                self.assertIn("HKLM\\Services", task.params["roots"])
                payload = work / "payload" / task.job_dir.lstrip("/")
                for name in ("s2ampmic.exe", "s2amreg.exe"):
                    self.assertEqual((payload / name).read_bytes(), name.encode())
                (work / "install.bin").write_bytes(b"stand-in pack")
                usb = folder / "stick"
                usb.mkdir()
                stick.prepare(usb, work / "install.bin", task, require_volume=False)
                self.assertEqual(stick.differences(usb, work / "install.bin", task), [])
                FakeCar(folder / "car", SERIAL).insert(usb, work, task)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.main(["stick", "import", str(usb), "--any-path"])
                self.assertIn("NOT complete: s2amreg.exe", out.getvalue())
                self.assertIn("NOT complete: PMIC report", out.getvalue())


if __name__ == "__main__":
    unittest.main()
