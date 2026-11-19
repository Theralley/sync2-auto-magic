"""Exercise the real paired-loop app's control flow, not CE, ARM timing, or FAT."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = r'''
#ifndef WINDOWS_H
#define WINDOWS_H
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD;
typedef int BOOL;
typedef wchar_t WCHAR, *LPWSTR;
typedef const wchar_t *LPCWSTR;
typedef void *HANDLE, *HINSTANCE, *LPVOID;
typedef unsigned char BYTE;
typedef long long LONGLONG;
typedef union { struct { DWORD LowPart; int32_t HighPart; }; int64_t QuadPart; } LARGE_INTEGER;
#define WINAPI
#define MAX_PATH 260
#define TRUE 1
#define FALSE 0
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
#define GENERIC_WRITE 0x40000000u
#define CREATE_NEW 1
#define FILE_ATTRIBUTE_NORMAL 128
#define FILE_SHARE_READ 1
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_ALREADY_EXISTS 183
DWORD GetModuleFileNameW(HINSTANCE, LPWSTR, DWORD);
DWORD GetLastError(void);
DWORD GetFileAttributesW(LPCWSTR);
HANDLE CreateFileW(LPCWSTR,DWORD,DWORD,void*,DWORD,DWORD,HANDLE);
BOOL WriteFile(HANDLE,const void*,DWORD,DWORD*,void*);
BOOL FlushFileBuffers(HANDLE);
BOOL CloseHandle(HANDLE);
BOOL MoveFileW(LPCWSTR,LPCWSTR);
BOOL QueryPerformanceCounter(LARGE_INTEGER*);
BOOL QueryPerformanceFrequency(LARGE_INTEGER*);
DWORD GetTickCount(void);
void Sleep(DWORD);
#endif
'''
SHIM = r'''
#include "windows.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wctype.h>
#include <assert.h>
int WINAPI WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
static const char *mode;
static WCHAR module[1024];
#ifdef S2AM_PAIR_V2
#define ROOT_SUBDIR L"S2AM-RAM\\"
#else
#define ROOT_SUBDIR L"S2AM-PAIR\\"
#endif
static const WCHAR *root = L"\\USB Disk\\" ROOT_SUBDIR;
static const char old[] = "previous result\r\n";
static char scratch[8192], result[8192];
static int calls, creates, opened, flushes, closes, moves, writes, error;
static int tmp_exists, final_exists, short_once;
static size_t used;
static int is(const char *s) { return !strcmp(mode,s); }
static int eq(const WCHAR *p,const WCHAR *q) {
    while (*p && *q && towupper(*p)==towupper(*q)) { ++p; ++q; }
    return !*p && !*q;
}
static int path_kind(const WCHAR *p) {
    size_t n=wcslen(root);
    for (size_t i=0;i<n;i++) assert(p[i] && towupper(p[i])==towupper(root[i]));
    if (eq(p+n,L"RESULT.CSV")) return 2;
    assert(eq(p+n,L"RESULT.TMP"));
    return 1;
}
DWORD GetModuleFileNameW(HINSTANCE h,LPWSTR out,DWORD cap) {
    assert(!h && cap && cap < 1024);
    if(is("module-error")) return 0;
    if(is("module-long")) { wmemset(out,L'X',cap); return cap; }
    assert(wcslen(module)<cap); wcscpy(out,module); return (DWORD)wcslen(module);
}
DWORD GetLastError(void) { return (DWORD)error; }
DWORD GetFileAttributesW(LPCWSTR p) {
    int exists=path_kind(p)==1 ? tmp_exists : final_exists;
    error=exists ? 0 : is("stat-fail") ? 5 : ERROR_FILE_NOT_FOUND;
    return exists ? FILE_ATTRIBUTE_NORMAL : INVALID_FILE_ATTRIBUTES;
}
HANDLE CreateFileW(LPCWSTR p,DWORD access,DWORD share,void *sec,DWORD disp,DWORD flags,HANDLE tmpl) {
    ++creates; assert(path_kind(p)==1 && access==GENERIC_WRITE && disp==CREATE_NEW);
    assert(!sec && !tmpl); (void)share; (void)flags;
    if(tmp_exists || is("create-fail")) { error=ERROR_ALREADY_EXISTS; return INVALID_HANDLE_VALUE; }
    tmp_exists=opened=1; return (HANDLE)(intptr_t)1;
}
BOOL WriteFile(HANDLE h,const void *body,DWORD len,DWORD *n,void *overlap) {
    assert(opened && h==(HANDLE)(intptr_t)1 && !overlap && used+len<sizeof scratch);
#ifdef S2AM_PAIR_V2
    assert(calls >= 64);
#endif
    ++writes; *n=0;
    if((is("write-fail") && writes==2) || (is("write-final-fail") && writes==35)) return FALSE;
    if(is("zero-write")) return TRUE;
    if(is("short-write") && !short_once++ && len>1) --len;
    memcpy(scratch+used,body,len); used+=len; scratch[used]=0; *n=len; return TRUE;
}
BOOL FlushFileBuffers(HANDLE h) {
    assert(opened && h==(HANDLE)(intptr_t)1); ++flushes;
    return !(is("flush-fail") && strstr(scratch,"complete,32"));
}
BOOL CloseHandle(HANDLE h) {
    assert(opened && h==(HANDLE)(intptr_t)1); ++closes; opened=0;
    return !is("close-fail");
}
BOOL MoveFileW(LPCWSTR from,LPCWSTR to) {
    assert(path_kind(from)==1 && path_kind(to)==2 && tmp_exists && !opened);
    ++moves;
    if (is("race-with-existing")) { strcpy(result,old); final_exists=1; }
    if (final_exists || is("move-fail")) return FALSE;
    strcpy(result,scratch); final_exists=1; tmp_exists=0; return TRUE;
}
BOOL QueryPerformanceFrequency(LARGE_INTEGER *n) {
    n->QuadPart=is("negative-qpf") ? -1 : is("zero-qpf") ? 0 : 1000000;
    return !is("qpf-fail");
}
BOOL QueryPerformanceCounter(LARGE_INTEGER *n) {
#ifdef S2AM_PAIR_V2
    assert(!writes && !flushes);
#endif
    ++calls;
    n->QuadPart=INT64_C(4294967000)+200*calls;
    if(calls==12 && is("negative-qpc")) n->QuadPart=-1;
    if(calls==12 && is("frozen-qpc")) n->QuadPart-=200;
    if(calls==13 && is("backward-qpc")) n->QuadPart-=1200;
    return !((calls==12 && is("qpc-fail")) || (calls==64 && is("last-qpc-fail")));
}
DWORD GetTickCount(void) {
    static DWORD ticks; return ticks+=is("timeout") ? 60001 : 1;
}
void Sleep(DWORD millis) {
#ifdef S2AM_PAIR_V2
    assert(!calls || calls >= 64);
#endif
    assert(millis<1000);
}
int main(int argc,char **argv) {
    assert(argc==3); mode=argv[1]; assert(mbstowcs(module,argv[2],1024)<1024);
    if(wcsstr(module,L"Disk2") || wcsstr(module,L"disk2")) root=L"\\USB Disk2\\" ROOT_SUBDIR;
    if(is("existing") || is("existing-tmp")) {
        if(is("existing")) { strcpy(result,old); final_exists=1; }
        else { tmp_exists=1; strcpy(scratch,old); }
    }
    int rc=WinMain(NULL,NULL,is("cmd-path") ? L"\\Windows\\override.csv" : L"",0);
    if(is("existing-tmp")) assert(!strcmp(scratch,old));
    printf("%d %d %d %d %d %d %d\n",rc,creates,writes,flushes,closes,moves,final_exists);
    if(final_exists) fputs(result,stdout);
    return 0;
}
'''

MODULE = r"\USB Disk\S2AM-PAIR\S2AMPAIR.EXE"


class PairedAppRuntime(unittest.TestCase):
    version = 1
    module = MODULE
    rounds_by_block = (16384,) * 4 + (32768,) * 4
    flags = ()

    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host test needs a C compiler")
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / "windows.h").write_text(HEADER)
        (d / "shim.c").write_text(SHIM)
        cls.exe = d / "paired-host"
        subprocess.run(
            [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-DS2AM_PAIR_HOST_TEST", *cls.flags,
             "-I", str(d), str(d / "shim.c"), str(ROOT / "s2am/native/s2ampair.c"),
             "-o", str(cls.exe)], check=True,
        )

    def app(self, mode, path=None):
        raw = subprocess.run([str(self.exe), mode, path or self.module], capture_output=True, timeout=6)
        self.assertEqual(raw.returncode, 0, raw.stderr)
        summary, body = raw.stdout.split(b"\n", 1)
        return [int(x) for x in summary.split()], body

    def check_success(self, mode="ok", path=None):
        (rc, creates, writes, flushes, closes, moves, exists), body = self.app(mode, path)
        self.assertEqual((rc, creates, closes, moves, exists), (0, 1, 1, 1, 1))
        self.assertGreater(writes, 0)
        self.assertGreater(flushes, 0)
        lines = body.decode("ascii").split("\r\n")
        self.assertEqual(lines[:2], [f"S2AM-PAIR,{self.version}", "qpf,1000000"])
        self.assertEqual(lines[-2:], ["complete,32", ""])
        self.assertEqual(len(lines[2:-2]), 32)
        last = 0
        for row, line in enumerate(lines[2:-2]):
            label, *fields = line.split(",")
            block, slot = divmod(row, 4)
            rounds = self.rounds_by_block[block]
            width = (32, 64, 64, 32)[slot]
            if block % 2:
                width = 96 - width
            self.assertEqual(label, "sample")
            b, s, r, w, start, end = map(int, fields)
            self.assertEqual((b, s, r, w), (block, slot, rounds, width))
            self.assertGreaterEqual(start, last)
            self.assertGreater(end, start)
            last = end
        self.assertGreater(last, 2**32)
        return body

    def test_exact_32_samples_and_disk_variants(self):
        for path in (self.module, self.module.lower(), self.module.replace("Disk", "Disk2")):
            with self.subTest(path=path):
                self.check_success(path=path)

    def test_wrong_module_never_touches_storage(self):
        folder, exe = self.module.rsplit("\\", 2)[1:]
        for path in ("\\Windows\\" + exe, "\\Storage Card\\" + folder + "\\" + exe,
                     self.module.replace("Disk", "Disk3"), self.module.replace("Disk", "Diskette"),
                     self.module.replace(folder, folder + "\\..\\" + folder),
                     self.module+"2", self.module[1:]):
            with self.subTest(path=path):
                data, body = self.app("ok", path)
                self.assertNotEqual(data[0], 0)
                self.assertEqual(data[1:], [0] * 6)
                self.assertFalse(body)
        for mode in ("module-error", "module-long", "cmd-path"):
            with self.subTest(mode=mode):
                data, body = self.app(mode)
                self.assertNotEqual(data[0], 0)
                self.assertEqual(data[1:], [0] * 6)
                self.assertFalse(body)

    def test_errors_never_publish_final(self):
        for mode in ("stat-fail", "create-fail", "existing-tmp", "qpf-fail", "negative-qpf", "zero-qpf",
                     "qpc-fail", "last-qpc-fail", "negative-qpc", "frozen-qpc", "backward-qpc", "timeout",
                     "write-fail", "write-final-fail", "zero-write", "flush-fail", "close-fail", "move-fail"):
            with self.subTest(mode=mode):
                data, body = self.app(mode)
                self.assertNotEqual(data[0], 0)
                self.assertEqual(data[-1], 0)
                self.assertFalse(body)

    def test_existing_and_racing_results_unchanged(self):
        for mode in ("existing", "race-with-existing"):
            with self.subTest(mode=mode):
                data, body = self.app(mode)
                self.assertNotEqual(data[0], 0)
                self.assertEqual(body, b"previous result\r\n")
                if mode == "existing":
                    self.assertEqual(data[1:6], [0] * 5)

    def test_short_write_abort_or_full_recovery(self):
        data, body = self.app("short-write")
        if data[0]:
            self.assertEqual(data[-1], 0)
            self.assertFalse(body)
        else:
            self.assertEqual(body, self.check_success())


class RamPairedAppRuntime(PairedAppRuntime):
    version = 2
    module = r"\USB Disk\S2AM-RAM\S2AMRAM.EXE"
    rounds_by_block = (16384, 32768, 32768, 16384) * 2
    flags = ("-DS2AM_PAIR_V2",)

    def test_rejects_old_module_path(self):
        summary, body = self.app("ok", MODULE)
        self.assertNotEqual(summary[0], 0)
        self.assertEqual(summary[1:], [0] * 6)
        self.assertFalse(body)

    def test_no_partial_output_on_final_measurement_failure(self):
        (rc, _creates, writes, flushes, _closes, moves, exists), _ = self.app("last-qpc-fail")
        self.assertNotEqual(rc, 0)
        self.assertEqual((writes, flushes, moves, exists), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
