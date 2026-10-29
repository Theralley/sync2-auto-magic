"""Tests for removing apps: catalog, menu edit, removal plan, scripts, and the fake-car loop."""
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
from s2am.job import MENU_XML, Job, meta, removal_script, stage, undo_script  # noqa: E402
from s2am.state import Entry, Store  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "builder" / "units" / "app_units.py").exists()
SERIAL = "XV31M13H"
ICON = "Apps/Info/SyncApps/Icons/"
MENU = [("Video Player", "VideoPlayer", ICON + "VideoPlayer.png"),
        ("Total Commander", "ExplorerPlugin", ICON + "Explorer.png"),
        ("AutoKit", "AutoKitPlugin", ICON + "AutoKit.png"),
        ("", "", ""),
        ("Reboot", "RebootPlugin", ICON + "Reboot.png")]


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Catalog(unittest.TestCase):
    def setUp(self):
        self.catalog = apps.catalog(UPSTREAM)

    def test_known_apps_and_their_files(self):
        autokit = self.catalog["autokit"]
        self.assertEqual((autokit.plugin, autokit.icon), ("AutoKitPlugin", "AutoKit.png"))
        self.assertIn("/SyncExtendedPack/Apps/Media/AutoKit/", autokit.files)
        self.assertIn("/windows/AutoKitPlugin.dll", autokit.files)
        self.assertIn("/SyncExtendedPack/Apps/Tools/explorer.exe",
                      self.catalog["total commander"].files)

    def test_inherited_configs_and_renamed_folders(self):
        # VideoPlayer_EN installs into VideoPlayer/; MirrorLink variants into EasyConnected/.
        self.assertIn("/SyncExtendedPack/Apps/Media/VideoPlayer/", self.catalog["video player"].files)
        self.assertNotIn("/SyncExtendedPack/Apps/Media/VideoPlayer_EN/",
                         self.catalog["video player"].files)
        self.assertIn("/SyncExtendedPack/Apps/Media/EasyConnected/", self.catalog["mirrorlink"].files)

    def test_reading_the_catalog_imports_no_upstream_module(self):
        before = set(sys.modules)
        apps.catalog(UPSTREAM)
        self.assertEqual({m for m in set(sys.modules) - before if "builder" in m or "units" in m},
                         set())


