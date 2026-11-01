"""Tests for the reversible theme job: Lincoln colours on Ford's theme, restore, refusals."""
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, native, stick, theme  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import (APPS_MENU_CE, THEMES_CE, Job, bundle_parts, bundle_script, meta, swap_script,  # noqa: E402
                      theme_script)
from s2am.state import Store  # noqa: E402

HAVE_UPSTREAM = (ROOT.parent / "syncextpack" / "SyncExtPack").exists()
SERIAL = "XV31M13H"
SCREEN = "Phone/PhoneHistory/PhoneHistory.swf"


def flash(version: int, body: bytes, compressed: bool = False) -> bytes:
    """A whole Flash file, as far as the jobs check: signature, version and the right length."""
    length = (8 + len(body)).to_bytes(4, "little")
    data = zlib.compress(body) if compressed else body
    return (b"CWS" if compressed else b"FWS") + bytes([version]) + length + data


MENU = flash(8, bytes(range(256)) * 80)  # SyncExtPack's SyncApps.swf, as far as the job can tell
HISTORY = flash(10, bytes(range(255, -1, -1)) * 60, compressed=True)  # Ford's call history screen
HISTORY_CE = "\\8inchSkins\\Ford\\Sync\\Apps\\Phone\\PhoneHistory\\PhoneHistory.swf"
FRAME = flash(10, bytes(range(256)) * 90, compressed=True)  # Ford's frame, which loads at start-up
FRAME_SCREEN = "AppConsole/AppConsole.swf"
FRAME_CE = "\\8inchSkins\\Ford\\Sync\\Apps\\AppConsole\\AppConsole.swf"
COLORS = {"Ford": ("0x966716", "0x45a180", "0xb3252a", "0x008cff"),
          "Lincoln": ("0x774732", "0x135D52", "0x78243E", "0x3B59A6")}


def theme_xml(brand: str) -> bytes:
    rows = [f'\t\t<AppType btnColor="{c}" dialogColor="{c}" dayColor="0x666666" nightColor="0x393939" />'
            f'\t<!-- {where} -->' for c, where in zip(("0x777777", *COLORS[brand]),
                                                     ("System", "TopLeft", "TopRight", "BottomLeft", "BottomRight"))]
    hidden = [f'\t\t<!-- <AppType btnColor="{c}" dialogColor="{c}" dayColor="0xEABA73" nightColor="0x392407" /> -->'
              for c in COLORS[brand]]
    return ("<XML>\r\n <Theme name=\"%s 8\">\r\n  <System>\r\n\t<AppTypes> \r\n%s\r\n%s\r\n\t</AppTypes>\r\n"
            "  </System>\r\n </Theme>\r\n</XML>\r\n" % (brand, "\r\n".join(rows), "\r\n".join(hidden))).encode()


def gradient(color: tuple) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (800, 240), color).save(out, "BMP")
    return out.getvalue()


def skin(brand: str) -> dict[str, bytes]:
    shade = 0 if brand == "Ford" else 90
    return {"Theme.XML": theme_xml(brand), "yellow.bmp": gradient((150, 103, shade)),
            "green.bmp": gradient((69, 161, shade)), "red.bmp": gradient((179, 37, shade)),
            "blue.bmp": gradient((shade, 140, 255))}


