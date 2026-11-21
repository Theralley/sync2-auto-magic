"""Run the real native diagnostic through a bounded, hardware-free Windows API shim."""
import os
import shutil
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWN = "20261116-180000-decdiag-ab12"
TARGET = "20261115-205200-dec-edc8"
JOB = f"SyncExtendedPack/_s2am/jobs/{OWN}"
OLD = f"SyncExtendedPack/_s2am/jobs/{TARGET}"
BACKUP = f"SyncExtendedPack/_s2am/backup/{TARGET}"
ACTIVE = "SyncExtendedPack/Apps/Media/AutoKit"
REPORT = f"USB Disk/s2am/reports/{OWN}"
DLLS = ("avcodec-56.dll", "avutil-54.dll", "avformat-56.dll")
LABELS = (*(f"active-{n}" for n in DLLS), *(f"backup-{n}" for n in DLLS),
          *(f"staged-new-{n}" for n in DLLS), "staged-script", "staged-runner",
          "staged-mortscript", "staged-job", "old-done")

WINDOWS = r'''
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD;
typedef int BOOL;
typedef void *HANDLE;
typedef void *HINSTANCE;
typedef wchar_t WCHAR;
typedef wchar_t *LPWSTR;
typedef const wchar_t *LPCWSTR;
typedef struct { DWORD dwLowDateTime, dwHighDateTime; } FILETIME;
typedef union { struct { DWORD LowPart, HighPart; }; uint64_t QuadPart; } ULARGE_INTEGER;
typedef struct { DWORD dwFileAttributes; FILETIME ftCreationTime, ftLastAccessTime,
 ftLastWriteTime; DWORD nFileSizeHigh, nFileSizeLow; } WIN32_FILE_ATTRIBUTE_DATA;
typedef enum { GetFileExInfoStandard } GET_FILEEX_INFO_LEVELS;
typedef struct { HANDLE hProcess, hThread; DWORD dwProcessId, dwThreadId; } PROCESS_INFORMATION;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define GENERIC_READ 0x80000000U
#define GENERIC_WRITE 0x40000000U
#define FILE_SHARE_READ 1
#define CREATE_NEW 1
#define CREATE_ALWAYS 2
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 128
#define FILE_ATTRIBUTE_DIRECTORY 16
#define FILE_ATTRIBUTE_ROMMODULE 8192
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_PATH_NOT_FOUND 3
#define ERROR_ALREADY_EXISTS 183
#define ERROR_FILE_EXISTS 80
#define WAIT_OBJECT_0 0
#define WAIT_TIMEOUT 258
#define WAIT_FAILED 0xffffffffU
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
DWORD GetModuleFileNameW(HINSTANCE, LPWSTR, DWORD);
BOOL GetDiskFreeSpaceExW(LPCWSTR, ULARGE_INTEGER *, ULARGE_INTEGER *, ULARGE_INTEGER *);
BOOL CreateProcessW(LPCWSTR, LPWSTR, void *, void *, BOOL, DWORD, void *, void *, void *, PROCESS_INFORMATION *);
DWORD WaitForSingleObject(HANDLE, DWORD);
BOOL GetExitCodeProcess(HANDLE, DWORD *);
'''

