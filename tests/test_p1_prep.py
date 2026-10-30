"""Tests for the P1 prep tools: stick check, bootstrap prepare/finish, AutoKit swap jobs."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from s2am import bootstrap, cli, diskcheck, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import AUTOKIT_CE, AUTOKIT_MODULES, Job, autokit_script, stage  # noqa: E402
from s2am.state import Store  # noqa: E402
import make_pack  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "FullPack" / "RemoveExtPack" / "MortScript.exe").exists()
SERIAL = "XV31M13H"
NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()


def disk(**overrides):
    """A diskutil reader for a healthy 16 GB FAT32/MBR USB stick, with overrides."""
    volume = {"FilesystemName": "MS-DOS FAT32", "TotalSize": 16 * 10 ** 9, "Internal": False,
              "Ejectable": True, "BusProtocol": "USB", "ParentWholeDisk": "disk9",
              "DeviceIdentifier": "disk9s1", "WritableVolume": True, "FreeSpace": 15 * 10 ** 9}
    whole = {"Content": diskcheck.MBR}
    for key, value in overrides.items():
        (whole if key == "Content" else volume)[key] = value
    return lambda target: whole if target == "disk9" else volume


class StickCheck(Temp):
    def levels(self, **overrides):
        return {f.message.split(":")[0]: f.level
                for f in diskcheck.check(self.stick, info=disk(**overrides))}

    def test_healthy_stick_passes(self):
        findings = diskcheck.check(self.stick, info=disk())
        self.assertFalse(diskcheck.failed(findings), findings)

    def test_each_disk_problem_fails(self):
        cases = {"file system": {"FilesystemName": "ExFAT"},
                 "size": {"TotalSize": 64 * 10 ** 9},
                 "external removable disk": {"Internal": True},
                 "partition scheme": {"Content": "GUID_partition_scheme"},
                 "writable": {"WritableVolume": False}}
        for label, override in cases.items():
            with self.subTest(label):
                self.assertEqual(self.levels(**override)[label], "fail")

    def test_superfloppy_without_partition_table_fails(self):
        levels = self.levels(ParentWholeDisk="disk9s1")
        self.assertEqual(levels["partition scheme"], "fail")

    def test_firmware_autorun_files_fail(self):
        (self.stick / "autoinstall.lst").write_text("x")
        findings = diskcheck.check(self.stick, info=disk())
        self.assertTrue(any(f.level == "fail" and "firmware" in f.message for f in findings))

    def test_waiting_install_bin_is_flagged(self):
        (self.stick / "SyncExtPack").mkdir()
        (self.stick / "SyncExtPack" / "install.bin").write_bytes(b"x")
        findings = diskcheck.check(self.stick, info=None)
        self.assertTrue(any(f.level == "warn" and "install.bin" in f.message for f in findings))

    def test_cli_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["stick", "check", str(self.stick), "--any-path"]), 0)
        (self.stick / "SyncMyRide").mkdir()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["stick", "check", str(self.stick), "--any-path"]), 1)


class Bootstrap(Temp):
    def make_build(self, serial=SERIAL, apps=bootstrap.DEFAULT_APPS, expires=NOW + timedelta(days=10),
                   files=bootstrap.FILES, empty=()):
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        name = f"SyncExtPack_{serial}_{'_'.join(apps)}_audiofix"
        contents = {n: (b"" if n in empty else f"{n} payload".encode()) for n in files}
        with zipfile.ZipFile(out / f"{name}.zip", "w") as zf:
            for n, data in contents.items():
                zf.writestr(f"SyncExtPack/{n}", data)
        manifest = out / f"{name}.manifest.json"
        manifest.write_text(json.dumps({
            "serial": serial, "apps": list(apps), "install_before_utc": expires.isoformat(),
            "usb_files": {n: hashlib.sha256(d).hexdigest() for n, d in contents.items()},
            "archive_sha256": hashlib.sha256((out / f"{name}.zip").read_bytes()).hexdigest()}))
        return manifest

    def test_prepare_writes_the_four_files_and_record(self):
        record = bootstrap.prepare(self.stick, SERIAL, self.make_build(), now=NOW)
        self.assertEqual(sorted(p.name for p in (self.stick / "SyncExtPack").iterdir()),
                         sorted(bootstrap.FILES))
        self.assertEqual(record["serial"], SERIAL)
        self.assertTrue((self.stick / bootstrap.RECORD).is_file())

    def test_prepare_refuses_bad_builds(self):
        cases = {
            "built for": dict(serial="ABCDEFGH"),
            "expired": dict(expires=NOW - timedelta(minutes=1)),
            "expires within two days": dict(expires=NOW + timedelta(days=1)),
            "apps": dict(apps=("Explorer", "Reboot")),
            "manifest lists": dict(files=bootstrap.FILES + ("install.bin",)),
            "empty": dict(empty=("update.bin",)),
        }
        for message, kwargs in cases.items():
            with self.subTest(message):
                shutil.rmtree(self.tmp / "out", ignore_errors=True)
                manifest = self.make_build(**kwargs)
                if message == "built for":
                    manifest = manifest.rename(manifest.with_name(
                        manifest.name.replace("ABCDEFGH", SERIAL)))
                with self.assertRaisesRegex(bootstrap.BootstrapError, message):
                    bootstrap.prepare(self.stick, SERIAL, manifest, now=NOW)

    def test_prepare_refuses_a_tampered_archive(self):
        manifest = self.make_build()
        with zipfile.ZipFile(manifest.with_name(manifest.name.replace(".manifest.json", ".zip")),
                             "a") as zf:
            zf.writestr("../evil.txt", b"x")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "does not match"):
            bootstrap.prepare(self.stick, SERIAL, manifest, now=NOW)

    def test_prepare_refuses_a_used_stick_unless_forced(self):
        (self.stick / "SyncExtPack").mkdir()
        (self.stick / "SyncExtPack" / "installed.bin").write_bytes(b"old")
        manifest = self.make_build()
        with self.assertRaisesRegex(bootstrap.BootstrapError, "already has"):
            bootstrap.prepare(self.stick, SERIAL, manifest, now=NOW)
        bootstrap.prepare(self.stick, SERIAL, manifest, now=NOW, force=True)
        self.assertFalse((self.stick / "SyncExtPack" / "installed.bin").exists())
        self.assertTrue(list((self.stick / "s2am" / "history").rglob("installed.bin")))

    def test_finish_renames_after_checks(self):
        bootstrap.prepare(self.stick, SERIAL, self.make_build(), now=NOW)
        updater = self.stick / "SyncExtPack"
        (updater / "install_log.txt").write_text("stage one log")
        bootstrap.finish(self.stick, now=NOW)
        self.assertTrue((updater / "install.bin").is_file())
        self.assertFalse((updater / "pack_install.bin").exists())
        self.assertFalse((updater / "install_log.txt").exists())
        with self.assertRaisesRegex(bootstrap.BootstrapError, "already exists"):
            bootstrap.finish(self.stick, now=NOW)

    def test_finish_refuses_changed_or_expired_packs(self):
        bootstrap.prepare(self.stick, SERIAL, self.make_build(), now=NOW)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "expired"):
            bootstrap.finish(self.stick, now=NOW + timedelta(days=30))
        (self.stick / "SyncExtPack" / "pack_install.bin").write_bytes(b"swapped")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "does not match"):
            bootstrap.finish(self.stick, now=NOW)

    def test_finish_needs_a_prepared_stick(self):
        with self.assertRaisesRegex(bootstrap.BootstrapError, "bootstrap prepare"):
            bootstrap.finish(self.stick, now=NOW)

    def test_cli_prepare_with_existing_manifest(self):
        manifest = self.make_build(expires=datetime.now(timezone.utc) + timedelta(days=10))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(
                cli.window, "check", return_value=(True, NOW)):
            code = cli.main(["bootstrap", "prepare", "--serial", SERIAL, "--stick", str(self.stick),
                             "--manifest", str(manifest), "--any-path"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("Installer.jpg", out.getvalue())

    def test_apps_only_puts_just_the_app_pack_on_as_install_bin(self):
        (self.stick / "SyncExtPack").mkdir()
        (self.stick / "SyncExtPack" / "installed.bin").write_bytes(b"an earlier job")
        record = bootstrap.prepare_apps_only(self.stick, SERIAL, self.make_build(), now=NOW)
        updater = self.stick / "SyncExtPack"
        self.assertEqual([p.name for p in updater.iterdir()], ["install.bin"])
        self.assertEqual((updater / "install.bin").read_bytes(), b"pack_install.bin payload")
        self.assertEqual(record["mode"], "apps-only")
        self.assertTrue(list((self.stick / "s2am" / "history").rglob("installed.bin")))

    def test_apps_only_never_leaves_an_unchecked_install_bin(self):
        manifest = self.make_build()
        data = json.loads(manifest.read_text())
        data["usb_files"]["pack_install.bin"] = "0" * 64  # the stick copy will not match
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(bootstrap.BootstrapError, "does not match"):
            bootstrap.prepare_apps_only(self.stick, SERIAL, manifest, now=NOW)
        self.assertEqual(list((self.stick / "SyncExtPack").iterdir()), [])

    def test_apps_only_waits_for_an_unimported_job(self):
        (self.stick / "s2am" / "pending").mkdir(parents=True)
        (self.stick / "s2am" / "pending" / "20261030-000000-inv-aaaa.json").write_text("{}")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "import it first"):
            bootstrap.prepare_apps_only(self.stick, SERIAL, self.make_build(), now=NOW)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "expired"):
            bootstrap.prepare_apps_only(self.stick, SERIAL,
                                        self.make_build(expires=NOW - timedelta(minutes=1)),
                                        now=NOW, force=True)

    def test_cli_apps_only(self):
        manifest = self.make_build(expires=datetime.now(timezone.utc) + timedelta(days=10))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(
                cli.window, "check", return_value=(True, NOW)):
            code = cli.main(["bootstrap", "prepare", "--serial", SERIAL, "--stick", str(self.stick),
                             "--manifest", str(manifest), "--apps-only", "--any-path"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("as install.bin", out.getvalue())
        self.assertNotIn("Installer.jpg", out.getvalue())

    def test_job_stick_moves_stage_one_files_aside(self):
        bootstrap.prepare(self.stick, SERIAL, self.make_build(), now=NOW)
        (self.tmp / "job.bin").write_bytes(b"job")
        stick.prepare(self.stick, self.tmp / "job.bin", Job(SERIAL, "inv"), require_volume=False)
        self.assertEqual(sorted(p.name for p in (self.stick / "SyncExtPack").iterdir()),
                         ["install.bin"])


class AutoKitSwap(Temp):
    def test_script_swaps_all_three_modules_after_busy_guard(self):
        script = autokit_script(Job(SERIAL, "akstock"), "orig")
        busy = script.index('ProcExists("AutoKit.exe")')
        for module in AUTOKIT_MODULES:
            copy = script.index(f'Copy(ak & "\\{module}.orig", ak & "\\{module}", TRUE)')
            self.assertGreater(copy, busy)
        self.assertLess(script.index("Copy(ak"), script.index("inventory.txt"))
        with self.assertRaises(ValueError):
            autokit_script(Job(SERIAL, "akstock"), "evil")

    def test_module_list_matches_make_pack(self):
        self.assertEqual(AUTOKIT_MODULES, make_pack.PATCH_TARGETS)

    @unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
    def test_swap_round_trip_and_status_reports_the_variant(self):
        car = FakeCar(self.tmp / "car", SERIAL)
        for module in AUTOKIT_MODULES:
            car.put(f"{AUTOKIT_CE}\\{module}", b"p" * 120)
            car.put(f"{AUTOKIT_CE}\\{module}.patched", b"p" * 120)
            car.put(f"{AUTOKIT_CE}\\{module}.orig", b"s" * 100)

        def run(kind):
            job = Job(SERIAL, kind)
            work = stage(job, UPSTREAM, self.tmp / "jobs" / job.id)
            (work / "install.bin").write_bytes(b"pack")
            stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
            car.insert(self.stick, work, job)
            stick.import_reports(self.stick, Store(), require_volume=False)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["status", "--serial", SERIAL])
            return out.getvalue()

        self.assertIn("AutoKit audio modules: patched (all 3)", run("inv"))
        self.assertIn("AutoKit audio modules: stock (all 3)", run("akstock"))
        self.assertIn("AutoKit audio modules: patched (all 3)", run("akpatch"))

    @unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
    def test_busy_autokit_is_left_alone_and_job_can_rerun(self):
        car = FakeCar(self.tmp / "car", SERIAL)
        car.put(f"{AUTOKIT_CE}\\AutoKit.exe", b"p" * 120)
        car.put(f"{AUTOKIT_CE}\\AutoKit.exe.orig", b"s" * 100)
        car.autokit_running = True
        job = Job(SERIAL, "akstock")
        work = stage(job, UPSTREAM, self.tmp / "jobs" / job.id)
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        car.insert(self.stick, work, job)
        report = self.stick / "s2am" / "reports" / job.id
        self.assertTrue((report / "busy.txt").exists())
        self.assertFalse(car.exists(job.done_marker))
        self.assertEqual(car._resolve(f"{AUTOKIT_CE}\\AutoKit.exe").stat().st_size, 120)

    def test_cli_job_kinds(self):
        for kind in ("inventory", "autokit-stock", "autokit-patched"):
            with self.subTest(kind), contextlib.redirect_stdout(io.StringIO()):
                if not HAVE_UPSTREAM:
                    self.skipTest("syncextpack fixtures not present")
                code = cli.main(["job", kind, "--serial", SERIAL, "--no-pack",
                                 "--work", str(self.tmp / kind)])
                self.assertEqual(code, 0)
                self.assertTrue(re.search(r"-(inv|akstock|akpatch)-", Job.from_json(
                    (self.tmp / kind / "job.json").read_text()).id))


class WindowExitCode(unittest.TestCase):
    def test_unsafe_window_exits_nonzero(self):
        with mock.patch.object(cli.window, "check", return_value=(False, NOW)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["window"]), 1)


if __name__ == "__main__":
    unittest.main()
