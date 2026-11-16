"""Bounded ordinary-file module evidence; the native shim never touches hardware."""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
NAMES = ("cspddk.dll", "autopmdrv.dll", "pmicPdk_mc13892.dll", "pmicSdk_mc13892.dll",
         "dvfc_mc13892.dll", "nk.exe", "kernel.dll", "coredll.dll")
LENGTHS = (33333, 19, 0, 17, 23, 29, 31, 37)


def contents(index):
    return bytes((offset + index * 17) % 256 for offset in range(LENGTHS[index]))


def summary(folder):
    return importlib.import_module("s2am.modules").summary(folder)


# This is only the Windows API boundary. The production C source is compiled unchanged.
WINDOWS = r'''
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD;
typedef int BOOL;
typedef unsigned char BYTE;
typedef void *HANDLE;
typedef void *HINSTANCE;
typedef wchar_t WCHAR;
typedef wchar_t *LPWSTR;
typedef const wchar_t *LPCWSTR;
typedef struct { DWORD dwLowDateTime, dwHighDateTime; } FILETIME;
typedef struct {
    DWORD dwFileAttributes;
    FILETIME ftCreationTime, ftLastAccessTime, ftLastWriteTime;
    DWORD nFileSizeHigh, nFileSizeLow;
} WIN32_FILE_ATTRIBUTE_DATA;
typedef enum { GetFileExInfoStandard } GET_FILEEX_INFO_LEVELS;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define MAX_PATH 260
#define GENERIC_READ 0x80000000U
#define GENERIC_WRITE 0x40000000U
#define FILE_SHARE_READ 1
#define FILE_SHARE_WRITE 2
#define CREATE_ALWAYS 2
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 128
#define FILE_ATTRIBUTE_DIRECTORY 16
#define FILE_ATTRIBUTE_INROM 64
#define FILE_ATTRIBUTE_ROMMODULE 8192
#define ERROR_ALREADY_EXISTS 183
#define ERROR_WRITE_FAULT 29
#define ERROR_READ_FAULT 30
#define ERROR_HANDLE_EOF 38
#define ERROR_INVALID_DATA 13
#define ERROR_TIMEOUT 1460
BOOL GetFileAttributesExW(LPCWSTR, GET_FILEEX_INFO_LEVELS, void *);
BOOL CreateDirectoryW(LPCWSTR, void *);
HANDLE CreateFileW(LPCWSTR, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
BOOL ReadFile(HANDLE, void *, DWORD, DWORD *, void *);
BOOL WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
BOOL FlushFileBuffers(HANDLE);
BOOL CloseHandle(HANDLE);
DWORD GetLastError(void);
void SetLastError(DWORD);
DWORD GetTickCount(void);
'''

