"""Tests for installing apps from the Mac: catalog variants, the plan, and the fake-car loop."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from s2am import apps, cli, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import MENU_XML, MORTRUNNER_SOURCE, MORTSCRIPT_SOURCE, Job, stage  # noqa: E402
import patch_waveout  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "builder" / "units" / "app_units.py").exists()
SERIAL = "XV31M13H"
ICON = "Apps/Info/SyncApps/Icons/"
MENU = [("AutoKit", "AutoKitPlugin", ICON + "AutoKit.png"), ("", "", ""), ("", "", ""),
        ("Reboot", "RebootPlugin", ICON + "Reboot.png")]


class Stage(unittest.TestCase):
    def test_mac_and_tool_litter_never_reaches_the_car(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for name in (MORTSCRIPT_SOURCE, MORTRUNNER_SOURCE):
            (tmp / "up" / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp / "up" / name).write_bytes(b"MZ")
        app = tmp / "app"
        for name in ("Player.exe", "Userdata/.tmp", ".DS_Store", "._Player.exe",
                     ".omc/state/sessions/x/throttle.json", "Skin/.DS_Store"):
            (app / name).parent.mkdir(parents=True, exist_ok=True)
            (app / name).write_bytes(b"x")
        work = stage(Job(SERIAL, "inv"), tmp / "up", tmp / "work",  # any kind stages a payload alike
                     payload=[(app, "/SyncExtendedPack/Apps/Media/App")])
        landed = work / "payload" / "SyncExtendedPack" / "Apps" / "Media" / "App"
        copied = sorted(str(p.relative_to(landed)) for p in landed.rglob("*") if p.is_file())
        self.assertEqual(copied, ["Player.exe", "Userdata/.tmp"])


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Plan(unittest.TestCase):
    def setUp(self):
        self.catalog = apps.catalog(UPSTREAM)
        self.menu = apps.render_menu(MENU)

    def plan(self, app, menu=None, **kwargs):
        return apps.plan_install(app, menu or self.menu, self.catalog, UPSTREAM, **kwargs)

    def test_variants_and_english_default(self):
        player = self.catalog["video player"]
        self.assertEqual(set(player.variants), {"VideoPlayerUnit", "VideoPlayerENUnit"})
        self.assertEqual(apps.default_variant(player), "VideoPlayerENUnit")
        self.assertEqual(apps.default_variant(self.catalog["mirrorlink"]), "MirrorLinkENNewUnit")

    def test_install_fills_the_first_free_slot_and_maps_sources(self):
        plan = self.plan("total commander")
        self.assertEqual(plan.app, "Total Commander")
        self.assertTrue(plan.adds_to_menu)
        after = apps.menu_entries(plan.menu_after)
        self.assertEqual(after[1], ("Total Commander", "ExplorerPlugin", ICON + "Explorer.png"))
        self.assertEqual(after[2:], MENU[2:])
        self.assertEqual({dst for _, dst in plan.sources},
                         {"/windows/ExplorerPlugin.dll", "/SyncExtendedPack/Apps/Tools/explorer.exe",
                          "/8inchSkins/Ford/Sync/Apps/Info/SyncApps/Icons/Explorer.png"})

    def test_renamed_source_folder_lands_in_the_app_folder(self):
        plan = self.plan("Video Player")
        folders = [(src.name, dst) for src, dst in plan.sources if src.is_dir()]
        self.assertEqual(folders, [("VideoPlayer_EN", "/SyncExtendedPack/Apps/Media/VideoPlayer/")])

    def test_refusals(self):
        with self.assertRaisesRegex(apps.AppError, "already in the Apps menu"):
            self.plan("AutoKit")
        full = apps.render_menu([e if e[0] else ("X", "XPlugin", "") for e in MENU])
        with self.assertRaisesRegex(apps.AppError, "no free slot"):
            self.plan("Total Commander", menu=full)
        clash = apps.render_menu(MENU[:1] + [("Files", "ExplorerPlugin", "")] + MENU[2:])
        with self.assertRaisesRegex(apps.AppError, "already use the plugin"):
            self.plan("Total Commander", menu=clash)
        with self.assertRaisesRegex(apps.AppError, "installable"):
            self.plan("Spotify")
        with self.assertRaisesRegex(apps.AppError, "variants"):
            self.plan("Video Player", variant="NopeUnit")

    def test_reinstall_keeps_the_menu(self):
        plan = self.plan("AutoKit", reinstall=True)
        self.assertFalse(plan.adds_to_menu)
        self.assertEqual(plan.menu_after, self.menu)


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put("\\SyncExtendedPack\\Apps\\Tools\\SyncAppsRunner.exe", b"r")
        self.car.put(MENU_XML, apps.render_menu([("", "", "")] * 3 + MENU[3:]))
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
        return job, work, out, imported

    def menu_names(self):
        return [n for n, _, _ in apps.menu_entries(self.car._resolve(MENU_XML).read_bytes()) if n]

    def test_install_then_remove_round_trip(self):
        self.run_job("inventory")
        _, _, plan, imported = self.run_job("install", "Total Commander")
        self.assertIn("copy /SyncExtendedPack/Apps/Tools/explorer.exe", plan)
        self.assertIn("verified: 'Total Commander' is in the menu", imported)
        self.assertEqual(self.menu_names(), ["Total Commander", "Reboot"])
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Tools\\explorer.exe"))
        self.assertTrue(self.car.exists("\\windows\\ExplorerPlugin.dll"))

        _, _, _, imported = self.run_job("remove", "Total Commander", "--purge")
        self.assertIn("verified: 'Total Commander' is no longer in the menu", imported)
        self.assertFalse(self.car.exists("\\SyncExtendedPack\\Apps\\Tools\\explorer.exe"))
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Tools\\SyncAppsRunner.exe"))

    def test_autokit_install_carries_the_sound_patch(self):
        self.run_job("inventory")
        _, work, plan, imported = self.run_job("install", "AutoKit")
        self.assertIn("sound patch", plan)
        self.assertIn("verified", imported)
        folder = work / "payload" / "SyncExtendedPack/Apps/Media/AutoKit"
        for name in ("AutoKit.exe.orig", "AutoKit.exe.patched", "WaveOutHooks.dll"):
            self.assertTrue((folder / name).is_file(), name)
        imports = [d[1] for d in patch_waveout.PEImage((folder / "AutoKit.exe").read_bytes())
                   .import_descriptors()]
        self.assertIn("WaveOutHooks.dll", imports)
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\WaveOutHooks.dll"))

    def test_stale_menu_leaves_the_menu_alone(self):
        self.run_job("inventory")
        self.car.put(MENU_XML, apps.render_menu([("Other", "OtherPlugin", "")] + [("", "", "")] * 2
                                                + MENU[3:]))
        _, _, _, imported = self.run_job("install", "Total Commander")
        self.assertIn("stale", imported)
        self.assertNotIn("Total Commander", self.menu_names())

    def test_dry_run_and_apps_listing(self):
        self.run_job("inventory")
        code, out = self.cli("job", "install", "Video Player", "--serial", SERIAL, "--dry-run",
                             "--work", str(self.tmp / "dry"))
        self.assertEqual(code, 0, out)
        self.assertIn("VideoPlayerENUnit", out)
        self.assertFalse((self.tmp / "dry").exists())
        self.run_job("install", "Total Commander")
        code, out = self.cli("apps", "--serial", SERIAL)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"Total Commander\s+in menu")
        self.assertRegex(out, r"AutoKit\s+-")

    def test_install_needs_a_report_first(self):
        code, out = self.cli("job", "install", "AutoKit", "--serial", SERIAL, "--no-pack",
                             "--work", str(self.tmp / "x"))
        self.assertEqual(code, 1)
        self.assertIn("run an inventory job first", out)


if __name__ == "__main__":
    unittest.main()
