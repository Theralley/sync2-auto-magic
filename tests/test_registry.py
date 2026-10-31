"""Tests for the read-only registry job (the call sound): its script, s2amreg.c's plain-C helpers
built for the Mac, and a run on the simulated car."""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, native, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import REGISTRY_ROOTS, Job, registry_script  # noqa: E402

HAVE_UPSTREAM = (ROOT.parent / "syncextpack" / "SyncExtPack").exists()
SERIAL = "XV31M13H"


class Script(unittest.TestCase):
    def test_runs_the_reader_and_waits_a_limited_time(self):
        script = registry_script(Job(SERIAL, "reg", params={"roots": list(REGISTRY_ROOTS), "depth": 6}))
        self.assertIn('Run("\\SyncExtendedPack\\_s2am\\jobs\\', script)
        self.assertIn('\\s2amreg.exe", "6 HKLM\\Software,HKLM\\Comm,HKLM\\Drivers,HKLM\\Audio,HKLM\\System,HKCU\\ "'
                      ' & out)', script)
        self.assertIn("While (n < 90)", script)
        self.assertLess(script.index('If (FileExists(out & "\\registry-done.txt"))'), script.index("Run("))
        self.assertIn('If (FileExists(out & "\\registry-done.txt"))', script)
        self.assertNotRegex(script, r"\b(Delete|DelTree|RmDir|RegWrite\w*|RegDelete\w*|RunWait)\(")
        for target in re.findall(r"Copy\([^,]+, ([^,]+), TRUE\)", script):  # only the usual report, to the stick
            self.assertTrue(target.startswith("out"), target)

    def test_refuses_roots_and_depths_it_should_not_take(self):
        for roots, depth in ((["HKLM\\Soft ware"], 6), (["HKLM\\A;B"], 6), (["HKCR\\x"], 6), (["HKLM\\..\\x"], 6),
                             (['HKLM\\a"b'], 6), ([], 6), (["HKLM\\Software"], 9), (["HKLM\\Software"], True)):
            with self.subTest(roots=roots, depth=depth), self.assertRaises(ValueError):
                registry_script(Job(SERIAL, "reg", params={"roots": roots, "depth": depth}))


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Helpers(unittest.TestCase):
    """The plain-C helpers of s2amreg.c (between "pure: begin" and "pure: end"), built for the Mac."""

    @classmethod
    def setUpClass(cls):
        source = (native.SOURCES / "s2amreg.c").read_text()
        pure = source[source.index("/* pure: begin"):source.index("/* pure: end */")]
        defines = "\n".join(re.findall(r"#define (?:NAME_CHARS|SHOW_BYTES) .*", source))
        program = "\n".join([
            "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>", defines, pure,
            "int main(int argc, char **argv) {",
            "    char out[1024] = \"\"; unsigned char data[300]; int i;",
            "    if (strcmp(argv[1], \"secret\") == 0) { printf(\"%d\\n\", is_secret(argv[2])); return 0; }",
            "    if (strcmp(argv[1], \"clean\") == 0) { strcpy(out, argv[2]); clean(out); printf(\"%s\\n\", out);"
            " return 0; }",
            "    if (strcmp(argv[1], \"hex\") == 0) { int n = atoi(argv[2]); for (i = 0; i < n; i++)"
            " data[i] = (unsigned char)i; add_hex(out, sizeof(out), data, (unsigned long)n); printf(\"%s\\n\", out);"
            " return 0; }",
            "    if (strcmp(argv[1], \"withheld\") == 0) { printf(\"%d\\n\", withheld(argv[2], argv[3],"
            " (unsigned long)atoi(argv[4]), (unsigned long)atoi(argv[5]))); return 0; }",
            "    printf(\"%s %s %s\\n\", type_name(1), type_name(4), type_name(99)); return 0;", "}"])
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "reg.c").write_text(program)
        subprocess.run(["cc", "-Wall", "-Werror", "-o", str(cls.work / "reg"), str(cls.work / "reg.c")],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_helper(self, *args):
        return subprocess.run([str(self.work / "reg"), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def test_secrets_are_recognised_by_name(self):
        for name, secret in (("key", "1"), ("LinkKey", "1"), ("PIN", "1"), ("Passphrase", "1"),
                             ("NetworkKey", "1"), ("Version", "0"), ("AudioRoute", "0"), ("", "0")):
            with self.subTest(name=name):
                self.assertEqual(self.run_helper("secret", name), secret)

    def test_a_link_key_stays_on_the_car_whatever_it_is_called(self):
        for key, name, kind, size, kept in (
                ("HKLM\\Software\\Microsoft\\Bluetooth\\LinkKeys\\x", "Data", "3", "16", "1"),  # the key's path
                ("HKLM\\Software\\Microsoft\\Bluetooth\\Device\\x", "Data", "3", "16", "1"),  # binary over 8
                ("HKLM\\Comm\\Wifi", "NetworkKey", "1", "20", "1"),  # the name
                ("HKLM\\Audio", "Mask", "3", "4", "0"), ("HKLM\\Audio", "Version", "4", "4", "0"),
                ("HKLM\\Software\\Microsoft\\Bluetooth\\HandsFree", "Features", "4", "4", "0")):
            with self.subTest(key=key, name=name):
                self.assertEqual(self.run_helper("withheld", key, name, kind, size), kept)

    def test_text_keeps_one_field_and_hex_stops_at_256_bytes(self):
        self.assertEqual(self.run_helper("clean", "a|b\tc"), "a?b?c")
        self.assertEqual(self.run_helper("hex", "3"), "000102")
        long = self.run_helper("hex", "300")
        self.assertTrue(long.endswith(" ...(300 bytes)"))
        self.assertEqual(len(long.split(" ")[0]), 512)
        self.assertEqual(self.run_helper("types"), "sz dword other")


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
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def test_registry_job_copies_the_settings_without_secrets(self):
        work = self.tmp / "job"
        code, out = self.cli("job", "registry", "--serial", SERIAL, "--no-pack", "--work", str(work))
        self.assertEqual(code, 0, out)
        self.assertIn("link key and PINs are not copied", out)
        job = Job.from_json((work / "job.json").read_text())
        self.assertTrue((work / "payload" / job.job_dir.lstrip("/") / "s2amreg.exe").is_file())
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.car.insert(self.stick, work, job)
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn("T, complete, 2 keys, 3 values, 1 not copied", imported)
        code, out = self.cli("job", "registry", "--root", "HKLM\\Soft ware", "--serial", SERIAL, "--no-pack")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
