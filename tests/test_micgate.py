import contextlib
import hashlib
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import apps, cli, micgate, mortscript, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import AUTOKIT_CE, MENU_XML, MIC_GATE_APPLIED, MIC_GATE_FILE, Job, mic_gate_script  # noqa: E402
from s2am.state import Store  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
STOCK = UPSTREAM / "FullPack/SyncExtendedPack/Apps/Media/AutoKit/AutoKit.exe"
SERIAL = "XV31M13H"
FUNCTION = struct.pack("<24I", *(0xE1A00000 if word is None else word for word in micgate.SHAPE))
PADDING = struct.pack("<I", 0xE12FFF1E) * 5


class Gate(unittest.TestCase):
    def test_opens_exactly_one_instruction_and_is_idempotent(self):
        module = PADDING + FUNCTION + PADDING
        opened = micgate.open_gate(module)
        changed = [i for i in range(len(module)) if module[i] != opened[i]]
        self.assertEqual(changed, [len(PADDING) + 4 * micgate.ANSWER])  # the low byte of mov r0, #0
        self.assertEqual(opened[changed[0]], 1)
        self.assertFalse(micgate.is_open(module))
        self.assertTrue(micgate.is_open(opened))
        self.assertEqual(micgate.open_gate(opened), opened)

    def test_refuses_a_program_without_the_function_or_with_two(self):
        for module in (PADDING * 10, PADDING + FUNCTION + FUNCTION, FUNCTION + micgate.open_gate(FUNCTION),
                       FUNCTION[:-4] + PADDING):
            with self.subTest(len(module)), self.assertRaises(micgate.GateError):
                micgate.open_gate(module)

    @unittest.skipUnless(STOCK.is_file(), "needs the app pack")
    def test_the_packs_autokit_has_the_gate_once_at_the_address_read_from_it(self):
        stock = STOCK.read_bytes()
        offset = micgate._find(stock, micgate.SHAPE)
        self.assertEqual(len(offset), 1)
        # .text: virtual address 0x1000, in the file at 0x400, image base 0x10000
        self.assertEqual(0x10000 + 0x1000 + offset[0] - 0x400, 0x28F48)
        opened = micgate.open_gate(stock)
        self.assertEqual(sum(a != b for a, b in zip(stock, opened)), 1)


class Script(unittest.TestCase):
    def test_checks_everything_before_the_first_change_and_keeps_the_way_back(self):
        script = mic_gate_script(Job(SERIAL, "akmic", params={"size": 370176}))
        mortscript.check(script)
        first = script.index(f'ak & "\\{MIC_GATE_FILE}", TRUE)')
        for check in ('ProcExists("AutoKit.exe")', "payload-bad.txt", 'NOT FileExists(ak & "\\AutoKit.exe.patched")',
                      'FileSize(ak & "\\AutoKit.exe.patched") <> 370176', 'FileSize(ak & "\\AutoKit.exe") <> 370176'):
            self.assertLess(script.index(check), first, check)
        swap = script.index(f'Copy(ak & "\\{MIC_GATE_FILE}", ak & "\\AutoKit.exe", TRUE)')
        back = script.index('Copy(ak & "\\AutoKit.exe.patched", ak & "\\AutoKit.exe", TRUE)')
        self.assertLess(swap, back)
        self.assertEqual(script.count(f'out & "\\{MIC_GATE_APPLIED}", TRUE)'), 2)  # also after a rollback
        self.assertLess(back, script.index("rollback-failed.txt"))
        self.assertLess(script.index("rollback-failed.txt"), script.index("the patched one was put back"))
        self.assertNotIn("Delete(ak & \"\\AutoKit.exe\")", script)
        for bad in ({}, {"size": "370176"}, {"size": True}, {"size": 12}):
            with self.subTest(bad), self.assertRaises(ValueError):
                mic_gate_script(Job(SERIAL, "akmic", params=bad))


