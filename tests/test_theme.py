"""Tests for the reversible theme job: Lincoln colours on Ford's theme, restore, refusals."""
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

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, native, stick, theme  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import THEMES_CE, Job, meta, theme_script  # noqa: E402
from s2am.state import Store  # noqa: E402

HAVE_UPSTREAM = (ROOT.parent / "syncextpack" / "SyncExtPack").exists()
SERIAL = "XV31M13H"
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

    def test_no_drive_log_no_theme(self):
        shutil.rmtree(self.tmp / "home")
        code, out = self.cli("job", "theme", "--preset", "lincoln", "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)
        self.assertIn("logger --drive", out)


if __name__ == "__main__":
    unittest.main()
