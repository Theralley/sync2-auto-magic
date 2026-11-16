"""Execute the real fixed clock reader against memory and Windows API fakes."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLL = (0, 4, 8, 12, 16, 28, 32, 36, 40, 44)
CCM = (0, 8, 12, 16, 20, 24, 28, 32, 72, 76, 84)

WINDOWS = r'''
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD, ULONG;
typedef unsigned char BYTE;
typedef int BOOL;
typedef void *HANDLE, *HINSTANCE, *HMODULE, *LPVOID;
typedef wchar_t WCHAR, *LPWSTR;
typedef const wchar_t *LPCWSTR;
typedef union { int64_t QuadPart; struct { DWORD LowPart; int32_t HighPart; }; } LARGE_INTEGER;
typedef int (*FARPROC)(void);
#define WINAPI
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define GENERIC_WRITE 0x40000000U
#define FILE_SHARE_READ 1
#define CREATE_NEW 1
#define FILE_ATTRIBUTE_NORMAL 128
HANDLE CreateFileW(LPCWSTR, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
BOOL WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
BOOL FlushFileBuffers(HANDLE);
BOOL CloseHandle(HANDLE);
HMODULE LoadLibraryW(LPCWSTR);
FARPROC GetProcAddress(HMODULE, LPCWSTR);
BOOL FreeLibrary(HMODULE);
DWORD GetLastError(void);
void SetLastError(DWORD);
'''

SHIM = r'''
#include "windows.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static const char *mode;
static FILE *file;
static DWORD error;
static char pending[20000], durable[20000];
static size_t used;
static void *regions[2];
static unsigned mapped;
static int ismode(const char *value) { return !strcmp(mode, value); }
static void ended(const char *line) {
    size_t n = strlen(durable), m = strlen(line);
    assert(n >= m && !strcmp(durable+n-m, line));
}
HANDLE CreateFileW(LPCWSTR path, DWORD access, DWORD share, void *security,
                  DWORD disposition, DWORD flags, HANDLE template) {
    char text[1024]; size_t i;
    assert(access == GENERIC_WRITE && share == FILE_SHARE_READ);
    assert(disposition == CREATE_NEW && flags == FILE_ATTRIBUTE_NORMAL);
    assert(!security && !template);
    for (i=0; path[i]; ++i) text[i] = path[i] == L'\\' ? '/' : (char)path[i];
    text[i]=0;
    if (ismode("createfail")) return INVALID_HANDLE_VALUE;
    file=fopen(text,"wx");
    puts("create");
    return file ? (HANDLE)file : INVALID_HANDLE_VALUE;
}
BOOL WriteFile(HANDLE h, const void *data, DWORD n, DWORD *done, void *overlapped) {
    assert(h == (HANDLE)file && !overlapped);
    if (ismode("writefail") || (ismode("midwritefail") && strstr(pending,"R|1|ccm-before|0|"))) {
        *done=0; error=29; return 0;
    }
    if (ismode("zerowrite")) { *done=0; return 1; }
    if (ismode("oversizewrite")) { *done=n+1; return 1; }
    if (ismode("shortwrite") && n>1) n=1;
    assert(used+n<sizeof(pending));
    memcpy(pending+used,data,n); used+=n; pending[used]=0;
    *done=(DWORD)fwrite(data,1,n,file);
    return *done==n;
}
BOOL FlushFileBuffers(HANDLE h) {
    assert(h == (HANDLE)file);
    fflush(file);
    if (ismode("flushfail") || (ismode("midflushfail") && strstr(pending,"B|read|1|pll1|0\r\n")) ||
        (ismode("finalflushfail") && strstr(pending,"T|complete\r\n"))) {
        error=29; return 0;
    }
    strcpy(durable,pending);
    if (ismode("changed") && strstr(pending,"B|read|2|pll1|0\r\n") && (mapped & 1)) {
        assert(!mprotect(regions[0],(size_t)sysconf(_SC_PAGESIZE),PROT_READ|PROT_WRITE));
        ((DWORD *)regions[0])[0]=0xffffffffU;
        assert(!mprotect(regions[0],(size_t)sysconf(_SC_PAGESIZE),PROT_READ));
    }
    return 1;
}
BOOL CloseHandle(HANDLE h) {
    int result;
    assert(h == (HANDLE)file);
    result=fclose(file)==0;
    puts("close");
    return ismode("closefail") ? 0 : result;
}
HMODULE LoadLibraryW(LPCWSTR name) {
    ended("B|load\r\n");
    assert(!wcscmp(name,L"\\Windows\\ceddk.dll"));
    puts("load");
    if (ismode("loadfail")) { error=193; return NULL; }
    return (HMODULE)(intptr_t)1;
}
static LPVOID map_io(LARGE_INTEGER physical, ULONG length, BYTE cached) {
    unsigned block, i; long page=sysconf(_SC_PAGESIZE);
    assert(!cached);
    if (physical.QuadPart==0x83f80000) {
        block=0; assert(length==0x30); ended("B|map|pll1\r\n");
    } else {
        assert(physical.QuadPart==0x73fd4000);
        block=1; assert(length==0x58); ended("B|map|ccm\r\n");
    }
    printf("map %u\n",block);
    if ((block==0 && ismode("mapfail")) || (block==1 && ismode("map2fail")) ||
        ismode("mapzeroerror")) { error=ismode("mapzeroerror") ? 0 : 5; return NULL; }
    assert(!regions[block]);
    regions[block]=mmap(NULL,(size_t)page,PROT_READ|PROT_WRITE,MAP_ANON|MAP_PRIVATE,-1,0);
    assert(regions[block]!=MAP_FAILED);
    for (i=0;i<length/4;i++) ((DWORD *)regions[block])[i]=0xf0000000U+block*0x1000+i*4;
    /* Any MMIO write in the production reader faults in this test. */
    assert(!mprotect(regions[block],(size_t)page,
                     block==0 && ismode("readcrash") ? PROT_NONE : PROT_READ));
    mapped|=1U<<block;
    return regions[block];
}
static void unmap_io(LPVOID address, ULONG length) {
    unsigned block;
    if (address==regions[0]) { block=0; assert(length==0x30); ended("B|unmap|pll1\r\n"); }
    else { block=1; assert(address==regions[1] && length==0x58); ended("B|unmap|ccm\r\n"); }
    assert(mapped & (1U<<block));
    printf("unmap %u\n",block);
    if (ismode("unmapcrash")) _exit(91);
    assert(!munmap(address,(size_t)sysconf(_SC_PAGESIZE)));
    mapped &= ~(1U<<block);
}
FARPROC GetProcAddress(HMODULE module, LPCWSTR name) {
    assert(module==(HMODULE)(intptr_t)1);
    if (!wcscmp(name,L"MmMapIoSpace")) {
        ended("B|resolve|MmMapIoSpace\r\n"); puts("resolve map");
        if (ismode("nomap")) { error=127; return NULL; }
        return (FARPROC)(void *)map_io;
    }
    assert(!wcscmp(name,L"MmUnmapIoSpace"));
    ended("B|resolve|MmUnmapIoSpace\r\n"); puts("resolve unmap");
    if (ismode("nounmap")) { error=127; return NULL; }
    return (FARPROC)(void *)unmap_io;
}
BOOL FreeLibrary(HMODULE module) {
    assert(module==(HMODULE)(intptr_t)1 && !mapped);
    ended("B|free-library\r\n"); puts("free");
    if (ismode("freefail")) { error=5; return 0; }
    return 1;
}
DWORD GetLastError(void) { return error; }
void SetLastError(DWORD value) { error=value; }
int WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
int main(int argc,char **argv) {
    WCHAR command[2048]; size_t i;
    assert(argc==3); mode=argv[2];
    setvbuf(stdout,NULL,_IONBF,0);
    for (i=0;argv[1][i];i++) command[i]=argv[1][i]=='/' ? L'\\' : (WCHAR)argv[1][i];
    command[i]=0;
    return WinMain(NULL,NULL,command,0);
}
'''


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class NativeClockProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "shim.c").write_text(SHIM)
        cls.program = cls.work / "clockprobe"
        result = subprocess.run(
            ["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-I", str(cls.work),
             str(ROOT / "s2am/native/s2amclock.c"), str(cls.work / "shim.c"), "-o", str(cls.program)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_probe(self, mode="ok", argument=None, prior=None):
        folder = Path(tempfile.mkdtemp(dir=self.work))
        report = folder / "clock snapshot.txt"
        if prior is not None:
            report.write_text(prior)
        command = argument if argument is not None else f'"{report}"'
        result = subprocess.run([str(self.program), command, mode], capture_output=True, text=True, timeout=5)
        return result, report.read_text() if report.exists() else ""

    def test_two_complete_bracketed_passes_contain_exact_fixed_reads(self):
        result, report = self.run_probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = []
        for sample in (1, 2):
            for block, offsets, bias in (("ccm-before", CCM, 0x1000), ("pll1", PLL, 0),
                                         ("ccm-after", CCM, 0x1000)):
                expected += [f"R|{sample}|{block}|{offset}|{0xf0000000 + bias + offset}" for offset in offsets]
        self.assertEqual([line for line in report.splitlines() if line.startswith("R|")], expected)
        self.assertEqual(report.splitlines()[0], "S|s2am-clock-v1")
        self.assertTrue(report.endswith("T|complete\n"))
        self.assertNotIn("E|", report)
        self.assertEqual(result.stdout.splitlines(), ["create", "load", "resolve map", "resolve unmap",
                         "map 0", "map 1", "unmap 1", "unmap 0", "free", "close"])
        lines = report.splitlines()
        for n, line in enumerate(lines):
            if line.startswith("R|"):
                self.assertEqual(lines[n-1], "B|read|" + "|".join(line.split("|")[1:4]))

    def test_missing_library_exports_and_mapping_denial_are_explicit(self):
        for mode, stage, error, maps in (("loadfail", "load", 193, 0), ("nomap", "resolve-map", 127, 0),
                                        ("nounmap", "resolve-unmap", 127, 0), ("mapfail", "map-pll1", 5, 1),
                                        ("mapzeroerror", "map-pll1", 0, 1), ("map2fail", "map-ccm", 5, 2)):
            with self.subTest(mode=mode):
                result, report = self.run_probe(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"E|{stage}|{error}\n", report)
                self.assertNotIn("T|", report)
                self.assertNotIn("R|", report)
                self.assertEqual(sum(line.startswith("map ") for line in result.stdout.splitlines()), maps)
                if mode == "map2fail":
                    self.assertIn("unmap 0", result.stdout)

    def test_existing_or_uncreatable_report_never_loads_library(self):
        result, report = self.run_probe(prior="previous interrupted evidence\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report, "previous interrupted evidence\n")
        self.assertNotIn("load", result.stdout)
        result, report = self.run_probe("createfail")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report, "")
        self.assertNotIn("load", result.stdout)

    def test_arguments_are_one_bounded_absolute_output_filename(self):
        for argument in ("", "relative.txt", '"unterminated', '"/tmp/output.txt" extra',
                         "/tmp/output.txt other", '"/tmp/' + "x" * 260 + '"'):
            with self.subTest(argument=argument):
                result, report = self.run_probe(argument=argument)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(report, "")

    def test_short_writes_complete_but_failed_progress_stops_sampling(self):
        result, report = self.run_probe("shortwrite")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(report.endswith("T|complete\n"))
        for mode in ("writefail", "zerowrite", "oversizewrite", "flushfail", "midwritefail", "midflushfail"):
            with self.subTest(mode=mode):
                result, report = self.run_probe(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("T|complete", report)
                if mode.startswith("mid"):
                    self.assertNotIn("R|1|pll1|", report)
                    self.assertNotIn("R|2|", report)
                else:
                    self.assertNotIn("load", result.stdout)

    def test_read_and_unmap_crashes_leave_last_flushed_stage(self):
        result, report = self.run_probe("readcrash")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(report.endswith("B|read|1|pll1|0\n"))
        self.assertNotIn("R|1|pll1|", report)
        result, report = self.run_probe("unmapcrash")
        self.assertEqual(result.returncode, 91)
        self.assertTrue(report.endswith("B|unmap|ccm\n"))
        self.assertNotIn("T|", report)

    def test_library_cleanup_failure_has_no_completion(self):
        result, report = self.run_probe("freefail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("E|free-library|5\n", report)
        self.assertNotIn("T|", report)

    def test_changed_registers_are_preserved_without_a_native_frequency_claim(self):
        result, report = self.run_probe("changed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("R|1|pll1|0|4026531840\n", report)
        self.assertIn("R|2|pll1|0|4294967295\n", report)
        self.assertTrue(report.endswith("T|complete\n"))
        self.assertNotIn("MHz", report)
        self.assertNotIn("stable", report)

    def test_final_storage_failure_requires_exit_status_even_if_marker_bytes_exist(self):
        for mode in ("finalflushfail", "closefail"):
            with self.subTest(mode=mode):
                result, report = self.run_probe(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("T|complete", report)


if __name__ == "__main__":
    unittest.main()