@unittest.skipUnless(STOCK.is_file(), "needs the app pack")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        from s2am.autokit import HOOK_SOURCE, patch_waveout
        self.patched = patch_waveout.patch(STOCK.read_bytes(), (UPSTREAM / HOOK_SOURCE).read_bytes())
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put(MENU_XML, apps.render_menu([("AutoKit", "AutoKitPlugin", "")]))
        for name in ("AutoKit.exe", "AutoKit.exe.patched"):
            self.car.put(f"{AUTOKIT_CE}\\{name}", self.patched)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def live(self):
        return self.car._resolve(f"{AUTOKIT_CE}\\AutoKit.exe").read_bytes()

    def run_job(self, *args):
        work = self.tmp / f"job{len(list(self.tmp.glob('job*')))}"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["job", *args, "--serial", SERIAL, "--no-pack", "--work", str(work)])
        self.assertEqual(code, 0, out.getvalue())
        job = Job.from_json((work / "job.json").read_text())
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.car.insert(self.stick, work, job)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["stick", "import", str(self.stick), "--any-path"])
        return out.getvalue()

    def test_opens_the_gate_verifies_it_and_autokit_patched_goes_back(self):
        imported = self.run_job("autokit-mic-gate")
        self.assertIn("verified: the car's AutoKit.exe is the one with the microphone gate open", imported)
        self.assertTrue(micgate.is_open(self.live()))
        self.assertEqual(sum(a != b for a, b in zip(self.live(), self.patched)), 1)
        self.assertFalse(micgate.is_open(self.car._resolve(f"{AUTOKIT_CE}\\AutoKit.exe.patched").read_bytes()))
        self.run_job("autokit-patched")
        self.assertEqual(self.live(), self.patched)

    def test_changes_nothing_while_autokit_runs_or_on_a_car_it_does_not_know(self):
        self.car.autokit_running = True
        imported = self.run_job("autokit-mic-gate")
        self.assertIn("nothing changed", imported)
        self.assertEqual(self.live(), self.patched)
        self.car.autokit_running = False
        self.car.put(f"{AUTOKIT_CE}\\AutoKit.exe", self.patched + b"x")
        self.assertIn("nothing changed", self.run_job("autokit-mic-gate"))
        self.assertEqual(self.live(), self.patched + b"x")

    def test_a_copy_that_does_not_come_out_whole_is_rolled_back(self):
        self.car.broken_copies.add(f"{AUTOKIT_CE}\\AutoKit.exe".lower())
        imported = self.run_job("autokit-mic-gate")
        self.assertIn("NOT applied: the car's AutoKit.exe is the patched one", imported)
        self.assertEqual(self.live(), self.patched)

    def test_a_way_back_that_fails_too_is_said_as_damage_not_as_put_back(self):
        self.car.broken_copies.add(f"{AUTOKIT_CE}\\AutoKit.exe".lower())
        self.car.mic_gate_rollback_works = False
        imported = self.run_job("autokit-mic-gate")
        self.assertIn("FAILED: the car's AutoKit.exe is damaged", imported)
        self.assertNotEqual(self.live(), self.patched)

    def test_a_result_that_did_not_come_back_is_unknown_not_unchanged(self):
        self.car.mic_gate_readback = False
        imported = self.run_job("autokit-mic-gate")
        self.assertIn("NOT verified: no copy of the car's AutoKit.exe came back", imported)
        self.assertNotIn("nothing changed", imported)
        self.assertTrue(micgate.is_open(self.live()))  # it was in fact applied

    def test_a_staging_copy_that_fails_changes_nothing(self):
        self.car.broken_copies.add(f"{AUTOKIT_CE}\\{MIC_GATE_FILE}".lower())
        self.run_job("autokit-mic-gate")
        self.assertEqual(self.live(), self.patched)

    def test_the_report_names_a_car_that_ended_up_with_something_else(self):
        report = self.tmp / "report"
        report.mkdir()
        (report / MIC_GATE_APPLIED).write_bytes(b"other")
        text = cli._verify_mic_gate(report, {"sha256": hashlib.sha256(b"a").hexdigest(),
                                             "patched_sha256": hashlib.sha256(b"b").hexdigest()})
        self.assertIn("NOT verified", text)
        self.assertIsNotNone(Store)


if __name__ == "__main__":
    unittest.main()