SHIM = r'''
#include "windows.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <sys/stat.h>
#include <errno.h>
#define OWN "20261116-180000-decdiag-ab12"
#define TARGET "20261115-205200-dec-edc8"
#define JOB "/SyncExtendedPack/_s2am/jobs/" OWN
#define OLD "/SyncExtendedPack/_s2am/jobs/" TARGET
#define REPORT "/USB Disk/s2am/reports/" OWN
#define ACTIVE "/SyncExtendedPack/Apps/Media/AutoKit/avcodec-56.dll"
typedef struct { FILE *file; int child, thread, write; char path[1024]; } Handle;
static const char *root, *mode;
static DWORD error, tick;
static unsigned calls, open_count, attr_count;
static int ismode(const char *s) { return !strcmp(mode,s); }
static void narrow(const WCHAR *wide, char *s) {
 size_t i; for(i=0; wide[i]; ++i) { assert(i<1023); s[i]=wide[i]==L'\\'?'/':(char)wide[i]; } s[i]=0;
}
static void host(const char *path, char *out) { assert(path[0]=='/'); snprintf(out,2048,"%s%s",root,path); }
static int prefix(const char *s,const char *p) { return !strncmp(s,p,strlen(p)); }
static int active(const char *s) { return !strcmp(s,ACTIVE); }
static int destination(const char *s) { return prefix(s,REPORT "/files/"); }
static void step(void) { assert(++calls<100000); }
DWORD GetLastError(void) { return error; }
void SetLastError(DWORD v) { error=v; }
DWORD GetTickCount(void) { step(); return tick; }
DWORD GetModuleFileNameW(HINSTANCE instance, LPWSTR out, DWORD count) {
 const char *s=JOB "/s2amdiag.exe"; size_t i; (void)instance;
 assert(strlen(s)+1<count); for(i=0;s[i];++i) out[i]=s[i]=='/'?L'\\':(WCHAR)s[i]; out[i]=0; return (DWORD)i;
}
BOOL GetFileAttributesExW(LPCWSTR path, GET_FILEEX_INFO_LEVELS level, void *result) {
 char p[1024], full[2048]; struct stat st; WIN32_FILE_ATTRIBUTE_DATA *a=result;
 step(); narrow(path,p); host(p,full); assert(level==GetFileExInfoStandard);
 if(ismode("mounterror") && prefix(p,"/USB Disk2/")) { error=5; return FALSE; }
 if(active(p)) { assert(tick<60000); ++attr_count; }
 if(stat(full,&st)) { error=2; return FALSE; }
 memset(a,0,sizeof(*a)); a->dwFileAttributes=S_ISDIR(st.st_mode)?16:128;
 a->nFileSizeLow=(DWORD)st.st_size; a->ftLastWriteTime.dwLowDateTime=7;
 if(active(p) && ismode("changed") && attr_count>1) a->ftLastWriteTime.dwLowDateTime=8;
 if(active(p) && ismode("oversize")) a->nFileSizeLow=4U*1024U*1024U+1;
 return TRUE;
}
BOOL CreateDirectoryW(LPCWSTR path, void *security) {
 char p[1024],full[2048]; (void)security; step(); narrow(path,p); host(p,full);
 assert(!strcmp(p,"/USB Disk/s2am") || !strcmp(p,"/USB Disk/s2am/reports") ||
        !strcmp(p,REPORT) || !strcmp(p,REPORT "/files"));
 if(ismode("reportdirfail") && !strcmp(p,REPORT)) { error=5; return FALSE; }
 if(!mkdir(full,0700)) return TRUE; error=errno==EEXIST?183:5; return FALSE;
}
HANDLE CreateFileW(LPCWSTR path,DWORD access,DWORD share,void *sec,DWORD disp,DWORD flags,HANDLE tmpl) {
 char p[1024],full[2048]; Handle *h; FILE *f; (void)flags; step(); narrow(path,p); host(p,full);
 assert(sec==NULL && tmpl==NULL && share==FILE_SHARE_READ);
 if(access==GENERIC_READ) {
  assert(disp==OPEN_EXISTING);
  assert(prefix(p,"/SyncExtendedPack/Apps/Media/AutoKit/") || prefix(p,OLD "/") ||
   prefix(p,"/SyncExtendedPack/_s2am/backup/" TARGET "/") ||
   !strcmp(p,"/SyncExtendedPack/_s2am/done/" TARGET ".txt") || !strcmp(p,JOB "/target.txt"));
  if(active(p)) { assert(tick<60000); if(ismode("openfail")) { error=32; return INVALID_HANDLE_VALUE; } }
  f=fopen(full,"rb");
 } else {
  assert(access==GENERIC_WRITE && (disp==CREATE_NEW || disp==CREATE_ALWAYS));
  assert(!strcmp(p,JOB "/native-entry.txt") || prefix(p,REPORT "/"));
  if(ismode("outputfail") && destination(p)) { error=112; return INVALID_HANDLE_VALUE; }
  if(disp==CREATE_NEW) { struct stat st; if(!stat(full,&st)) { error=80; return INVALID_HANDLE_VALUE; } }
  f=fopen(full,"wb");
 }
 if(!f) { error=2; return INVALID_HANDLE_VALUE; }
 h=calloc(1,sizeof(*h)); h->file=f; h->write=access==GENERIC_WRITE; strcpy(h->path,p); ++open_count; return h;
}
BOOL ReadFile(HANDLE handle,void *data,DWORD n,DWORD *got,void *overlap) {
 Handle *h=handle; (void)overlap; step(); assert(!h->write);
 if(active(h->path)) { assert(tick<60000); if(ismode("readfail")) { error=30; *got=0; return FALSE; } }
 *got=(DWORD)fread(data,1,n,h->file);
 if(active(h->path) && ismode("expire-read") && *got) tick=60000;
 return TRUE;
}
BOOL WriteFile(HANDLE handle,const void *data,DWORD n,DWORD *written,void *overlap) {
 Handle *h=handle; (void)overlap; step(); assert(h->write);
 if(destination(h->path)) {
  assert(tick<60000);
  if(ismode("zerowrite")) { *written=0; error=29; return TRUE; }
  if((ismode("shortwrite") || ismode("expire-write")) && n>17) n=17;
 }
 if(ismode("reportfail") && !strcmp(h->path,REPORT "/decdiag.txt")) { error=112; *written=0; return FALSE; }
 *written=(DWORD)fwrite(data,1,n,h->file);
 if(destination(h->path) && ismode("expire-write")) tick=60000;
 return *written==n;
}
BOOL FlushFileBuffers(HANDLE handle) {
 Handle *h=handle; step(); if(ismode("flushfail") && destination(h->path)) { error=29; return FALSE; }
 if(ismode("reportflush") && !strcmp(h->path,REPORT "/decdiag.txt")) { error=29; return FALSE; }
 return fflush(h->file)==0;
}
BOOL CloseHandle(HANDLE handle) {
 Handle *h=handle; int fail=ismode("closefail") && destination(h->path); step();
 if(ismode("reportclose") && !strcmp(h->path,REPORT "/decdiag.txt")) fail=1;
 if(h->file) { fclose(h->file); --open_count; }
 free(h); if(fail) error=6; return !fail;
}
BOOL GetDiskFreeSpaceExW(LPCWSTR path,ULARGE_INTEGER *available,ULARGE_INTEGER *total,ULARGE_INTEGER *free_all) {
 char p[1024]; narrow(path,p); step();
 available->QuadPart=1024ULL*1024*1024; total->QuadPart=2ULL*1024*1024*1024; *free_all=*available;
 if(ismode("spacefail")) { error=5; return FALSE; } return TRUE;
}
BOOL CreateProcessW(LPCWSTR path,LPWSTR command,void *a,void *b,BOOL inherit,DWORD flags,
 void *env,void *cwd,void *startup,PROCESS_INFORMATION *pi) {
 char p[1024],cmd[1024]; Handle *h,*t; step(); narrow(path,p); narrow(command,cmd);
 assert(!a && !b && !inherit && !flags && !env && !cwd && !startup);
 assert(!strcmp(p,JOB "/MortScript.exe") || !strcmp(p,JOB "/s2amclock.exe"));
 if(!strcmp(p,JOB "/MortScript.exe")) {
  assert(!strcmp(cmd,"\"/SyncExtendedPack/_s2am/jobs/" OWN "/probe.mscr\""));
  if(ismode("probefail")) { error=193; return FALSE; }
 } else assert(!strcmp(cmd,"\"/USB Disk/s2am/reports/" OWN "/clock.txt\""));
 h=calloc(1,sizeof(*h)); h->child=strstr(p,"MortScript")?1:2; strcpy(h->path,p);
 t=calloc(1,sizeof(*t)); t->thread=1; pi->hProcess=h; pi->hThread=t; pi->dwProcessId=7; pi->dwThreadId=8;
 return TRUE;
}
static void child_marker(int child) {
 char full[2048]; FILE *f; host(child==1?JOB "/probe-done.txt":REPORT "/clock.txt",full);
 f=fopen(full,"wb"); assert(f); fputs(child==1?OWN:"clock sample",f); fclose(f);
}
DWORD WaitForSingleObject(HANDLE handle,DWORD ms) {
 Handle *h=handle; step(); assert(h->child && ms<=15000);
 if((h->child==1 && (ismode("probetimeout") || ismode("probelate"))) ||
    (h->child==2 && ismode("clocktimeout"))) {
  tick+=ms; if(ismode("probelate")) child_marker(h->child); return WAIT_TIMEOUT;
 }
 if(ismode("waitfail")) { error=6; return WAIT_FAILED; }
 if(!ismode("nomarker")) child_marker(h->child); return WAIT_OBJECT_0;
}
BOOL GetExitCodeProcess(HANDLE handle,DWORD *code) {
 Handle *h=handle; step(); assert(h->child);
 if(ismode("exitfail")) { error=6; return FALSE; } *code=0; return TRUE;
}
int WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
int main(int argc,char **argv) {
 int result; WCHAR command[]=L""; assert(argc==3); root=argv[1]; mode=argv[2];
 result=WinMain(NULL,NULL,command,0); assert(open_count==0); printf("return=%d calls=%u tick=%u\n",result,calls,tick);
 return 0;
}
'''


