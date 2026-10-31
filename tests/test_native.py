"""Tests for the native WinCE helpers: binary checks, source/AutoKit agreement, jobs."""
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

from s2am import apps, cli, native, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import MENU_XML, Job, hello_script, logger_script  # noqa: E402

AUTOKIT = ROOT.parent / "syncextpack" / "FullPack" / "SyncExtendedPack" / "Apps" / "Media" / "AutoKit"
HAVE_UPSTREAM = (AUTOKIT / "AutoKit.exe").exists()
BUILT = ROOT / "build" / "native"
SERIAL = "XV31M13H"


class Check(unittest.TestCase):
    @unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
    def test_refuses_binaries_needing_more_than_coredll(self):
        for name in ("AutoKit.exe", "libRRAudio.dll"):
            with self.subTest(name), self.assertRaisesRegex(native.NativeError, "imports"):
                native.check((AUTOKIT / name).read_bytes(), name)

    def test_refuses_non_pe(self):
        with self.assertRaises(native.NativeError):
            native.check(b"not a program")

    @unittest.skipUnless((BUILT / "hello.exe").exists(), "run `s2am native build` first")
    def test_built_programs_pass(self):
        for name in native.PROGRAMS:
            native.check((BUILT / name).read_bytes(), name)

    @unittest.skipUnless(os.environ.get("S2AM_DOCKER_TESTS") == "1", "set S2AM_DOCKER_TESTS=1")
    def test_build_in_docker(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        built = native.build(out)
        self.assertEqual(set(built), set(native.PROGRAMS))


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Sources(unittest.TestCase):
    def test_notifylog_listens_for_every_uigear_message_autokit_uses(self):
        found = set()
        for name in ("AutoKit.exe", "Uigeardll2.dll"):
            data = (AUTOKIT / name).read_bytes()
            for match in re.finditer(rb"(?:[\x20-\x7e]\x00){6,}", data):
                text = match.group().decode("utf-16le")
                if re.fullmatch(r"_UIGEAR_[A-Z0-9_]+_", text):
                    found.add(text)
        source = (native.SOURCES / "notifylog.c").read_text()
        listed = set(re.findall(r'L"(_UIGEAR_[A-Z0-9_]+_)"', source))
        self.assertEqual(listed, found)


class Scripts(unittest.TestCase):
    def test_hello_waits_for_the_program(self):
        script = hello_script(Job(SERIAL, "hello"))
        self.assertRegex(script, r'RunWait\(".*\\hello\.exe", out & "\\native-hello\.txt"\)')

    def test_native_logger_runs_in_the_background_with_its_duration(self):
        script = logger_script(Job(SERIAL, "log", params={"seconds": 120, "native": True}))
        self.assertIn('\\notifylog.exe", "120 " & out & "\\notify.txt")', script)
        self.assertNotIn("RunWait", script)
        plain = logger_script(Job(SERIAL, "log", params={"seconds": 120}))
        self.assertNotIn("notifylog", plain)

    def test_watcher_only_looks(self):
        """It may ask AutoKit's window for nothing but WM_NULL, and never changes the car."""
        source = (native.SOURCES / "s2amwatch.c").read_text()
        code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith(("*", "/*")))
        for call in ("GetWindowText", "PostMessage", "TerminateProcess", "DeleteFile", "RegSetValue",
                     "RegCreateKey", "RegDeleteKey", "ShowWindow", "SetForegroundWindow", "SetEvent",
                     "MoveFile", "CreateProcess"):
            self.assertNotIn(call, code, call)
        self.assertEqual(re.findall(r"SendMessageW\(([^,]+),\s*(\w+)", code), [("(HWND)window", "WM_NULL")])
        self.assertIn("CopyFileW(copies[i][0], target", code)  # copies only to the stick

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
    def test_watcher_keeps_every_run_of_a_log(self):
        """copy_number and copy_path from s2amwatch.c, built for the Mac, fed the sizes of
        AutoKit's hwlog.log as the watcher saw them in the car on 2026-10-30."""
        source = (native.SOURCES / "s2amwatch.c").read_text()

        def function(name):
            start = source.rindex("\n", 0, source.index(f" {name}(")) + 1
            return source[start:source.index("\n}\n", start) + 3]
        sizes = [348, 474, 122, 226, 348, 120, 224, 346, 122, 19002, 146914, 258768, 122, 226, 348, 474, 122]
        program = "\n".join([
            "#include <stdio.h>", "#include <wchar.h>", "typedef wchar_t WCHAR;", "typedef int BOOL;",
            "typedef unsigned long DWORD;", "#define TRUE 1", "#define FALSE 0", "#define MAX_PATH 260",
            re.search(r"#define MAX_COPIES .*", source).group(), "static WCHAR folder[MAX_PATH] = L\"\\\\out\";",
            function("copy_number"), function("copy_path"),
            "int main(void) {",
            f"    DWORD sizes[] = {{{', '.join(map(str, sizes))}}};",
            "    DWORD copied = 0; int newest = 0; unsigned i; WCHAR target[MAX_PATH];",
            "    for (i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {",
            "        newest = copy_number(newest, sizes[i], copied); copied = sizes[i];",
            "        printf(\"%d \", newest);",
            "    }",
            "    copy_path(target, L\"autokit-hwlog-live\", newest, L\".log\"); printf(\"\\n%ls\\n\", target);",
            "    printf(\"%d %d %d\\n\", copy_number(98, 1, 2), copy_number(99, 1, 2), copy_number(99, 5, 2));",
            "    wmemset(folder, L'x', 250); folder[250] = 0;",
            "    printf(\"%d\\n\", copy_path(target, L\"autokit-hwlog-live\", 1, L\".log\"));",
            "    return 0;", "}"])
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work)
        (work / "copies.c").write_text(program)
        subprocess.run(["cc", "-Wall", "-Werror", "-o", str(work / "copies"), str(work / "copies.c")],
                       check=True, capture_output=True)
        out = subprocess.run([str(work / "copies")], check=True, capture_output=True, text=True).stdout
        numbers, name, cap, fits = out.splitlines()
        # each time the log starts over (it shrank) the next copy begins; the 258 KB run is copy 4
        self.assertEqual(numbers.split(), "1 1 2 2 2 3 3 3 4 4 4 4 5 5 5 5 6".split())
        self.assertEqual(name, "\\out\\autokit-hwlog-live-06.log")
        self.assertEqual(cap, "99 99 99")  # past 99 the last copy is overwritten
        self.assertEqual(fits, "0")


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
        self.car.put(MENU_XML, apps.render_menu([("", "", "")]))
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
        self.imported = self.cli("stick", "import", str(self.stick), "--any-path")[1]
        return job, work

    def test_native_hello_ships_the_program_and_reports(self):
        job, work = self.run_job("native-hello")
        self.assertIn("verified: native code runs on this SYNC 2 (wince 7.0 build 3500)", self.imported)
        self.assertEqual((work / "payload" / job.job_dir.lstrip("/") / "hello.exe").read_bytes(),
                         b"MZ stand-in")
        self.assertIn("s2am native hello ok", self.cli("report", "--serial", SERIAL, job.id)[1])

    def test_native_logger_report_shows_window_messages(self):
        job, work = self.run_job("logger", "--native", "--seconds", "60")
        self.assertTrue((work / "payload" / job.job_dir.lstrip("/") / "notifylog.exe").is_file())
        self.assertTrue((work / "payload" / job.job_dir.lstrip("/") / "s2amwatch.exe").is_file())
        report = self.cli("report", "--serial", SERIAL, job.id)[1]
        self.assertIn("REG|_UIGEAR_BOX_NOTIFY_", report)


if __name__ == "__main__":
    unittest.main()
