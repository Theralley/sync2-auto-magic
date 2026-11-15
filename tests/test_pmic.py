"""The existing PMIC driver's read-only voltage-preset diagnostic."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, native, pmic, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import Job, pmic_script  # noqa: E402

SERIAL = "XV31M13H"

# Compile the actual application against an API shim: no car hardware is touched.
WINDOWS = r'''
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD;
typedef void *HANDLE;
typedef void *HINSTANCE;
typedef wchar_t WCHAR;
typedef wchar_t *LPWSTR;
#define WINAPI
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define MAX_PATH 260
#define GENERIC_READ 0x80000000U
#define GENERIC_WRITE 0x40000000U
#define FILE_SHARE_READ 1
#define FILE_SHARE_WRITE 2
#define CREATE_ALWAYS 2
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 128
#define FILE_FLAG_RANDOM_ACCESS 0x10000000U
HANDLE CreateFileW(const WCHAR *, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
int WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
int FlushFileBuffers(HANDLE);
int CloseHandle(HANDLE);
DWORD GetLastError(void);
int DeviceIoControl(HANDLE, DWORD, void *, DWORD, void *, DWORD, DWORD *, void *);
'''

SHIM = r'''
#include "windows.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
static const char *mode;
static int files;
static const HANDLE device = (HANDLE)(intptr_t)1;
HANDLE CreateFileW(const WCHAR *path, DWORD access, DWORD share, void *security,
                   DWORD disposition, DWORD attributes, HANDLE template) {
    char local[1024]; size_t i;
    if (!wcscmp(path, L"PMI1:")) {
        assert(access == (GENERIC_READ | GENERIC_WRITE));
        assert(share == (FILE_SHARE_READ | FILE_SHARE_WRITE));
        assert(disposition == OPEN_EXISTING && attributes == FILE_FLAG_RANDOM_ACCESS);
        return !strcmp(mode, "openfail") ? INVALID_HANDLE_VALUE : device;
    }
    assert(access == GENERIC_WRITE && disposition == CREATE_ALWAYS);
    if (++files == 2 && !strcmp(mode, "donefail")) return INVALID_HANDLE_VALUE;
    for (i=0; path[i]; i++) local[i] = path[i] == L'\\' ? '/' : (char)path[i];
    local[i]=0;
    FILE *f=fopen(local,"wb");
    return f ? (HANDLE)f : INVALID_HANDLE_VALUE;
}
int WriteFile(HANDLE f, const void *data, DWORD n, DWORD *done, void *unused) {
    if (!strcmp(mode, "writefail")) { *done=0; return 0; }
    if (!strcmp(mode, "shortwrite") && n>1) n=1;
    *done=(DWORD)fwrite(data,1,n,(FILE *)f); return *done==n;
}
int FlushFileBuffers(HANDLE f) { return fflush((FILE *)f)==0; }
int CloseHandle(HANDLE f) {
    if (f==device) { puts("closed device"); return 1; }
    return fclose((FILE *)f)==0;
}
DWORD GetLastError(void) { return 5; }
int DeviceIoControl(HANDLE f, DWORD code, void *in, DWORD in_size, void *out,
                    DWORD out_size, DWORD *returned, void *overlapped) {
    DWORD index=*(DWORD *)in;
    assert(f==device && code==0x00224000 && in_size==4 && out_size==4);
    assert(!returned && !overlapped && (index==7 || index==24));
    printf("read %u\n", index);
    if ((index==7 && !strcmp(mode,"read7fail")) ||
        (index==24 && !strcmp(mode,"read24fail"))) return 0;
    if (!strcmp(mode,"noop")) return 1;
    *(DWORD *)out = index==7 ? 0x41d1 : 14672;
    if (index==7 && !strcmp(mode,"badid")) *(DWORD *)out=0x40c1;
    if (index==7 && !strcmp(mode,"wrongcode")) *(DWORD *)out=0x61d1;
    if (index==24 && !strcmp(mode,"wide24")) *(DWORD *)out=0x1000000;
    return 1;
}
int WinMain(HINSTANCE, HINSTANCE, LPWSTR, int);
int main(int argc, char **argv) {
    WCHAR path[1024]; size_t i;
    assert(argc==3); mode=argv[2];
    for (i=0; argv[1][i]; i++) path[i]=(WCHAR)argv[1][i]; path[i]=0;
    return WinMain(NULL,NULL,path,0);
}
'''


class Script(unittest.TestCase):
    def test_pmic_job_is_available(self):
        self.assertIn("pmic", cli.JOB_KINDS)

    def test_job_waits_boundedly_and_does_not_change_settings(self):
        script = pmic_script(Job(SERIAL, "pmic"))
        self.assertIn("While (n < 15)", script)
        self.assertIn('\\s2ampmic.exe", out)', script)
        self.assertIn('FileExists(out & "\\pmic-done.txt")', script)
        self.assertNotRegex(script, r"\b(RegWrite\w*|RegDelete\w*|RunWait|Reset|Kill)\(")

    def test_interrupted_job_preserves_an_existing_native_completion(self):
        script = pmic_script(Job(SERIAL, "pmic"))
        self.assertRegex(script, r'If \(FileExists\(out & "\\pmic-done.txt"\)\)\r?\n'
                                r'  n = 15\r?\nElse\(\)\r?\n  Run\([^\n]+s2ampmic.exe[^\n]+\r?\nEndIf\(\)')


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "shim.c").write_text(SHIM)
        cls.program = cls.work / "pmic"
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                        "-I", str(cls.work), str(native.SOURCES / "s2ampmic.c"), str(cls.work / "shim.c"),
                        "-o", str(cls.program)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def sample(self, mode):
        folder = Path(tempfile.mkdtemp(dir=self.work))
        result = subprocess.run([str(self.program), str(folder), mode], capture_output=True, text=True)
        log = (folder / "pmic.txt").read_text() if (folder / "pmic.txt").exists() else ""
        done = (folder / "pmic-done.txt").read_text() if (folder / "pmic-done.txt").exists() else ""
        return result, log, done

    def test_valid_identity_reads_only_two_registers_and_decodes_all_presets(self):
        result, log, done = self.sample("ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["read 7", "read 24", "closed device"])
        for preset, mv in (("normal", 1000), ("DVS", 850), ("standby", 950)):
            self.assertIn(f"V|SW1 {preset} preset mV|{mv}\n", log)
        self.assertIn("active voltage, CPU rail mapping and temperature remain unknown", log)
        self.assertEqual(done, "T|complete\n")
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp)
            (report / "pmic.txt").write_text(log)
            (report / "pmic-done.txt").write_text(done)
            self.assertEqual(pmic.summary(report), "SW1 presets: normal 1000 mV, DVS 850 mV, standby 950 mV; "
                                                  "active rail voltage remains unknown")
            for bad in ("", log.replace("1000", "1100"), log.replace("R|7|16849", "R|7|0"),
                        log.replace("T|complete", "T|unavailable"), log + "x" * 4097):
                with self.subTest(bad=bad[:80]):
                    (report / "pmic.txt").write_text(bad)
                    self.assertIn("NOT verified", pmic.summary(report))
            (report / "pmic.txt").unlink()
            self.assertIn("NOT verified", pmic.summary(report))
            (report / "pmic.txt").write_text(log)
            (report / "pmic-done.txt").write_text("T|complete" + " " * 118 + "\nT|unavailable\n")
            self.assertIn("NOT complete", pmic.summary(report))

    def test_parser_reports_unavailable_and_missing_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp)
            self.assertIn("NOT complete", pmic.summary(report))
            (report / "pmic-done.txt").write_text("T|unavailable\n")
            self.assertIn("PMIC unavailable", pmic.summary(report))

    def test_unsupported_or_failed_device_never_reports_presets(self):
        for mode, reads, stage in (("openfail", [], 5), ("read7fail", [7], 1),
                                   ("badid", [7], 2), ("wrongcode", [7], 2), ("noop", [7], 2),
                                   ("read24fail", [7, 24], 3), ("wide24", [7, 24], 4)):
            with self.subTest(mode=mode):
                result, log, done = self.sample(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual([line for line in result.stdout.splitlines() if line.startswith("read ")],
                                 [f"read {n}" for n in reads])
                if mode != "openfail":
                    self.assertIn("closed device", result.stdout)
                self.assertNotIn("V|", log)
                self.assertIn(f"E|stage {stage}|", log)
                self.assertEqual(done, "T|unavailable\n")

    def test_partial_writes_are_completed_and_write_failure_has_no_done_marker(self):
        result, log, done = self.sample("shortwrite")
        self.assertEqual(result.returncode, 0)
        self.assertIn("V|SW1 normal preset mV|1000\n", log)
        self.assertEqual(done, "T|complete\n")
        for mode in ("writefail", "donefail"):
            with self.subTest(mode=mode):
                result, _, done = self.sample(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(done, "")


class Workflow(unittest.TestCase):
    def test_staging_and_import_distinguish_completion_from_measurement_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with mock.patch.dict(os.environ, {"S2AM_HOME": str(folder / "home")}), \
                    mock.patch.object(native, "binary", return_value=b"MZ stand-in"):
                work = folder / "job"
                with contextlib.redirect_stdout(io.StringIO()):
                    code = cli.main(["job", "pmic", "--serial", SERIAL, "--no-pack", "--work", str(work)])
                self.assertEqual(code, 0)
                job = Job.from_json((work / "job.json").read_text())
                self.assertTrue((work / "payload" / job.job_dir.lstrip("/") / "s2ampmic.exe").is_file())
                (work / "install.bin").write_bytes(b"pack")
                usb = folder / "stick"
                usb.mkdir()
                stick.prepare(usb, work / "install.bin", job, require_volume=False)
                car = FakeCar(folder / "car", SERIAL)
                car.insert(usb, work, job)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.main(["stick", "import", str(usb), "--any-path"])
                self.assertIn("NOT complete: PMIC report may be partial", out.getvalue())


if __name__ == "__main__":
    unittest.main()