SHIM = r'''
#include "windows.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <sys/stat.h>
#include <errno.h>

enum { SOURCE=1, MODULE=2, REPORT=3, MARKER=4 };
typedef struct { int kind, index, closed; DWORD pos; FILE *file; } File;
static File handles[32];
static int used, active_sources, attributes[8], report_flushed, report_closed, timed_out;
static unsigned source_reads;
static DWORD last_error;
static const char *mode, *folder;
static const char *names[8] = {"cspddk.dll", "autopmdrv.dll", "pmicPdk_mc13892.dll",
    "pmicSdk_mc13892.dll", "dvfc_mc13892.dll", "nk.exe", "kernel.dll", "coredll.dll"};
static DWORD lengths[8] = {33333,19,0,17,23,29,31,37};
static int ismode(const char *s) { return !strcmp(mode,s); }
static void narrow(const WCHAR *wide, char *text) {
    size_t i;
    for (i=0; wide[i]; ++i) { assert(i<1023); text[i]=wide[i]==L'\\' ? '/' : (char)wide[i]; }
    text[i]=0;
}
static int source_index(const char *path) {
    int i;
    if (strncmp(path,"/Windows/",9)) return -1;
    for (i=0;i<8;i++) if (!strcmp(path+9,names[i])) return i;
    assert(!"unlisted source path"); return -1;
}
static File *handle(int kind, int index, FILE *file) {
    File *h;
    assert(used<32); h=&handles[used++]; h->kind=kind; h->index=index; h->file=file;
    return h;
}
BOOL GetFileAttributesExW(LPCWSTR path, GET_FILEEX_INFO_LEVELS level, void *result) {
    char text[1024]; int i; WIN32_FILE_ATTRIBUTE_DATA *data=result;
    narrow(path,text); i=source_index(text); assert(i>=0 && level==GetFileExInfoStandard);
    assert(!timed_out);
    ++attributes[i]; memset(data,0,sizeof(*data));
    if (i==0 && ismode("attrfail")) { memset(data,0xaa,sizeof(*data)); last_error=5; return 0; }
    data->dwFileAttributes=FILE_ATTRIBUTE_NORMAL;
    data->nFileSizeLow=lengths[i]; data->ftLastWriteTime.dwLowDateTime=11+(DWORD)i;
    data->ftLastWriteTime.dwHighDateTime=3;
    if (i==0) {
        if (ismode("rommodule")) data->dwFileAttributes|=FILE_ATTRIBUTE_ROMMODULE|FILE_ATTRIBUTE_INROM;
        if (ismode("inrom")) data->dwFileAttributes|=FILE_ATTRIBUTE_INROM;
        if (ismode("directory")) data->dwFileAttributes|=FILE_ATTRIBUTE_DIRECTORY;
        if (ismode("oversize")) data->nFileSizeLow=4U*1024U*1024U+1;
        if (ismode("highsize")) data->nFileSizeHigh=1;
        if (ismode("changed") && attributes[i]>1) ++data->ftLastWriteTime.dwLowDateTime;
        if (ismode("postattrfail") && attributes[i]>1) { last_error=5; return 0; }
    }
    return 1;
}
BOOL CreateDirectoryW(LPCWSTR path, void *security) {
    char text[1024], expected[1024]; narrow(path,text);
    snprintf(expected,sizeof(expected),"%s/modules",folder); assert(!strcmp(text,expected));
    if (mkdir(text,0700)==0) return 1;
    last_error=errno==EEXIST ? ERROR_ALREADY_EXISTS : 5; return 0;
}
HANDLE CreateFileW(LPCWSTR path, DWORD access, DWORD share, void *security,
                   DWORD disposition, DWORD flags, HANDLE template) {
    char text[1024], expected[1024]; int i,kind=0; FILE *file;
    narrow(path,text); i=source_index(text);
    if (i>=0) {
        assert(!timed_out);
        assert(attributes[i]>0 && access==GENERIC_READ && share==FILE_SHARE_READ);
        assert(disposition==OPEN_EXISTING && security==NULL && template==NULL);
        if (i==0) {
            assert(!ismode("rommodule") && !ismode("directory") && !ismode("oversize") && !ismode("highsize") && !ismode("attrfail"));
            if (ismode("openfail")) { last_error=5; return INVALID_HANDLE_VALUE; }
        }
        printf("open %s\n",names[i]); ++active_sources; return handle(SOURCE,i,NULL);
    }
    assert(access==GENERIC_WRITE && disposition==CREATE_ALWAYS);
    assert(!strncmp(text,folder,strlen(folder)) && text[strlen(folder)]=='/');
    snprintf(expected,sizeof(expected),"%s/modules.txt",folder);
    if (!strcmp(text,expected)) kind=REPORT;
    snprintf(expected,sizeof(expected),"%s/modules-done.txt",folder);
    if (!strcmp(text,expected)) {
        assert(report_flushed && report_closed); kind=MARKER;
        if (ismode("donefail")) { last_error=5; return INVALID_HANDLE_VALUE; }
    }
    for (i=0;i<8;i++) {
        snprintf(expected,sizeof(expected),"%s/modules/%s",folder,names[i]);
        if (!strcmp(text,expected)) { kind=MODULE; break; }
    }
    assert(kind);
    if (kind==MODULE && i==0 && ismode("createfail")) { last_error=5; return INVALID_HANDLE_VALUE; }
    file=fopen(text,"wb"); if (!file) { last_error=5; return INVALID_HANDLE_VALUE; }
    return handle(kind,i,file);
}
BOOL ReadFile(HANDLE value, void *buffer, DWORD count, DWORD *done, void *overlapped) {
    File *h=value; DWORD available,n,j; unsigned char *out=buffer;
    assert(h->kind==SOURCE && !h->closed && overlapped==NULL && count>0 && count<=65536);
    assert(!timed_out);
    ++source_reads;
    if (h->index==0 && ismode("readfail") && h->pos>0) { *done=0; last_error=5; return 0; }
    available=lengths[h->index]-h->pos;
    if (h->index==0 && ismode("truncated") && h->pos>0) available=0;
    if (h->index==0 && ismode("growing") && h->pos==lengths[0]) available=1;
    n=count<available ? count : available;
    for (j=0;j<n;j++) out[j]=(unsigned char)(h->pos+j+(DWORD)h->index*17);
    h->pos+=n; *done=n;
    if (h->index==0 && !n && ismode("budget-eof")) timed_out=1;
    return 1;
}
BOOL WriteFile(HANDLE value, const void *buffer, DWORD count, DWORD *done, void *overlapped) {
    File *h=value;
    assert(h->kind!=SOURCE && !h->closed && overlapped==NULL);
    if (h->kind==MODULE) assert(!timed_out);
    if ((h->kind==MODULE && h->index==0 && ismode("writefail")) ||
        (h->kind==REPORT && ismode("reportwritefail"))) { *done=0; last_error=5; return 0; }
    if (h->kind==MODULE && h->index==0 && ismode("zerowrite")) { *done=0; return 1; }
    if (ismode("shortwrite") && count>3) count=3;
    if (h->kind==MODULE && h->index==0 && ismode("budget-shortwrite") && count>3) count=3;
    *done=(DWORD)fwrite(buffer,1,count,h->file);
    if (h->kind==MODULE && h->index==0) {
        h->pos+=*done;
        if (ismode("budget-shortwrite") || (ismode("budget-finalwrite") && h->pos==lengths[0]))
            timed_out=1;
    }
    return *done==count;
}
BOOL FlushFileBuffers(HANDLE value) {
    File *h=value; assert(h->kind!=SOURCE && !h->closed);
    if ((h->kind==MODULE && h->index==0 && ismode("flushfail")) ||
        (h->kind==REPORT && ismode("reportflushfail"))) { last_error=5; return 0; }
    if (fflush(h->file)!=0) { last_error=5; return 0; }
    if (h->kind==REPORT) report_flushed=1;
    return 1;
}
BOOL CloseHandle(HANDLE value) {
    File *h=value; assert(value!=INVALID_HANDLE_VALUE && !h->closed); h->closed=1;
    if (h->kind==SOURCE) {
        printf("close %s\n",names[h->index]); --active_sources;
        if (h->index==0 && ismode("sourceclosefail")) { last_error=5; return 0; }
        return 1;
    }
    if (h->kind==REPORT) report_closed=1;
    assert(fclose(h->file)==0);
    if (h->kind==MODULE && h->index==0 && ismode("closefail")) { last_error=5; return 0; }
    return 1;
}
DWORD GetLastError(void) { return last_error; }
void SetLastError(DWORD value) { last_error=value; }
DWORD GetTickCount(void) {
    return timed_out || (ismode("budget") && source_reads>0) ? 61001U : 1000U;
}
int WinMain(HINSTANCE, HINSTANCE, LPWSTR, int);
int main(int argc, char **argv) {
    WCHAR path[1024]; size_t i; int result;
    assert(argc==3); folder=argv[1]; mode=argv[2];
    for (i=0;argv[1][i];i++) path[i]=(WCHAR)argv[1][i]; path[i]=0;
    result=WinMain(NULL,NULL,path,0);
    assert(active_sources==0);
    for (i=0;i<(size_t)used;i++) assert(handles[i].closed);
    return result;
}
'''


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.work)
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "shim.c").write_text(SHIM)
        cls.program = cls.work / "modules"
        result = subprocess.run(
            ["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-I", str(cls.work),
             str(ROOT / "s2am/native/s2ammodules.c"), str(cls.work / "shim.c"), "-o", str(cls.program)],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def sample(self, mode):
        folder = Path(tempfile.mkdtemp(dir=self.work))
        result = subprocess.run([str(self.program), str(folder), mode], capture_output=True,
                                text=True, timeout=5)
        self.assertGreaterEqual(result.returncode, 0, result.stderr)
        log = (folder / "modules.txt").read_text() if (folder / "modules.txt").exists() else ""
        done = (folder / "modules-done.txt").read_text() if (folder / "modules-done.txt").exists() else ""
        return result, folder, log, done

    def complete_rows(self, log, done):
        self.assertEqual(done, "T|complete\n")
        lines = log.splitlines()
        self.assertEqual(lines[0], "S|s2am-modules-v1|8")
        self.assertEqual(lines[-1], "T|complete")
        rows = [line.split("|") for line in lines[1:-1]]
        self.assertEqual([row[1] for row in rows], list(NAMES))
        self.assertTrue(all(len(row) == 11 and row[0] == "F" for row in rows))
        return rows

    def test_normal_and_inrom_files_are_copied_with_exact_size_and_crc(self):
        for mode in ("ok", "inrom", "shortwrite"):
            with self.subTest(mode=mode):
                result, folder, log, done = self.sample(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = self.complete_rows(log, done)
                for index, row in enumerate(rows):
                    self.assertEqual(row[7], "copied")
                    self.assertEqual(int(row[8]), 0)
                    self.assertEqual(int(row[9]), LENGTHS[index])
                    self.assertEqual(int(row[10]), zlib.crc32(contents(index)))
                    self.assertEqual((folder / "modules" / NAMES[index]).read_bytes(), contents(index))
                self.assertIn("modules: 8/8 files copied, 0 ROM modules, 0 unavailable", summary(folder))

    def test_unreadable_metadata_rom_directories_and_large_files_are_never_opened(self):
        for mode, status in (("attrfail", "attrs-error"), ("rommodule", "rom-module"),
                             ("directory", "directory"), ("oversize", "too-large"),
                             ("highsize", "too-large")):
            with self.subTest(mode=mode):
                result, folder, log, done = self.sample(mode)
                row = self.complete_rows(log, done)[0]
                self.assertEqual(row[7], status)
                self.assertNotIn("open cspddk.dll", result.stdout)
                self.assertFalse((folder / "modules/cspddk.dll").exists())
                if mode == "attrfail":
                    self.assertEqual(row[2:7], ["0"] * 5)
                    self.assertEqual(row[8], "5")
                self.assertIn("modules: 7/8 files copied", summary(folder))
                self.assertIn("1 ROM modules" if mode == "rommodule" else "1 unavailable", summary(folder))

    def test_failed_copies_are_recorded_and_never_accepted_as_copied(self):
        modes = (("openfail", "open-error"), ("readfail", "read-error"),
                 ("createfail", "create-error"), ("writefail", "write-error"),
                 ("zerowrite", "write-error"), ("flushfail", "flush-error"),
                 ("closefail", "close-error"), ("sourceclosefail", "close-error"),
                 ("changed", "changed"), ("truncated", "changed"),
                 ("growing", "changed"),
                 ("postattrfail", "changed"))
        for mode, status in modes:
            with self.subTest(mode=mode):
                _, folder, log, done = self.sample(mode)
                row = self.complete_rows(log, done)[0]
                self.assertEqual(row[7], status)
                if mode not in ("zerowrite", "changed", "truncated", "growing"):
                    self.assertEqual(row[8], "5")
                self.assertIn("modules: 7/8 files copied, 0 ROM modules, 1 unavailable", summary(folder))

    def test_elapsed_budget_stops_further_source_opens_without_claiming_a_copy(self):
        result, folder, log, done = self.sample("budget")
        rows = self.complete_rows(log, done)
        self.assertTrue(any(row[7] == "error-budget" for row in rows))
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith("open ")],
                         ["open cspddk.dll"])
        self.assertIn("modules: 0/8 files copied", summary(folder))

    def test_incomplete_report_or_marker_is_not_success(self):
        for mode in ("reportwritefail", "reportflushfail", "donefail"):
            with self.subTest(mode=mode):
                result, folder, _, done = self.sample(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(done, "T|complete\n")
                self.assertRegex(summary(folder), "NOT (complete|verified)")

    def test_expiry_during_short_writes_or_final_verification_starts_no_more_copy_io(self):
        for mode, count in (("budget-shortwrite", 3), ("budget-finalwrite", LENGTHS[0]),
                            ("budget-eof", LENGTHS[0])):
            with self.subTest(mode=mode):
                result, folder, log, done = self.sample(mode)
                rows = self.complete_rows(log, done)
                self.assertEqual(rows[0][7], "error-budget")
                self.assertEqual(int(rows[0][9]), count)
                self.assertEqual(rows[0][10], "0")
                self.assertTrue(all(row[7] == "error-budget" for row in rows))
                self.assertEqual([line for line in result.stdout.splitlines() if line.startswith("open ")],
                                 ["open cspddk.dll"])
                self.assertIn("modules: 0/8 files copied", summary(folder))


class Reports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder / "modules").mkdir()
        rows = []
        for index, name in enumerate(NAMES):
            data = contents(index)
            (self.folder / "modules" / name).write_bytes(data)
            rows.append(f"F|{name}|128|0|{len(data)}|3|{11 + index}|copied|0|{len(data)}|{zlib.crc32(data)}")
        self.text = "S|s2am-modules-v1|8\n" + "\n".join(rows) + "\nT|complete\n"
        (self.folder / "modules.txt").write_text(self.text)
        (self.folder / "modules-done.txt").write_text("T|complete\n")

    def assert_rejected(self):
        self.assertRegex(summary(self.folder), "NOT (complete|verified)")

    def test_complete_manifest_and_copy_bytes_are_verified(self):
        value = summary(self.folder)
        self.assertIn("modules: 8/8 files copied, 0 ROM modules, 0 unavailable", value)
        self.assertIn("modules.txt", value)

    def test_missing_partial_or_oversized_marker_and_report_are_rejected(self):
        marker = self.folder / "modules-done.txt"
        for text in ("", "T|complet", "T|unavailable\n", "T|complete\nextra\n", "x" * 10000):
            with self.subTest(marker=text[:30]):
                marker.write_text(text)
                self.assert_rejected()
        marker.unlink()
        self.assert_rejected()
        marker.write_text("T|complete\n")
        report = self.folder / "modules.txt"
        for text in ("", self.text[:-12], self.text + "extra\n", self.text + "x" * 100000):
            with self.subTest(report=text[:30]):
                report.write_text(text)
                self.assert_rejected()
        report.unlink()
        self.assert_rejected()

    def test_schema_names_order_counts_and_numeric_fields_are_strict(self):
        lines = self.text.splitlines(keepends=True)
        bad_texts = [self.text.replace("s2am-modules-v1", "s2am-modules-v0"),
                     self.text.replace("s2am-modules-v1|8", "s2am-modules-v1|9"),
                     self.text.replace("cspddk.dll", "../cspddk.dll"),
                     "".join(lines[:1] + lines[2:]),
                     "".join(lines[:2] + lines[1:]),
                     "".join(lines[:1] + [lines[2], lines[1]] + lines[3:])]
        for column, value in ((2, "-1"), (3, "4294967296"), (4, "-1"),
                              (5, "x"), (6, "4294967296"), (7, "unknown"),
                              (8, "5"), (9, "-1"), (10, "4294967296")):
            row = lines[1].rstrip("\n").split("|")
            row[column] = value
            bad_texts.append("".join(lines[:1] + ["|".join(row) + "\n"] + lines[2:]))
        for text in bad_texts:
            with self.subTest(text=text[:100]):
                (self.folder / "modules.txt").write_text(text)
                self.assert_rejected()

    def test_same_size_tampering_missing_files_and_extra_bytes_are_rejected(self):
        target = self.folder / "modules" / NAMES[0]
        original = target.read_bytes()
        for data in (b"!" + original[1:], original[:-1], original + b"!"):
            with self.subTest(length=len(data)):
                target.write_bytes(data)
                self.assert_rejected()
        target.unlink()
        self.assert_rejected()

    def test_symlink_copies_are_not_verified(self):
        target = self.folder / "modules" / NAMES[0]
        other = self.folder / "outside.bin"
        other.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(other)
        self.assert_rejected()

    def test_symlink_module_directory_is_not_verified(self):
        directory = self.folder / "modules"
        other = self.folder / "linked-modules"
        directory.rename(other)
        directory.symlink_to(other, target_is_directory=True)
        self.assert_rejected()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires named pipes")
    def test_nonregular_zero_size_copy_is_rejected_without_opening_it(self):
        # A FIFO has the same length as this valid empty-file fixture. Opening it
        # would block; run in a bounded child so a regression cannot hang the suite.
        target = self.folder / "modules" / NAMES[2]
        target.unlink()
        os.mkfifo(target)
        result = subprocess.run(
            [sys.executable, "-c", "from pathlib import Path; import sys; "
             "from s2am.modules import summary; print(summary(Path(sys.argv[1])))", str(self.folder)],
            cwd=ROOT, capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT verified", result.stdout)

    def test_noncopy_status_never_accepts_a_leftover_partial_file_as_copied(self):
        lines = self.text.splitlines()
        row = lines[1].split("|")
        row[7:] = ["read-error", "5", "4096", "0"]
        lines[1] = "|".join(row)
        text = "\n".join(lines) + "\n"
        (self.folder / "modules.txt").write_text(text)
        (self.folder / "modules" / NAMES[0]).write_bytes(b"partial")
        value = summary(self.folder)
        self.assertIn("modules: 7/8 files copied, 0 ROM modules, 1 unavailable", value)


if __name__ == "__main__":
    unittest.main()
