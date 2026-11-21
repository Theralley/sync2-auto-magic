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


class Drive(unittest.TestCase):
    """The plain-C helpers of s2amdrive.c (between "pure: begin" and "pure: end"), built for the Mac."""

    @classmethod
    def setUpClass(cls):
        source = (native.SOURCES / "s2amdrive.c").read_text()
        pure = source[source.index("/* pure: begin"):source.index("/* pure: end */")]
        program = "\n".join([
            "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>",
            "typedef unsigned int DWORD;", "typedef unsigned char BYTE;", "typedef int BOOL;",
            "#define TRUE 1", "#define FALSE 0", re.search(r"#define SHOT_EVERY_MS .*", source).group(), pure,
            "static int hex(int c) { return c <= '9' ? c - '0' : c - 'a' + 10; }",
            "int main(int argc, char **argv) {",
            "    if (argc > 1 && strcmp(argv[1], \"sha\") == 0) {",  # sha <file of hex data> <chunk size>
            "        FILE *in = fopen(argv[2], \"rb\"); char *text = malloc(400000); size_t n, i, step;",
            "        BYTE *data, digest[32]; Sha256 sha;",
            "        if (!in || !text) return 2;",
            "        n = fread(text, 1, 400000, in) / 2; fclose(in); step = (size_t)atoi(argv[3]);",
            "        data = malloc(n + 1);",
            "        for (i = 0; i < n; i++) data[i] = (BYTE)(hex(text[2 * i]) * 16 + hex(text[2 * i + 1]));",
            "        sha256_init(&sha);",
            "        for (i = 0; i < n; i += step) sha256_update(&sha, data + i, (DWORD)(n - i < step ? n - i : step));",
            "        sha256_final(&sha, digest);",
            "        for (i = 0; i < 32; i++) printf(\"%02x\", digest[i]);",
            "        printf(\"\\n\"); return 0;",
            "    }",
            "    if (argc > 1 && strcmp(argv[1], \"bmp\") == 0) {",  # a 5x3 picture, one red pixel
            "        int width = 5, height = 3, stride = (width * 3 + 3) & ~3; BYTE header[54], pixels[48];",
            "        FILE *out = fopen(argv[2], \"wb\");",
            "        memset(pixels, 0, sizeof(pixels)); pixels[2 * stride + 2] = 255;",  # bottom-up: top row
            "        bmp_header(header, width, height, stride);",
            "        fwrite(header, 1, 54, out); fwrite(pixels, 1, (size_t)(stride * height), out); fclose(out);",
            "        return 0;",
            "    }",
            "    if (argc > 1 && strcmp(argv[1], \"clock\") == 0) {",  # clock <rounds> <ticks apart> <per second>
            "        DWORD loops = (DWORD)strtoul(argv[2], NULL, 10), ticks = (DWORD)strtoul(argv[3], NULL, 10);",
            "        DWORD rate = (DWORD)strtoul(argv[4], NULL, 10);",
            "        printf(\"%u %d\\n\", loop_mhz(loops, ticks, rate), window_ok(ticks, rate)); return 0;",
            "    }",
            "    if (argc > 1 && strcmp(argv[1], \"sw1\") == 0) {",  # sw1 <register, hex>
            "        printf(\"%u\\n\", sw1_millivolts((DWORD)strtoul(argv[2], NULL, 16))); return 0;",
            "    }",
            "    if (argc > 1 && strcmp(argv[1], \"busy\") == 0) {",  # busy <delta> <delta> ...
            "        int i;",
            "        for (i = 2; i < argc; i++) note_busy((DWORD)i, (DWORD)atoi(argv[i]), i, 251, 0);",
            "        for (i = 0; i < busy_count; i++) printf(\"%u \", busy[i].delta);",
            "        printf(\"\\n\"); return 0;",
            "    }",
            "    {",
            "        BYTE frame[48 * 16]; BOOL black; DWORD a, b;",
            "        memset(frame, 0, sizeof(frame)); a = frame_hash(frame, 16, 16, 48, &black);",
            "        printf(\"%d \", black); frame[0] = 9; b = frame_hash(frame, 16, 16, 48, &black);",
            "        printf(\"%d %d\\n\", black, a != b);",
            # first; the same again; changed but not still; still; kept changing 30 s
            "        printf(\"%d %d %d %d %d\\n\", want_shot(1, 0, 0, FALSE, 0), want_shot(1, 1, 1, TRUE, 99999),",
            "               want_shot(2, 1, 1, TRUE, 1000), want_shot(2, 2, 1, TRUE, 1000),",
            "               want_shot(3, 2, 1, TRUE, SHOT_EVERY_MS));",
            "    }",
            "    return 0;", "}"])
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "drive.c").write_text(program)
        subprocess.run(["cc", "-Wall", "-Werror", "-o", str(cls.work / "drive"), str(cls.work / "drive.c")],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_helper(self, *args):
        return subprocess.run([str(self.work / "drive"), *args], check=True, capture_output=True,
                              text=True).stdout

    def test_load_keeps_the_eight_busiest_threads_in_order(self):
        self.assertEqual(self.run_helper("busy", "3", "9", "5").split(), ["9", "5", "3"])
        deltas = ["4", "1", "9", "2", "7", "6", "8", "3", "5", "10", "0"]
        self.assertEqual(self.run_helper("busy", *deltas).split(), ["10", "9", "8", "7", "6", "5", "4", "3"])

    def test_clock_comes_from_loops_cycles_and_the_counter(self):
        # 65 cycles a round: 8192 rounds in 887 ticks of a 1 MHz counter is 600 MHz, in 665 ticks 800 MHz
        # the long loop has 32 more adds a round than the short one, and the difference in time is
        # theirs alone: 16384 rounds, 874 ticks apart on a 1 MHz counter, is 600 MHz; 655 ticks, 800
        self.assertEqual(self.run_helper("clock", "16384", "874", "1000000").split(), ["599", "1"])
        self.assertEqual(self.run_helper("clock", "16384", "655", "1000000").split(), ["800", "1"])
        # a millisecond counter: 1048576 rounds, 56 ticks apart
        self.assertEqual(self.run_helper("clock", "1048576", "56", "1000").split(), ["599", "1"])
        self.assertEqual(self.run_helper("clock", "4096", "49", "1000").split()[1], "0")
        self.assertEqual(self.run_helper("clock", "4096", "400", "1000000").split()[1], "0")  # 0.4 ms
        self.assertEqual(self.run_helper("clock", "4096", "0", "1000000").split()[0], "0")
        # a fast counter must not overflow: 4096 rounds in 29000 ticks of 66.5 MHz
        self.assertEqual(self.run_helper("clock", "4096", "14500", "66500000").split(), ["601", "0"])
        self.assertEqual(self.run_helper("clock", "32768", "116000", "66500000").split(), ["601", "1"])

    def test_core_voltage_follows_the_mc13892_table(self):
        self.assertEqual(self.run_helper("sw1", "000000").strip(), "600")
        self.assertEqual(self.run_helper("sw1", "000014").strip(), "1100")   # code 20
        self.assertEqual(self.run_helper("sw1", "0003f2").strip(), "1050")   # other fields ignored
        self.assertEqual(self.run_helper("sw1", "80001f").strip(), "1375")   # SW1 has no high range

    def test_sha256_matches_python_at_every_block_edge(self):
        import hashlib
        for length in (0, 3, 55, 56, 63, 64, 65, 119, 1000, 70000):
            data = bytes((7 * i + length) % 256 for i in range(length))
            for step in (1, 7, 64, 32768):
                with self.subTest(length=length, step=step):
                    (self.work / "data.hex").write_text(data.hex())  # a file: Linux limits one argument to 128 KB
                    out = self.run_helper("sha", str(self.work / "data.hex"), str(step)).strip()
                    self.assertEqual(out, hashlib.sha256(data).hexdigest())

    def test_screenshot_header_gives_a_bmp_the_mac_opens_upright(self):
        from PIL import Image
        path = self.work / "shot.bmp"
        self.run_helper("bmp", str(path))
        with Image.open(path) as image:
            self.assertEqual(image.size, (5, 3))
            self.assertEqual(image.convert("RGB").getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(image.convert("RGB").getpixel((0, 2)), (0, 0, 0))

    def test_screenshots_are_taken_once_a_screen_settles(self):
        hashes, decisions = self.run_helper().splitlines()
        self.assertEqual(hashes, "1 0 1")  # all black, then not; a changed pixel changes the hash
        self.assertEqual(decisions.split(), ["1", "0", "0", "1", "1"])


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
