"""Tests for the runner guard: the native program's shape and the on/off job."""
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

from s2am import apps, cli, mortscript, native, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import MENU_XML, TOOLS_CE, Job, guard_script  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "FullPack").is_dir()
SERIAL = "XV31M13H"
SOURCE = (native.SOURCES / "s2amrun.c").read_text()
RUNNER = UPSTREAM / "FullPack/SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe"
STOCK = RUNNER.read_bytes() if RUNNER.exists() else b"Ford runner"
GUARD = b"MZ s2amrun stand-in"
PARAMS = {"stock_size": len(STOCK)}


class Source(unittest.TestCase):
    """The guard must repeat the stock runner's own steps; these come from its disassembly."""

    def test_gives_the_screen_back_like_the_stock_runner(self):
        show = SOURCE[SOURCE.index("static void show_sync"):SOURCE.index("static void close_app")]
        order = [show.index(s) for s in ('L"SYNC_DESKTOP_SHOW_UI"', "ShowWindow(desktop, SW_SHOW)",
                                         "SetForegroundWindow", 'L"show"', 'L"HandleShow"')]
        self.assertEqual(order, sorted(order))
        self.assertIn('FindWindowW(L"DESKTOP", NULL)', SOURCE)

    def test_starts_the_original_and_never_takes_its_mutex(self):
        self.assertIn('L"SyncAppsRunner.orig.exe"', SOURCE)
        self.assertNotIn("SyncAppsRunnerMutex", SOURCE)  # the original must still see itself as first

    def test_never_closes_an_app_that_has_not_shown_a_window(self):
        rule = re.search(r"hidden = \((.*?)\)", SOURCE).group(1)
        self.assertIn("shown", rule)

    def test_acts_only_when_nothing_usable_is_on_the_screen(self):
        # both rules need the empty screen: no app window, no SYNC, no other foreground window
        self.assertIn("empty", re.search(r"hidden = \((.*?)\)", SOURCE).group(1))
        self.assertIn("empty", re.search(r"gone = \((.*?)\)", SOURCE).group(1))
        nothing = SOURCE[SOURCE.index("static BOOL nothing_on_screen"):]
        self.assertIn("other_on_screen(app)", nothing[:300])
        close = SOURCE[SOURCE.index("static void close_app"):SOURCE.index("/* The app's file name")]
        self.assertLess(close.index("nothing_on_screen(pid)"), close.index("TerminateProcess"))

    def test_keeps_watching_while_the_app_lives(self):
        self.assertIn("if (runner_done && !app)", SOURCE)

    def test_registered_and_cached(self):
        self.assertEqual(native.PROGRAMS["s2amrun.exe"], "s2amrun.c")

    @unittest.skipUnless((ROOT / "build" / "native" / "s2amrun.exe").exists(), "run `s2am native build`")
    def test_built_binary_needs_only_coredll(self):
        native.check((ROOT / "build" / "native" / "s2amrun.exe").read_bytes(), "s2amrun.exe")


class Script(unittest.TestCase):
    def test_both_actions_pass_the_car_rules(self):
        for action in ("enable", "disable"):
            mortscript.check(guard_script(Job(SERIAL, "guard", params={"action": action, **PARAMS})))
        for bad in ({"action": "maybe", **PARAMS}, {"action": "enable"}, {"action": "enable",
                                                                          "stock_size": "11776"}):
            with self.subTest(bad), self.assertRaises(ValueError):
                guard_script(Job(SERIAL, "guard", params=bad))

    def test_selftest_runs_before_anything_is_copied(self):
        script = guard_script(Job(SERIAL, "guard", params={"action": "enable", **PARAMS}))
        self.assertLess(script.index("--s2am-selftest"), script.index("Copy("))
        self.assertLess(script.index('ProcExists("SyncAppsRunner.exe")'), script.index("RunWait("))


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        for patcher in (mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")}),
                        mock.patch.object(native, "binary", return_value=GUARD)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put(MENU_XML, apps.render_menu([("AutoKit", "AutoKitPlugin", "")]))
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.exe", STOCK)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def runner(self, name="SyncAppsRunner.exe"):
        path = self.car._resolve(f"{TOOLS_CE}\\{name}")
        return path.read_bytes() if path.exists() else None

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

    def status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["status", "--serial", SERIAL])
        return out.getvalue()

    def test_on_keeps_fords_runner_and_off_puts_it_back(self):
        imported = self.run_job("runner-guard")
        self.assertIn("verified: runner guard is on (self-test: s2amrun ok", imported)
        self.assertEqual(self.runner(), GUARD)
        self.assertEqual(self.runner("SyncAppsRunner.orig.exe"), STOCK)
        self.assertIn("runner guard (fixes the freeze when leaving an app): on", self.status())

        self.run_job("runner-guard")  # turned on again (an update): the original stays Ford's
        self.assertEqual(self.runner("SyncAppsRunner.orig.exe"), STOCK)

        imported = self.run_job("runner-guard", "--off")
        self.assertIn("verified: runner guard is off", imported)
        self.assertEqual(self.runner(), STOCK)
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))

    def test_nothing_changes_if_the_guard_cannot_run_on_the_car(self):
        self.car.native_runs = False
        imported = self.run_job("runner-guard")
        self.assertIn("failed", imported)
        self.assertEqual(self.runner(), STOCK)
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))

    def test_waits_while_an_app_is_open(self):
        self.car.running.add("syncappsrunner.exe")
        self.assertIn("busy", self.run_job("runner-guard"))
        self.assertEqual(self.runner(), STOCK)

    def test_a_damaged_keep_is_rebuilt_from_fords_runner(self):
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.orig.exe", STOCK[:100])  # power cut mid-copy
        self.assertIn("runner guard is on", self.run_job("runner-guard"))
        self.assertEqual(self.runner("SyncAppsRunner.orig.exe"), STOCK)
        self.assertEqual(self.runner(), GUARD)

    def test_an_unknown_runner_is_never_replaced(self):
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.exe", b"someone else's runner")
        self.assertIn("failed", self.run_job("runner-guard"))
        self.assertEqual(self.runner(), b"someone else's runner")
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))

    def test_off_refuses_a_damaged_keep(self):
        self.run_job("runner-guard")
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.orig.exe", STOCK[:100])
        self.assertIn("failed", self.run_job("runner-guard", "--off"))
        self.assertEqual(self.runner(), GUARD)  # still working, not replaced by a broken file

    def test_builder_refuses_a_guard_the_size_of_fords_runner(self):
        with mock.patch.object(native, "binary", return_value=b"x" * len(STOCK)):
            out = io.StringIO()
            with contextlib.redirect_stderr(out):
                code = cli.main(["job", "runner-guard", "--serial", SERIAL, "--no-pack",
                                 "--work", str(self.tmp / "same")])
        self.assertEqual(code, 1)
        self.assertIn("exactly the size", out.getvalue())

    def test_guard_log_shows_in_status(self):
        self.car.put("\\SyncExtendedPack\\_s2am\\guard.log", b"0|start|AutoKit.exe\r\n5|stuck|x1\r\n")
        self.run_job("inventory")
        self.assertIn("5|stuck|x1", self.status())


if __name__ == "__main__":
    unittest.main()