@unittest.skipUnless(shutil.which("cc"), "needs a host C compiler")
@unittest.skipIf(os.name == "nt", "its stand-ins use Unix C calls: needs a Unix host (#6)")
class Diagnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = tempfile.TemporaryDirectory()
        cls.work = Path(cls.compiler.name)
        source = ROOT / "s2am/native/s2amdiag.c"
        if not source.is_file():
            raise AssertionError("native diagnostic source does not exist yet")
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "shim.c").write_text(SHIM)
        cls.exe = cls.work / "diag"
        result = subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                                 "-Wno-misleading-indentation", "-I", str(cls.work), str(source),
                                 str(cls.work / "shim.c"), "-o", str(cls.exe)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.compiler.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contents = {}
        def put(path, data):
            dest = self.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        self.put = put
        put(f"{JOB}/target.txt", (TARGET + "\r\n").encode())
        put(f"USB Disk/s2am/pending/{OWN}.json", b"{}")
        for group, (prefix, folder, nameprefix) in enumerate(
                (("active", ACTIVE, ""), ("backup", BACKUP, ""), ("staged-new", OLD, "new-"))):
            for i, name in enumerate(DLLS):
                data = bytes((j+i+group*53) % 256 for j in range(7001+i))
                put(f"{folder}/{nameprefix}{name}", data)
                self.contents[f"{prefix}-{name}"] = data
        for label, path in (("staged-script", f"{OLD}/s2amjob.mscr"),
                            ("staged-runner", f"{OLD}/s2amjob.exe"),
                            ("staged-mortscript", f"{OLD}/MortScript.exe"),
                            ("staged-job", f"{OLD}/job.json"),
                            ("old-done", f"SyncExtendedPack/_s2am/done/{TARGET}.txt")):
            data = label.encode(); put(path, data); self.contents[label] = data
        for name in ("MortScript.exe", "probe.mscr", "s2amclock.exe"):
            put(f"{JOB}/{name}", b"fixture")

    def run_diag(self, mode="normal"):
        result = subprocess.run([str(self.exe), str(self.root), mode], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.output = result.stdout
        path = self.root / REPORT / "decdiag.txt"
        self.rows = [line.split("|") for line in path.read_text().splitlines()] if path.exists() else []
        return {row[1]: row for row in self.rows if row[0] == "F"}

    def done(self):
        return (self.root / REPORT / "done.txt").exists()

    def child(self, kind):
        return next(row for row in self.rows if row[0] == kind)

    def test_complete_snapshot_has_exact_files_crc_and_frozen_child_results(self):
        rows = self.run_diag()
        self.assertEqual(self.rows[0], ["S", "s2am-decdiag-v1", OWN, TARGET])
        self.assertEqual(tuple(rows), LABELS)
        self.assertEqual(self.rows[-1], ["T", "complete"])
        self.assertEqual((self.root / REPORT / "done.txt").read_text(), OWN)
        self.assertTrue((self.root / JOB / "native-entry.txt").is_file())
        for label, row in rows.items():
            self.assertEqual(len(row), 11)
            self.assertEqual(row[7:9], ["copied", "0"])
            self.assertEqual(int(row[9]), len(self.contents[label]))
            self.assertEqual(int(row[10]), zlib.crc32(self.contents[label]))
            self.assertEqual((self.root / REPORT / "files" / label).read_bytes(), self.contents[label])
        self.assertEqual(self.child("P"), ["P", "exited", "0", "0", "1", "0", "1"])
        self.assertEqual(self.child("C"), ["C", "exited", "0", "0", "1", "0", "1"])
        self.assertEqual(len([r for r in self.rows if r[0] == "D"]), 5)

    def test_source_and_output_failures_are_rows_not_false_copies(self):
        for mode, status in (("openfail", "open-error"), ("readfail", "read-error"),
                             ("outputfail", "create-error"), ("zerowrite", "write-error"),
                             ("flushfail", "flush-error"), ("closefail", "close-error"),
                             ("changed", "changed"), ("oversize", "too-large")):
            with self.subTest(mode=mode):
                if (self.root / REPORT).exists(): shutil.rmtree(self.root / REPORT)
                (self.root / JOB / "probe-done.txt").unlink(missing_ok=True)
                rows = self.run_diag(mode)
                self.assertEqual(rows[LABELS[0]][7], status)
                self.assertEqual(rows[LABELS[0]][10], "0")
                self.assertTrue(self.done())

    def test_short_writes_complete_and_deadline_stops_new_copy_calls(self):
        rows = self.run_diag("shortwrite")
        self.assertEqual(rows[LABELS[0]][7], "copied")
        self.assertEqual((self.root / REPORT / "files" / LABELS[0]).read_bytes(), self.contents[LABELS[0]])
        for mode in ("expire-write", "expire-read"):
            with self.subTest(mode=mode):
                shutil.rmtree(self.root / REPORT)
                (self.root / JOB / "probe-done.txt").unlink(missing_ok=True)
                rows = self.run_diag(mode)
                self.assertTrue(all(r[7] == "error-budget" for r in rows.values()))
                self.assertEqual(self.child("P")[1], "error-budget")
                self.assertEqual(self.child("C")[1], "error-budget")

    def test_missing_source_does_not_claim_all_files_copied(self):
        (self.root / ACTIVE / DLLS[0]).unlink()
        rows = self.run_diag()
        self.assertEqual(rows[LABELS[0]][2:], ["0", "0", "0", "0", "0", "attrs-error", "2", "0", "0"])
        self.assertTrue(self.done())

    def test_report_failure_never_creates_done(self):
        for mode in ("reportfail", "reportflush", "reportclose"):
            with self.subTest(mode=mode):
                if (self.root / REPORT).exists(): shutil.rmtree(self.root / REPORT)
                (self.root / JOB / "probe-done.txt").unlink(missing_ok=True)
                self.run_diag(mode)
                self.assertFalse(self.done())

    def test_report_directory_failure_leaves_native_breadcrumb(self):
        self.run_diag("reportdirfail")
        self.assertFalse(self.done())
        self.assertTrue((self.root / JOB / "native-entry.txt").exists())
        self.assertIn("fresh-report-failed|5", (self.root / JOB / "native-entry.txt").read_text())

    def test_unreadable_pending_mount_cannot_establish_unique_destination(self):
        self.run_diag("mounterror")
        self.assertFalse(self.rows)
        self.assertFalse(self.done())

    def test_failed_storage_query_keeps_error_and_zeros_unknown_sizes(self):
        self.run_diag("spacefail")
        for row in self.rows:
            if row[0] == "D":
                self.assertEqual(row[4:], ["0", "5", "0", "0", "0", "0"])

    def test_ambiguous_or_absent_pending_mount_leaves_no_report(self):
        self.put(f"USB Disk2/s2am/pending/{OWN}.json", b"{}")
        self.run_diag()
        self.assertFalse(self.rows)
        self.assertFalse(self.done())
        (self.root / f"USB Disk2/s2am/pending/{OWN}.json").unlink()
        (self.root / f"USB Disk/s2am/pending/{OWN}.json").unlink()
        self.run_diag()
        self.assertFalse(self.rows)

    def test_replay_preserves_existing_report_and_active_files(self):
        before = {p: p.read_bytes() for p in (self.root / ACTIVE).iterdir()}
        self.run_diag()
        path = self.root / REPORT / "decdiag.txt"
        first = path.read_bytes()
        self.run_diag("probefail")
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.root / ACTIVE).iterdir()})

    def test_probe_launch_wait_and_completion_are_separate(self):
        for mode, status, marker in (("probefail", "launch-error", "0"),
                                     ("probetimeout", "timeout", "0"),
                                     ("probelate", "timeout", "1"),
                                     ("nomarker", "exited", "0"),
                                     ("waitfail", "wait-error", "0"),
                                     ("exitfail", "exit-error", "1")):
            with self.subTest(mode=mode):
                if (self.root / REPORT).exists(): shutil.rmtree(self.root / REPORT)
                (self.root / JOB / "probe-done.txt").unlink(missing_ok=True)
                self.run_diag(mode)
                row = self.child("P")
                self.assertEqual((row[1], row[-1]), (status, marker))
                if status != "exited": self.assertEqual(row[4], "0")
                self.assertTrue(self.done())

    def test_stale_probe_marker_prevents_launch_and_clock_is_optional(self):
        self.put(f"{JOB}/probe-done.txt", b"old")
        (self.root / JOB / "s2amclock.exe").unlink()
        self.run_diag("probefail")
        self.assertEqual(self.child("P")[1], "stale-marker")
        self.assertEqual(self.child("C")[1], "unavailable")
        self.assertTrue(self.done())

    def test_clock_timeout_is_recorded_without_killing_child(self):
        self.run_diag("clocktimeout")
        self.assertEqual(self.child("C"), ["C", "timeout", "0", "258", "0", "0", "0"])
        self.assertTrue(self.done())

    def test_target_path_injection_or_wrong_kind_fails_before_usb_report(self):
        for target in (b"../elsewhere", b"20261115-205200-clock-edc8", b"20261115-205200-dec-edc8\x00evil",
                       (TARGET + "\nextra").encode(), b"x" * 200):
            with self.subTest(target=target):
                self.put(f"{JOB}/target.txt", target)
                self.run_diag()
                self.assertFalse(self.rows)
                self.assertFalse(self.done())


if __name__ == "__main__":
    unittest.main()