class Menu(unittest.TestCase):
    def test_render_matches_the_builders_empty_slot_format(self):
        xml = apps.render_menu(MENU).decode()
        self.assertTrue(xml.startswith('<?xml version="1.0" ?>'))
        self.assertIn('<app name="">', xml)
        self.assertIn("<native/>", xml)
        self.assertEqual(apps.menu_entries(xml.encode()), MENU)

    def test_render_is_stable(self):
        once = apps.render_menu(MENU)
        self.assertEqual(apps.render_menu(apps.menu_entries(once)), once)


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Plan(unittest.TestCase):
    def setUp(self):
        self.catalog = apps.catalog(UPSTREAM)
        self.menu = apps.render_menu(MENU)
        self.inventory = [Entry("F", "\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\Media.exe", 5),
                          Entry("F", "\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\voSDKPlayer.exe", 5)]

    def plan(self, app, purge=False, menu=None):
        return apps.plan_removal(app, menu or self.menu, self.inventory, self.catalog, purge)

    def test_menu_only_keeps_every_file(self):
        plan = self.plan("video player")
        self.assertEqual(plan.app, "Video Player")
        self.assertEqual((plan.delete_dirs, plan.delete_files), ([], []))
        after = apps.menu_entries(plan.menu_after)
        self.assertEqual(len(after), len(MENU))
        self.assertEqual(after[0], ("", "", ""))
        self.assertEqual(after[1:], MENU[1:])

    def test_purge_deletes_owned_files_and_guards_running_exes(self):
        plan = self.plan("Video Player", purge=True)
        self.assertEqual(plan.delete_dirs, ["/SyncExtendedPack/Apps/Media/VideoPlayer/"])
        self.assertEqual(sorted(plan.delete_files),
                         ["/8inchSkins/Ford/Sync/Apps/Info/SyncApps/Icons/VideoPlayer.png",
                          "/windows/VideoPlayer.dll"])
        self.assertEqual(plan.executables, ["Media.exe", "voSDKPlayer.exe"])

    def test_registry_files_in_a_purged_folder_are_reported(self):
        self.inventory.append(Entry("F", "\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\box.reg", 3))
        plan = self.plan("Video Player", purge=True)
        self.assertTrue(any("box.reg" in k and "registry" in k for k in plan.kept))

    def test_purge_of_total_commander_deletes_only_its_exe_not_tools(self):
        plan = self.plan("Total Commander", purge=True)
        self.assertEqual(plan.delete_dirs, [])
        self.assertIn("/SyncExtendedPack/Apps/Tools/explorer.exe", plan.delete_files)
        self.assertNotIn("/SyncExtendedPack/Apps/Tools/", plan.delete_files + plan.delete_dirs)

    def test_shared_icon_or_plugin_is_kept(self):
        menu = apps.render_menu(MENU[:4] + [("Navitel", "NavitelPlugin", ICON + "Navitel.png"),
                                            ("Navitel Old", "NavitelOldPlugin", ICON + "Navitel.png")])
        plan = self.plan("Navitel Old", purge=True, menu=menu)
        self.assertTrue(any("Navitel.png" in k and ("also installed by 'Navitel'" in k
                                                     or "icon still used" in k) for k in plan.kept))
        self.assertNotIn("/8inchSkins/Ford/Sync/Apps/Info/SyncApps/Icons/Navitel.png",
                         plan.delete_files)

    def test_unknown_or_missing_apps_are_refused(self):
        with self.assertRaisesRegex(apps.AppError, "not.*in the Apps menu"):
            self.plan("Spotify")
        custom = apps.render_menu(MENU + [("MyTool", "MyToolPlugin", ICON + "x.png")])
        with self.assertRaisesRegex(apps.AppError, "not a SyncExtPack app"):
            self.plan("MyTool", purge=True, menu=custom)
        self.assertEqual(self.plan("MyTool", menu=custom).app, "MyTool")  # menu-only is fine

    def test_never_deletes_protected_masked_or_out_of_place_paths(self):
        for path in ("/windows/UpdateService.dll", "/SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe",
                     "/syncextendedpack/apps/tools/syncappsrunner.exe", "/SyncExtendedPack/Apps/",
                     "/SyncExtendedPack/Apps/Tools/", "/windows/Other.dll", "/8inchSkins/Ford/Sync/x.swf",
                     "/SyncExtendedPack/Apps/Media/../../windows/x.dll", "/SyncExtendedPack/Apps/Tools/*.exe",
                     "/SyncExtendedPack/Apps//Tools/", "/SyncExtendedPack/Apps/Media/A?/",
                     "SyncExtendedPack/Apps/Media/X/", "/SyncExtendedPack/Apps/Media/x\\y/"):
            with self.subTest(path):
                self.assertFalse(apps._allowed(path, "VideoPlayer"))
        for path in ("/SyncExtendedPack/Apps/Media/VideoPlayer/", "/windows/VideoPlayer.dll",
                     "/SyncExtendedPack/Apps/Tools/explorer.exe",
                     "/8inchSkins/Ford/Sync/Apps/Info/SyncApps/Icons/VideoPlayer.png"):
            with self.subTest(path):
                self.assertTrue(apps._allowed(path, "VideoPlayer"))

    def test_purge_is_refused_when_another_entry_uses_the_same_plugin(self):
        menu = apps.render_menu(MENU + [("Movies", "VideoPlayer", ICON + "VideoPlayer.png")])
        with self.assertRaisesRegex(apps.AppError, "also use the plugin"):
            self.plan("Video Player", purge=True, menu=menu)
        self.assertEqual(self.plan("Video Player", menu=menu).delete_dirs, [])  # menu-only is fine


def in_order(test, script, steps):
    """Each step must appear after the previous one."""
    position = 0
    for step in steps:
        found = script.find(step, position)
        test.assertNotEqual(found, -1, f"{step!r} missing or out of order")
        position = found + len(step)