class Checks(unittest.TestCase):
    def test_check_refuses_files_sync_might_not_read(self):
        old = skin("Ford")
        theme.check("Theme.XML", theme_xml("Lincoln"), old["Theme.XML"])  # fine
        for name, data, why in (
                ("Theme.XML", b"<XML><Theme>", "not valid XML"),
                ("Theme.XML", theme_xml("Ford").replace(b"0xb3252a", b"red"), "is not 0xRRGGBB"),
                ("Theme.XML", theme_xml("Ford").replace(b'<AppType btnColor="0x008cff"', b'<Other x="1"'),
                 "AppType entries"),
                ("red.bmp", gradient((1, 2, 3))[:-10], "exactly the original"),
                ("red.bmp", b"PNG" + gradient((1, 2, 3))[3:], "exactly the original")):
            with self.subTest(why), self.assertRaisesRegex(theme.ThemeError, why):
                theme.check(name, data, old[name])

    def test_script_writes_only_the_theme_folder_the_backup_and_the_stick(self):
        files = {n: {"old": 10, "new": 10, "old_sha256": "a", "new_sha256": "b"} for n in theme.FILES}
        script = theme_script(Job(SERIAL, "theme", params={"files": files, "fetch": ["\\Windows\\bthcsr.dll"]}))
        for target in re.findall(r"Copy\([^,]+, ([^,]+), TRUE\)", script):
            self.assertRegex(target, r'^(th|bk|out|"\\SyncExtendedPack\\_s2am)')
        self.assertNotRegex(script, r"\b(Delete|DelTree|RmDir|RegWrite\w*|Run)\(")
        self.assertIn('ReadFile(th & "\\Theme.XML") ne ReadFile(jd & "\\old-Theme.XML")', script)
        self.assertIn("NEED_REBOOT=True", meta(Job(SERIAL, "theme")).decode("utf-16-le"))
        with self.assertRaises(ValueError):
            theme_script(Job(SERIAL, "theme", params={"files": {"Other.swf": files["Theme.XML"]}}))
        with self.assertRaises(ValueError):
            theme_script(Job(SERIAL, "theme", params={"files": files, "fetch": ["\\USB Disk\\x"]}))
        menu = {"SyncApps.swf": {"old": 9, "new": 9, "old_sha256": "a", "new_sha256": "b"}}
        script = swap_script(Job(SERIAL, "appmenu", params={"files": menu,
                                                              "added": {"Tiles\\AutoKitPlugin.png": {"new": 5}}}))
        self.assertIn('MkDir(th & "\\Tiles")', script)
        self.assertIn('Copy(jd & "\\add-Tiles_AutoKitPlugin.png", th & "\\Tiles\\AutoKitPlugin.png", TRUE)', script)
        self.assertNotRegex(script, r"\b(Delete|DelTree|RmDir|RegWrite\w*|Run)\(")
        for added in ({"..\\Windows\\x.png": {"new": 5}}, {"Tiles\\a.exe": {"new": 5}}):
            with self.assertRaises(ValueError):
                swap_script(Job(SERIAL, "appmenu", params={"files": menu, "added": added}))
        with self.assertRaises(ValueError):  # a theme job cannot touch the menu, nor the other way round
            swap_script(Job(SERIAL, "theme", params={"files": menu}))

    def test_bundle_script_queues_every_part_and_keeps_its_own_folder(self):
        files = {"PhoneHistory.swf": {"old": 9, "new": 10, "old_sha256": "a", "new_sha256": "b"}}
        screen = Job(SERIAL, "screen", params={"screen": SCREEN, "files": files})
        clean = Job(SERIAL, "clean")
        parts = [{"kind": j.kind, "id": j.id, "created_utc": j.created_utc, "params": j.params}
                 for j in (screen, clean)]
        bundle = Job(SERIAL, "bundle", params={"parts": parts})
        script = bundle_script(bundle)
        for part in (screen, clean):
            self.assertIn(f'WriteFile(stick & "\\s2am\\reports\\{part.id}\\queued.txt"', script)
        self.assertLess(script.index(screen.id + "\\queued.txt"), script.index('Copy(jd & "\\new-PhoneHistory.swf"'))
        self.assertIn(f'jd = "\\SyncExtendedPack\\_s2am\\jobs\\{bundle.id}"', script)  # the cleanup keeps it
        self.assertEqual(script.count("DelTree("), 1)
        self.assertIn("NEED_REBOOT=True", meta(bundle).decode("utf-16-le"))
        for wrong in ([{**parts[1]}, {**parts[0]}], [parts[0], parts[0]],
                      [{"kind": "rm", "id": parts[0]["id"].replace("screen", "rm"), "created_utc": screen.created_utc,
                        "params": {}}], []):
            with self.subTest(wrong), self.assertRaises(ValueError):
                bundle_parts(Job(SERIAL, "bundle", params={"parts": wrong}))

    def test_a_bundle_part_cut_short_reads_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            report, updater = Path(temp) / "report", Path(temp) / "SyncExtPack"
            report.mkdir()
            updater.mkdir()
            for marker, status in (("queued.txt", "not-run"), ("started.txt", "interrupted"),
                                   ("stale.txt", "stale"), ("done.txt", "applied")):
                (report / marker).write_text("x")  # each marker on top of the ones before
                self.assertEqual(stick._status(report, updater)[0], status, marker)

    def test_screen_script_writes_only_that_screens_folder(self):
        files = {"PhoneHistory.swf": {"old": 9, "new": 10, "old_sha256": "a", "new_sha256": "b"}}
        script = swap_script(Job(SERIAL, "screen", params={"screen": SCREEN, "files": files}))
        self.assertIn('th = "\\8inchSkins\\Ford\\Sync\\Apps\\Phone\\PhoneHistory"', script)
        for target in re.findall(r"Copy\([^,]+, ([^,]+), TRUE\)", script):
            self.assertRegex(target, r'^(th|bk|out)')
        self.assertNotRegex(script, r"\b(Delete|DelTree|RmDir|RegWrite\w*|Run)\(")
        self.assertIn("NEED_REBOOT=True", meta(Job(SERIAL, "screen")).decode("utf-16-le"))
        # the stick's copy of the backup is checked too, before the screen is touched
        self.assertLess(script.index('If (FileSize(out & "\\backup\\PhoneHistory.swf") <> 9)'),
                        script.index('Copy(jd & "\\new-PhoneHistory.swf"'))
        frame = {"AppConsole.swf": files["PhoneHistory.swf"]}
        self.assertIn('th = "\\8inchSkins\\Ford\\Sync\\Apps\\AppConsole"', swap_script(
            Job(SERIAL, "screen", params={"screen": "AppConsole/AppConsole.swf", "files": frame, "startup": True})))
        self.assertIn('orig-AppConsole.swf', swap_script(Job(SERIAL, "screen", params={
            "screen": "AppConsole/AppConsole.swf", "files": {"AppConsole.swf": 9}, "restore": "20261101-160854-screen-1ef7"})))
        for params in ({"screen": "AppConsole/AppConsole.swf", "files": frame},  # not planned with --startup
                       {"screen": "AppConsole/AppConsole.swf", "files": frame, "startup": "yes"},
                       {"screen": "Home/Home.swf", "files": {"Home.swf": files["PhoneHistory.swf"]}},
                       {"screen": "Phone/Phone.swf", "files": {"Phone.swf": files["PhoneHistory.swf"]}},
                       {"screen": "AppConsole/AppConsole.swf", "files": files},
                       {"screen": "../Phone/PhoneHistory/PhoneHistory.swf", "files": files},
                       {"screen": SCREEN, "files": {"Phone.swf": files["PhoneHistory.swf"]}},
                       {"screen": SCREEN, "files": files, "added": {"Tiles\\a.png": {"new": 5}}}):
            with self.subTest(params), self.assertRaises(ValueError):
                swap_script(Job(SERIAL, "screen", params=params))


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
        self.ford, self.lincoln = skin("Ford"), skin("Lincoln")
        for name in theme.FILES:
            self.car.put(f"{THEMES_CE}\\{name}", self.ford[name])
            self.car.put(f"\\8inchSkins\\Lincoln\\Sync\\Themes\\{name}", self.lincoln[name])
        self.car.put("\\Windows\\bthcsr.dll", b"MZ bluetooth")
        self.car.put(f"{APPS_MENU_CE}\\SyncApps.swf", MENU)
        self.car.put(HISTORY_CE, HISTORY)
        self.car.put(FRAME_CE, FRAME)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()
        self.drive_log()

    def drive_log(self):
        """What `logger --drive` leaves in the store: the skins copy and the file list."""
        report = self.tmp / "drive"
        for brand, files in (("Ford", self.ford), ("Lincoln", self.lincoln)):
            folder = report / "skins" / "8inchSkins" / brand / "Sync" / "Themes"
            folder.mkdir(parents=True)
            for name, data in files.items():
                (folder / name).write_bytes(data)
        (report / "files.txt").write_text("F|\\Windows\\bthcsr.dll|12\r\nF|\\Windows\\coredll.dll|9\r\n")
        menu = report / "skins" / "8inchSkins" / "Ford" / "Sync" / "Apps" / "Info" / "SyncApps"
        menu.mkdir(parents=True)
        (menu / "SyncApps.swf").write_bytes(MENU)
        screen = report / "skins" / "8inchSkins" / "Ford" / "Sync" / "Apps" / SCREEN
        screen.parent.mkdir(parents=True)
        screen.write_bytes(HISTORY)
        frame = report / "skins" / "8inchSkins" / "Ford" / "Sync" / "Apps" / FRAME_SCREEN
        frame.parent.mkdir(parents=True)
        frame.write_bytes(FRAME)
        store = Store()
        job = Job(SERIAL, "log", params={"seconds": 600, "drive": True})
        store.save_job(SERIAL, job.id, {**__import__("json").loads(job.to_json()), "status": "applied"})
        store.save_report(SERIAL, job.id, report)

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

    def car_theme(self) -> dict[str, bytes]:
        return {name: self.car._resolve(f"{THEMES_CE}\\{name}").read_bytes() for name in theme.FILES}

    def test_lincoln_colours_then_restore(self):
        job, work, imported = self.run_job("theme", "--preset", "lincoln", "--fetch", "\\Windows\\bt*.dll")
        self.assertIn("applied", imported)
        self.assertIn("verified: the new theme is on the car (5 files match byte for byte)", imported)
        now = self.car_theme()
        for name in theme.FILES[1:]:
            self.assertEqual(now[name], self.lincoln[name])
        self.assertIn(b'<Theme name="Ford 8">', now["Theme.XML"])  # the name stays
        self.assertIn(b'btnColor="0x774732"', now["Theme.XML"])
        self.assertIn(b'dayColor="0xEABA73"', now["Theme.XML"])  # Ford's hidden set is untouched
        report = Store().report(SERIAL, job.id)
        self.assertEqual((report / "fetched" / "Windows_bthcsr.dll").read_bytes(), b"MZ bluetooth")
        self.assertEqual((report / "backup" / "red.bmp").read_bytes(), self.ford["red.bmp"])
        self.assertIn("NEED_REBOOT=True", (work / "meta.txt").read_bytes().decode("utf-16-le"))

        _, _, imported = self.run_job("theme", "--restore", job.id)
        self.assertIn("verified: the original theme is back (5 files match byte for byte)", imported)
        self.assertEqual(self.car_theme(), self.ford)

    def test_own_theme_from_a_folder_changes_only_what_differs(self):
        folder = self.tmp / "night"
        folder.mkdir()
        (folder / "Theme.XML").write_bytes(theme_xml("Ford").replace(b"0x966716", b"0xD6A048"))
        (folder / "red.bmp").write_bytes(gradient((220, 76, 84)))
        (folder / "blue.bmp").write_bytes(self.ford["blue.bmp"])  # the same as the car's: left alone
        job, _, imported = self.run_job("theme", "--from", str(folder))
        self.assertIn("verified: the new theme is on the car (2 files match byte for byte)", imported)
        self.assertEqual(sorted(job.params["files"]), ["Theme.XML", "red.bmp"])
        self.assertEqual(self.car_theme()["green.bmp"], self.ford["green.bmp"])
        self.run_job("theme", "--restore", job.id)
        self.assertEqual(self.car_theme(), self.ford)

    def test_a_changed_car_theme_stops_the_job(self):
        self.car.put(f"{THEMES_CE}\\Theme.XML", theme_xml("Ford").replace(b"0x777777", b"0x123456"))
        before = self.car_theme()
        _, _, imported = self.run_job("theme", "--preset", "lincoln")
        self.assertIn("stale", imported)
        self.assertEqual(self.car_theme(), before)

    def test_a_copy_that_breaks_puts_the_backup_back_and_the_restore_stick_finishes(self):
        self.car.broken_copies.add(f"{THEMES_CE}\\red.bmp".lower())
        job, _, imported = self.run_job("theme", "--preset", "lincoln")
        self.assertIn("failed", imported)
        now = self.car_theme()
        for name in ("Theme.XML", "yellow.bmp", "green.bmp", "blue.bmp"):
            self.assertEqual(now[name], self.ford[name])  # put back at once
        self.assertNotEqual(now["red.bmp"], self.ford["red.bmp"])  # the broken one stays broken...
        self.car.broken_copies.clear()
        _, _, imported = self.run_job("theme", "--restore", job.id)  # ...until the restore stick
        self.assertIn("verified: the original theme is back", imported)
        self.assertEqual(self.car_theme(), self.ford)

    def test_restore_carries_the_originals_so_the_cars_backup_is_not_needed(self):
        job, _, _ = self.run_job("theme", "--preset", "lincoln")
        shutil.rmtree(self.car._resolve(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}"))
        _, work, imported = self.run_job("theme", "--restore", job.id)
        self.assertIn("verified: the original theme is back", imported)
        self.assertEqual(self.car_theme(), self.ford)
        folder = work / "payload" / Job.from_json((work / "job.json").read_text()).job_dir.lstrip("/")
        self.assertEqual((folder / "orig-red.bmp").read_bytes(), self.ford["red.bmp"])

    def test_a_job_that_started_once_does_not_run_again(self):
        work = self.tmp / "half"
        code, out = self.cli("job", "theme", "--preset", "lincoln", "--serial", SERIAL, "--no-pack",
                             "--work", str(work))
        self.assertEqual(code, 0, out)
        job = Job.from_json((work / "job.json").read_text())
        self.car.put(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}\\Theme.XML", b"half a run")
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.car.insert(self.stick, work, job)
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn("stale", imported)
        self.assertEqual(self.car_theme(), self.ford)

    def test_a_replayed_stick_gets_no_verdict(self):
        job, work, _ = self.run_job("theme", "--preset", "lincoln")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.car.insert(self.stick, work, job)
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn("nothing ran twice", imported)
        self.assertNotIn("verified", imported)

    def test_restore_refuses_originals_that_are_not_what_the_job_replaced(self):
        job, _, _ = self.run_job("theme", "--preset", "lincoln")
        drive = next(r for r in (self.tmp / "home").rglob("Ford/Sync/Themes"))
        (drive / "red.bmp").write_bytes(gradient((1, 2, 3)))
        code, out = self.cli("job", "theme", "--restore", job.id, "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("not what", out)

    def test_import_copies_contents_not_the_cars_file_flags(self):
        import errno
        job, work, _ = self.run_job("theme", "--preset", "lincoln", "--fetch", "\\Windows\\bt*.dll")
        refuse = OSError(errno.EPERM, "Operation not permitted")  # macOS on a read-only CE file's flags
        with mock.patch("os.chflags", side_effect=refuse):
            Store().save_report(SERIAL, job.id, self.stick / "s2am" / "reports" / job.id)
        report = Store().report(SERIAL, job.id)
        self.assertEqual((report / "fetched" / "Windows_bthcsr.dll").read_bytes(), b"MZ bluetooth")

    def tiles(self) -> Path:
        folder = self.tmp / "tiles"
        folder.mkdir(exist_ok=True)
        for name in ("AutoKitPlugin.png", "AutoKitPlugin-big.png", "AllApps.png"):
            out = io.BytesIO()
            Image.new("RGB", (155, 145), (30, 33, 40)).save(out, "PNG")
            (folder / name).write_bytes(out.getvalue())
        return folder

    def test_new_apps_menu_then_restore(self):
        swf = self.tmp / "SyncApps-tiles.swf"
        swf.write_bytes(flash(8, b"tiles" * 4000))
        job, work, imported = self.run_job("apps-menu", "--swf", str(swf), "--tiles", str(self.tiles()))
        self.assertIn("verified: the new Apps menu is on the car (4 files match byte for byte)", imported)
        self.assertEqual(self.car._resolve(f"{APPS_MENU_CE}\\SyncApps.swf").read_bytes(), swf.read_bytes())
        self.assertTrue(self.car.exists(f"{APPS_MENU_CE}\\Tiles\\AutoKitPlugin-big.png"))
        self.assertIn("NEED_REBOOT=True", (work / "meta.txt").read_bytes().decode("utf-16-le"))
        _, _, imported = self.run_job("apps-menu", "--restore", job.id)
        self.assertIn("verified: the original Apps menu is back (1 files match byte for byte)", imported)
        self.assertEqual(self.car._resolve(f"{APPS_MENU_CE}\\SyncApps.swf").read_bytes(), MENU)
        self.assertTrue(self.car.exists(f"{APPS_MENU_CE}\\Tiles\\AllApps.png"))  # left, unused

    def test_apps_menu_refuses_what_the_player_cannot_load(self):
        tiles = self.tiles()
        bad = self.tmp / "bad.swf"
        bad.write_bytes(b"<html>")
        code, out = self.cli("job", "apps-menu", "--swf", str(bad), "--tiles", str(tiles), "--serial", SERIAL,
                             "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("not a Flash file", out)
        good = self.tmp / "good.swf"
        good.write_bytes(flash(8, b"x" * 100))
        (tiles / "evil name.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        code, out = self.cli("job", "apps-menu", "--swf", str(good), "--tiles", str(tiles), "--serial", SERIAL,
                             "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("evil name.png", out)

    def test_cleanup_removes_old_job_folders_and_keeps_its_own_and_the_backups(self):
        job, _, _ = self.run_job("theme", "--preset", "lincoln")
        jobs = self.car._resolve(f"\\SyncExtendedPack\\_s2am\\jobs")
        self.assertTrue((jobs / job.id).is_dir())
        cleanup, _, imported = self.run_job("cleanup")
        self.assertIn("removed 1 old job folders", imported)
        self.assertEqual([p.name for p in jobs.iterdir()], [cleanup.id])
        self.assertTrue(self.car.exists(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}\\red.bmp"))
        script = (self.tmp / "job1" / "payload" / cleanup.job_dir.lstrip("/") / "s2amjob.mscr").read_text()
        self.assertIn(f'WriteFile(jd & "\\keep-{cleanup.id}"', script)
        self.assertIn('ForEach d in directories("\\SyncExtendedPack\\_s2am\\jobs\\*")', script)
        self.assertEqual(script.count("DelTree("), 1)

    def test_ford_screen_then_restore(self):
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        job, work, imported = self.run_job("screen", "--screen", SCREEN, "--swf", str(swf))
        self.assertIn("verified: the new screen is on the car (1 files match byte for byte)", imported)
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), swf.read_bytes())
        self.assertEqual((Store().report(SERIAL, job.id) / "backup" / "PhoneHistory.swf").read_bytes(), HISTORY)
        self.assertIn("NEED_REBOOT=True", (work / "meta.txt").read_bytes().decode("utf-16-le"))
        _, _, imported = self.run_job("screen", "--restore", job.id)
        self.assertIn("verified: the original screen is back (1 files match byte for byte)", imported)
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), HISTORY)

    def test_the_frame_needs_startup_and_its_undo_does_not(self):
        swf = self.tmp / "AppConsole.swf"
        swf.write_bytes(flash(10, b"flat buttons" * 2000, compressed=True))
        code, out = self.cli("job", "screen", "--screen", FRAME_SCREEN, "--swf", str(swf), "--serial", SERIAL,
                             "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("loads when SYNC starts", out)
        self.assertEqual(self.car._resolve(FRAME_CE).read_bytes(), FRAME)
        job, work, imported = self.run_job("screen", "--screen", FRAME_SCREEN, "--swf", str(swf), "--startup")
        self.assertIs(job.params["startup"], True)
        self.assertIn("verified: the new screen is on the car (1 files match byte for byte)", imported)
        self.assertEqual(self.car._resolve(FRAME_CE).read_bytes(), swf.read_bytes())
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), HISTORY)  # only the frame
        script = (work / "payload" / job.job_dir.lstrip("/") / "s2amjob.mscr").read_text()
        self.assertIn('th = "\\8inchSkins\\Ford\\Sync\\Apps\\AppConsole"', script)
        _, _, imported = self.run_job("screen", "--restore", job.id)
        self.assertIn("verified: the original screen is back (1 files match byte for byte)", imported)
        self.assertEqual(self.car._resolve(FRAME_CE).read_bytes(), FRAME)

    def test_a_bundle_cannot_carry_the_frame_without_startup(self):
        swf = self.tmp / "AppConsole.swf"
        swf.write_bytes(flash(10, b"flat buttons" * 2000, compressed=True))
        work = self.build("screen", "--screen", FRAME_SCREEN, "--swf", str(swf), "--startup")
        job = Job.from_json((work / "job.json").read_text())
        forged = Job(SERIAL, "screen", params={k: v for k, v in job.params.items() if k != "startup"})
        with self.assertRaisesRegex(ValueError, "--startup"):
            bundle_script(Job(SERIAL, "bundle", params={"parts": [
                {"kind": "screen", "id": forged.id, "created_utc": forged.created_utc, "params": forged.params}]}))

    def test_a_new_screen_as_long_as_fords_is_refused(self):
        body = bytearray(bytes(range(255, -1, -1)) * 60)
        for k in range(len(body)):  # a valid screen, not Ford's, exactly as long
            body[k] ^= 1
            same_length = flash(10, bytes(body), compressed=True)
            if len(same_length) == len(HISTORY) and same_length != HISTORY:
                break
            body[k] ^= 1
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(same_length)
        code, out = self.cli("job", "screen", "--screen", SCREEN, "--swf", str(swf), "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("exactly as long as Ford's", out)

    def test_screen_undo_still_builds_after_a_newer_drive_log(self):
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        job, _, _ = self.run_job("screen", "--screen", SCREEN, "--swf", str(swf))
        later = self.tmp / "later"  # a drive log taken after the change copies our screen
        (later / "skins" / "8inchSkins" / "Ford" / "Sync" / "Apps" / SCREEN).parent.mkdir(parents=True)
        (later / "skins" / "8inchSkins" / "Ford" / "Sync" / "Apps" / SCREEN).write_bytes(swf.read_bytes())
        log = Job(SERIAL, "log", params={"seconds": 600, "drive": True})
        Store().save_job(SERIAL, log.id, {**__import__("json").loads(log.to_json()), "status": "applied"})
        Store().save_report(SERIAL, log.id, later)
        _, _, imported = self.run_job("screen", "--restore", job.id)
        self.assertIn("verified: the original screen is back", imported)
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), HISTORY)

    def test_another_ford_version_of_the_same_size_is_caught_and_undone_to_itself(self):
        other = HISTORY[:-1] + bytes([HISTORY[-1] ^ 1])  # not what the Mac planned against, same size
        self.car.put(HISTORY_CE, other)
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        job, _, imported = self.run_job("screen", "--screen", SCREEN, "--swf", str(swf))
        self.assertIn("NOT verified: the backup on the stick is missing or differs", imported)
        _, _, imported = self.run_job("screen", "--restore", job.id)
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), other)  # what was really there

    def test_a_changed_car_screen_stops_the_screen_job(self):
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        self.car.put(HISTORY_CE, HISTORY + b"a newer Ford version")
        _, _, imported = self.run_job("screen", "--screen", SCREEN, "--swf", str(swf))
        self.assertIn("stale", imported)
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), HISTORY + b"a newer Ford version")

    def test_screen_job_refuses_what_it_should_not_do(self):
        for data, why in ((b"<html>", "not a Flash file"), (b"CWS\x0a", "not a Flash file"),
                          (flash(10, b"x" * 100, compressed=True)[:-3], "not a Flash file"),
                          (flash(8, b"x" * 100, compressed=True), "same version"),
                          (HISTORY, "the same as the car's")):
            swf = self.tmp / "new.swf"
            swf.write_bytes(data)
            code, out = self.cli("job", "screen", "--screen", SCREEN, "--swf", str(swf), "--serial", SERIAL,
                                 "--no-pack")
            with self.subTest(why):
                self.assertNotEqual(code, 0)
                self.assertIn(why, out)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):  # not on the list
            cli.main(["job", "screen", "--screen", "Home/Home.swf", "--swf", str(swf), "--serial", SERIAL])
        theme_job, _, _ = self.run_job("theme", "--preset", "lincoln")
        code, out = self.cli("job", "screen", "--restore", theme_job.id, "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("is not a screen job", out)

    def build(self, *args) -> Path:
        """Build a job without running it; returns its folder."""
        work = self.tmp / f"built{len(list(self.tmp.glob('built*')))}"
        code, out = self.cli("job", *args, "--serial", SERIAL, "--no-pack", "--work", str(work))
        self.assertEqual(code, 0, out)
        return work

    def run_built(self, work: Path, on=None) -> str:
        """Prepare, insert and import a built job, on the usual stick or another one (``on``)."""
        job, usb = Job.from_json((work / "job.json").read_text()), on or self.stick
        usb.mkdir(exist_ok=True)
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(usb, work / "install.bin", job, require_volume=False)
        self.car.insert(usb, work, job)
        return self.cli("stick", "import", str(usb), "--any-path")[1]

    def test_bundle_runs_its_parts_in_order_and_each_is_verified(self):
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        menu = self.tmp / "SyncApps-tiles.swf"
        menu.write_bytes(flash(8, b"tiles" * 4000))
        parts = [self.build("theme", "--preset", "lincoln"),
                 self.build("apps-menu", "--swf", str(menu), "--tiles", str(self.tiles())),
                 self.build("screen", "--screen", SCREEN, "--swf", str(swf)),
                 self.build("cleanup")]
        bundle = self.build("bundle", *[a for w in parts for a in ("--part", str(w))])
        imported = self.run_built(bundle)
        self.assertIn("verified: the new theme is on the car (5 files match byte for byte)", imported)
        self.assertIn("verified: the new Apps menu is on the car (4 files match byte for byte)", imported)
        self.assertIn("verified: the new screen is on the car (1 files match byte for byte)", imported)
        self.assertRegex(imported, r"bundle-[0-9a-f]{4}: applied")
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), swf.read_bytes())
        self.assertEqual(self.car._resolve(f"{APPS_MENU_CE}\\SyncApps.swf").read_bytes(), menu.read_bytes())
        jobs = self.car._resolve("\\SyncExtendedPack\\_s2am\\jobs")
        self.assertEqual([p.name for p in jobs.iterdir()], [Job.from_json((bundle / "job.json").read_text()).id])
        theme_id = Job.from_json((parts[0] / "job.json").read_text()).id
        self.assertTrue(self.car.exists(f"\\SyncExtendedPack\\_s2am\\backup\\{theme_id}\\red.bmp"))
        undo = self.build("bundle", "--part", str(self.build("theme", "--restore", theme_id)),
                          "--part", str(self.build("screen", "--restore",
                                                    Job.from_json((parts[2] / "job.json").read_text()).id)))
        imported = self.run_built(undo)
        self.assertIn("verified: the original theme is back", imported)
        self.assertIn("verified: the original screen is back", imported)
        self.assertEqual(self.car_theme(), self.ford)
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), HISTORY)

    def test_a_part_that_stops_ends_the_bundle(self):
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        parts = [self.build("theme", "--preset", "lincoln"),
                 self.build("screen", "--screen", SCREEN, "--swf", str(swf))]
        bundle = self.build("bundle", *[a for w in parts for a in ("--part", str(w))])
        self.car.put(f"{THEMES_CE}\\Theme.XML", theme_xml("Ford").replace(b"0x966716", b"0x111111"))
        imported = self.run_built(bundle)
        self.assertRegex(imported, r"theme-[0-9a-f]{4}: stale")
        self.assertRegex(imported, r"screen-[0-9a-f]{4}: not-run")
        self.assertRegex(imported, r"bundle-[0-9a-f]{4}: stopped")
        self.assertEqual(self.car._resolve(HISTORY_CE).read_bytes(), HISTORY)  # never reached

    def test_bundle_refuses_parts_it_should_not_hold(self):
        theme_part = self.build("theme", "--preset", "lincoln")
        clean = self.build("cleanup")
        for parts, why in (([clean, theme_part], "only be the last part"), ([theme_part, theme_part], "twice")):
            code, out = self.cli("job", "bundle", *[a for w in parts for a in ("--part", str(w))], "--serial", SERIAL,
                                 "--no-pack")
            with self.subTest(why):
                self.assertNotEqual(code, 0)
                self.assertIn(why, out)
        new = next(theme_part.rglob("new-red.bmp"))
        new.write_bytes(new.read_bytes()[:-1] + b"x")  # changed after it was built
        code, out = self.cli("job", "bundle", "--part", str(theme_part), "--serial", SERIAL, "--no-pack")
        self.assertIn("not the file", out)
        ran, _, _ = self.run_job("theme", "--preset", "lincoln")
        code, out = self.cli("job", "bundle", "--part", str(self.tmp / "job0"), "--serial", SERIAL, "--no-pack")
        self.assertIn("has run on the car already", out)

    def test_bundle_refuses_a_part_that_names_a_file_outside_its_folder(self):
        part = self.build("theme", "--preset", "lincoln")
        job = Job.from_json((part / "job.json").read_text())
        job.files["/8inchSkins/Ford/Sync/Apps/Info/SyncApps/SyncApps.xml"] = "0" * 64
        (part / "job.json").write_text(job.to_json())
        code, out = self.cli("job", "bundle", "--part", str(part), "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("outside its own folder", out)

    def test_bundle_refuses_a_part_that_differs_from_what_was_built(self):
        part = self.build("theme", "--preset", "lincoln")
        job = Job.from_json((part / "job.json").read_text())
        Store().save_job(SERIAL, job.id, {**__import__("json").loads(job.to_json()), "status": "built"})
        job.params["files"]["red.bmp"]["old_sha256"] = "0" * 64
        (part / "job.json").write_text(job.to_json())
        code, out = self.cli("job", "bundle", "--part", str(part), "--serial", SERIAL, "--no-pack")
        self.assertIn("is not what", out)

    def test_a_part_applied_from_another_stick_stays_applied(self):
        swf = self.tmp / "PhoneHistory.swf"
        swf.write_bytes(flash(10, b"our icons" * 1000, compressed=True))
        first, screen = self.build("theme", "--preset", "lincoln"), self.build("screen", "--screen", SCREEN,
                                                                                "--swf", str(swf))
        bundle = self.build("bundle", "--part", str(first), "--part", str(screen))
        self.run_built(screen, on=self.tmp / "other")  # the screen alone, from another stick first
        self.car.put(f"{THEMES_CE}\\Theme.XML", theme_xml("Ford").replace(b"0x966716", b"0x111111"))
        imported = self.run_built(bundle)  # the theme stops, so the bundle never reaches the screen
        self.assertIn("it is applied already, from another run", imported)
        screen_id = Job.from_json((screen / "job.json").read_text()).id
        self.assertEqual(Store().job(SERIAL, screen_id)["status"], "applied")
        self.assertTrue((Store().report(SERIAL, screen_id) / "backup" / "PhoneHistory.swf").is_file())

    def test_a_bundle_run_again_marks_its_parts_as_run_before(self):
        part = self.build("theme", "--preset", "lincoln")
        bundle = self.build("bundle", "--part", str(part))
        self.run_built(bundle)
        self.assertIn("inserted again", self.run_built(bundle))  # the same stick: its first reports
        imported = self.run_built(bundle, on=self.tmp / "fresh")  # a fresh stick: no reports yet
        self.assertRegex(imported, r"theme-[0-9a-f]{4}: already-applied")
        self.assertRegex(imported, r"bundle-[0-9a-f]{4}: already-applied")

    def test_no_drive_log_no_theme(self):
        shutil.rmtree(self.tmp / "home")
        code, out = self.cli("job", "theme", "--preset", "lincoln", "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("logger --drive", out)


if __name__ == "__main__":
    unittest.main()