class Scripts(unittest.TestCase):
    def job(self, **params):
        base = {"app": "Video Player", "expected_len": 812, "new_len": 790, "delete_dirs": [],
                "delete_files": [], "executables": []}
        return Job(SERIAL, "rm", params={**base, **params})

    def test_order_payload_busy_compare_backup_copy_verify_phase_then_deletes(self):
        script = removal_script(self.job(delete_dirs=["/SyncExtendedPack/Apps/Media/VideoPlayer/"],
                                         delete_files=["/windows/VideoPlayer.dll"],
                                         executables=["Media.exe"]))
        steps = ("FileSize(exp) <> 812", "FileSize(new) <> 790", 'ProcExists("Media.exe")',
                 "If (ReadFile(xml) ne ReadFile(exp))", 'Copy(xml, bk & "\\SyncApps.xml", TRUE)',
                 'If (ReadFile(bk & "\\SyncApps.xml") ne ReadFile(exp))', "  Copy(new, xml, TRUE)",
                 "  If (ReadFile(xml) ne ReadFile(new))", "    Copy(exp, xml, TRUE)",
                 'WriteFile("\\SyncExtendedPack\\_s2am\\phase',
                 'DelTree("\\SyncExtendedPack\\Apps\\Media\\VideoPlayer")',
                 'Delete("\\windows\\VideoPlayer.dll")')
        in_order(self, script, steps)

    def test_resume_branch_checks_the_new_menu_before_deleting(self):
        script = removal_script(self.job(delete_files=["/windows/VideoPlayer.dll"]))
        resume = script.index('If (FileExists("\\SyncExtendedPack\\_s2am\\phase')
        self.assertLess(resume, script.index("If (ReadFile(xml) ne ReadFile(new))"))
        self.assertLess(script.index("If (ReadFile(xml) ne ReadFile(new))"), script.index("Delete("))

    def test_menu_only_script_deletes_nothing(self):
        self.assertNotRegex(removal_script(self.job()), r"\b(DelTree|RmDir|Delete)\(")

    def test_blocks_balanced_and_errors_silenced(self):
        for script in (removal_script(self.job(executables=["a.exe"])),
                       undo_script(Job(SERIAL, "undo", params={"target": "20261030-120000-rm-abcd",
                                                               "expected_len": 700}))):
            words = re.findall(r"^\s*(If|EndIf)\b", script, re.M)
            self.assertEqual(words.count("If"), words.count("EndIf"))
            self.assertEqual(script.splitlines()[1], 'ErrorLevel("off")')

    def test_undo_compares_contents_and_restores_on_a_bad_copy(self):
        script = undo_script(Job(SERIAL, "undo", params={"target": "20261030-120000-rm-abcd",
                                                         "expected_len": 700}))
        in_order(self, script, ("If (ReadFile(xml) ne ReadFile(exp))", "Copy(bk, xml, TRUE)",
                                "If (ReadFile(xml) ne ReadFile(bk))", "  Copy(exp, xml, TRUE)"))

    def test_bad_params_are_refused(self):
        for params in ({"expected_len": 0}, {"new_len": "790"}, {"delete_files": ['/windows/a".dll']}):
            with self.subTest(params), self.assertRaises(ValueError):
                removal_script(self.job(**params))
        with self.assertRaises(ValueError):
            undo_script(Job(SERIAL, "undo", params={"target": "../x", "expected_len": 5}))

    def test_menu_changing_jobs_restart_sync(self):
        self.assertIn("NEED_REBOOT=True", meta(self.job()).decode("utf-16-le"))
        self.assertNotIn("NEED_REBOOT", meta(Job(SERIAL, "inv")).decode("utf-16-le"))


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(unittest.TestCase):
    """inventory -> remove (menu only) -> undo, and inventory -> remove --purge, on a fake car."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put("\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\Media.exe", b"v" * 50)
        self.car.put("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\AutoKit.exe", b"a" * 60)
        self.car.put("\\SyncExtendedPack\\Apps\\Tools\\SyncAppsRunner.exe", b"r" * 9)
        self.car.put("\\Windows\\VideoPlayer.dll", b"p" * 4)
        self.car.put("\\8inchSkins\\Ford\\Sync\\Apps\\Info\\SyncApps\\Icons\\VideoPlayer.png", b"i")
        self.car.put(MENU_XML, apps.render_menu(MENU))
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
        code, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        return job, out, imported

    def menu_names(self):
        return [n for n, _, _ in apps.menu_entries(self.car._resolve(MENU_XML).read_bytes()) if n]

    def test_remove_then_undo_restores_the_menu(self):
        self.run_job("inventory")
        removed, plan, imported = self.run_job("remove", "Video Player")
        self.assertIn("files stay on the car", plan)
        self.assertIn("verified: 'Video Player' is no longer in the menu", imported)
        self.assertNotIn("Video Player", self.menu_names())
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\Media.exe"))

        _, _, imported = self.run_job("undo", removed.id)
        self.assertIn("verified: 'Video Player' is back in the menu", imported)
        self.assertEqual(self.menu_names()[0], "Video Player")

    def test_purge_deletes_files_but_not_shared_tools(self):
        self.run_job("inventory")
        _, plan, imported = self.run_job("remove", "Video Player", "--purge")
        self.assertIn("delete folder /SyncExtendedPack/Apps/Media/VideoPlayer/", plan)
        self.assertIn("applied", imported)
        self.assertFalse(self.car.exists("\\SyncExtendedPack\\Apps\\Media\\VideoPlayer"))
        self.assertFalse(self.car.exists("\\Windows\\VideoPlayer.dll"))
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Tools\\SyncAppsRunner.exe"))
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\AutoKit.exe"))

    def test_stale_menu_changes_nothing(self):
        self.run_job("inventory")
        self.car.put(MENU_XML, apps.render_menu(MENU + [("New", "NewPlugin", "")]))  # changed since
        _, _, imported = self.run_job("remove", "Video Player", "--purge")
        self.assertIn("stale", imported)
        self.assertIn("Video Player", self.menu_names())
        self.assertTrue(self.car.exists("\\SyncExtendedPack\\Apps\\Media\\VideoPlayer\\Media.exe"))

    def test_running_app_is_not_purged(self):
        self.run_job("inventory")
        self.car.running.add("media.exe")
        _, _, imported = self.run_job("remove", "Video Player", "--purge")
        self.assertIn("busy", imported)
        self.assertIn("Video Player", self.menu_names())

    def test_dry_run_builds_nothing(self):
        self.run_job("inventory")
        code, out = self.cli("job", "remove", "AutoKit", "--purge", "--dry-run", "--serial", SERIAL,
                             "--work", str(self.tmp / "dry"))
        self.assertEqual(code, 0, out)
        self.assertIn("delete folder /SyncExtendedPack/Apps/Media/AutoKit/", out)
        self.assertFalse((self.tmp / "dry").exists())

    def test_remove_needs_a_report_first(self):
        code, out = self.cli("job", "remove", "AutoKit", "--serial", SERIAL, "--no-pack",
                             "--work", str(self.tmp / "x"))
        self.assertEqual(code, 1)
        self.assertIn("run an inventory job first", out)

    def test_undo_only_for_applied_remove_jobs(self):
        inventory, _, _ = self.run_job("inventory")
        code, out = self.cli("job", "undo", inventory.id, "--serial", SERIAL, "--no-pack",
                             "--work", str(self.tmp / "u"))
        self.assertEqual(code, 1)
        self.assertIn("not an applied remove job", out)

    def test_same_size_but_different_menu_is_stale(self):
        self.run_job("inventory")
        before = self.car._resolve(MENU_XML).read_bytes()
        swapped = apps.render_menu([("Video Plaxer", "VideoPlayer", ICON + "VideoPlayer.png")] + MENU[1:])
        self.assertEqual(len(swapped), len(before))  # same size, different content
        self.car.put(MENU_XML, swapped)
        _, _, imported = self.run_job("remove", "Video Player", "--purge")
        self.assertIn("stale", imported)
        self.assertTrue(self.car.exists("\\Windows\\VideoPlayer.dll"))

    def test_codex_lineage_case_stale_undo_cannot_resurrect_a_purged_entry(self):
        # remove AutoKit -> undo -> purge Video Player -> undo the AutoKit removal again
        self.run_job("inventory")
        removed, _, _ = self.run_job("remove", "AutoKit")
        self.run_job("undo", removed.id)
        self.run_job("remove", "Video Player", "--purge")
        code, out = self.cli("job", "undo", removed.id, "--serial", SERIAL, "--no-pack",
                             "--work", str(self.tmp / "again"))
        self.assertEqual(code, 1)
        self.assertIn("already undone", out)
        # Even an undo built behind the Mac's back is stopped by the car's content check.
        expected = (Store().report(SERIAL, removed.id) / "SyncApps.xml").read_bytes()
        stale = Job(SERIAL, "undo", params={"target": removed.id, "app": "AutoKit",
                                            "expected_len": len(expected)})
        work = stage(stale, UPSTREAM, self.tmp / "stale-undo", {"SyncApps.xml.expected": expected})
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", stale, require_volume=False)
        self.car.insert(self.stick, work, stale)
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn("stale", imported)
        self.assertNotIn("Video Player", self.menu_names())

    def test_silent_copy_failure_restores_the_menu_and_deletes_nothing(self):
        self.run_job("inventory")
        before = self.car._resolve(MENU_XML).read_bytes()
        self.car.broken_copies.add(MENU_XML.lower())
        _, _, imported = self.run_job("remove", "Video Player", "--purge")
        self.assertIn("failed", imported)
        self.car.broken_copies.clear()
        self.assertEqual(self.car._resolve(MENU_XML).read_bytes()[: len(before) // 2],
                         before[: len(before) // 2])
        self.assertTrue(self.car.exists("\\Windows\\VideoPlayer.dll"))

    def test_power_cut_after_menu_change_resumes_the_purge(self):
        self.run_job("inventory")
        self.car.power_cut_after_phase = True
        job, _, imported = self.run_job("remove", "Video Player", "--purge")
        self.assertIn("pending", imported)  # stick still carries install.bin
        self.assertNotIn("Video Player", self.menu_names())
        self.assertTrue(self.car.exists("\\Windows\\VideoPlayer.dll"))  # not yet deleted
        work = [w for w in self.tmp.glob("job*") if Job.from_json((w / "job.json").read_text()).id == job.id][0]
        self.car.insert(self.stick, work, job)  # same stick, next ignition
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn("applied", imported)
        self.assertFalse(self.car.exists("\\Windows\\VideoPlayer.dll"))


if __name__ == "__main__":
    unittest.main()
