"""Focused real native collector under deterministic CE fakes; no device access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

WINDOWS = r'''
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD,UINT; typedef int32_t LONG; typedef int BOOL;
typedef unsigned char BYTE; typedef wchar_t WCHAR; typedef const WCHAR *LPCWSTR;
typedef WCHAR *LPWSTR; typedef void *HANDLE,*HMODULE,*HINSTANCE,*LPVOID;
typedef union { struct { DWORD LowPart; LONG HighPart; }; int64_t QuadPart; } LARGE_INTEGER;
typedef struct { DWORD dwLowDateTime,dwHighDateTime; } FILETIME;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define INVALID_FILE_ATTRIBUTES 0xffffffffu
#define GENERIC_WRITE 0x40000000u
#define FILE_SHARE_READ 1
#define CREATE_NEW 1
#define FILE_ATTRIBUTE_NORMAL 128
#define MB_OK 0
#define MB_ICONINFORMATION 64
#define MB_ICONEXCLAMATION 48
DWORD GetTickCount(void), GetLastError(void), GetCurrentProcessId(void),GetCurrentThreadId(void);
void SetLastError(DWORD),Sleep(DWORD);
DWORD GetModuleFileNameW(HINSTANCE,LPWSTR,DWORD),GetFileAttributesW(LPCWSTR);
HMODULE GetModuleHandleW(LPCWSTR),LoadLibraryW(LPCWSTR);
BOOL FreeLibrary(HMODULE),QueryPerformanceCounter(LARGE_INTEGER*),QueryPerformanceFrequency(LARGE_INTEGER*);
void (*GetProcAddressW(HMODULE,LPCWSTR))(void);
HANDLE CreateFileW(LPCWSTR,DWORD,DWORD,void*,DWORD,DWORD,HANDLE);
BOOL WriteFile(HANDLE,const void*,DWORD,DWORD*,void*),FlushFileBuffers(HANDLE),CloseHandle(HANDLE),MoveFileW(LPCWSTR,LPCWSTR);
int MessageBoxW(HANDLE,LPCWSTR,LPCWSTR,UINT);
'''

SHIM = r'''
#include "windows.h"
#include "load_observer_protocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <sys/stat.h>
static const char *root,*mode; static DWORD tick,err,serial,rounds,proc_at,thread_at,opened,closed;
static FILE *out; static int writing,counter_calls,frequency_calls; static uint64_t elapsed;
static int is(const char*s){return !strcmp(mode,s);}
static void path(char*p,const char*name){snprintf(p,2048,"%s/%s",root,name);}
DWORD GetTickCount(void){return tick;} DWORD GetLastError(void){return err;} void SetLastError(DWORD e){err=e;}
DWORD GetCurrentProcessId(void){return 42;} DWORD GetCurrentThreadId(void){return 7;}
void Sleep(DWORD n){assert(n==5000);tick+=n;elapsed+=n;if(is("budget")){tick+=400000;elapsed+=400000;}}
DWORD GetModuleFileNameW(HINSTANCE h,LPWSTR p,DWORD n){const WCHAR*s=L"\\USB Disk\\S2AM-LOAD\\S2AMLOAD.EXE";assert(!h&&n==260);if(is("pathfail"))return 0;if(is("pathfull"))return 260;wcscpy(p,s);return (DWORD)wcslen(s);}
DWORD GetFileAttributesW(LPCWSTR p){char f[2048];struct stat st;assert(wcsstr(p,L"LOAD.CSV"));path(f,"LOAD.CSV");if(is("attrfail")){err=5;return 0xffffffffu;}if(!stat(f,&st))return 128;err=2;return 0xffffffffu;}
HMODULE GetModuleHandleW(LPCWSTR p){assert(!wcscmp(p,L"coredll.dll"));return (HMODULE)1;}
HMODULE LoadLibraryW(LPCWSTR p){assert(!wcscmp(p,L"\\Windows\\toolhelp.dll"));if(is("loadfail")){err=126;return NULL;}return (HMODULE)2;}
BOOL FreeLibrary(HMODULE h){assert(h==(HMODULE)2);return !is("freefail");}
BOOL QueryPerformanceCounter(LARGE_INTEGER*q){counter_calls++;if(is("qpcfail")&&counter_calls==12){err=5;return 0;}q->QuadPart=(int64_t)elapsed*8000+(++serial);if(is("frozen"))q->QuadPart=1;return 1;}
BOOL QueryPerformanceFrequency(LARGE_INTEGER*q){q->QuadPart=8000000;if(is("qpfchange")&&frequency_calls++)q->QuadPart=8000001;return 1;}
static HANDLE snap(DWORD flags,DWORD pid){assert(flags==0x40000006u&&!pid&&!writing);rounds++;proc_at=thread_at=0;if(is("snapshotfail")){err=5;return INVALID_HANDLE_VALUE;}opened++;return (HANDLE)4;}
static BOOL process(HANDLE h,LoadProcess*p){assert(h==(HANDLE)4&&p->dwSize==sizeof(*p));DWORD limit=is("processcap")?257:is("processexact")?256:2;if(proc_at>=limit){err=is("processzeroenum")?0:18;return 0;}p->th32ProcessID=limit>2?1000+proc_at:proc_at?99:42;wcscpy(p->szExeFile,is("sanitize")?L"C:\\private\\Auto,Kit.exe":proc_at?L"AutoKit.exe":L"S2AMLOAD.EXE");proc_at++;return 1;}
static BOOL thread(HANDLE h,LoadThread*t){DWORD limit=is("truncated")?513:is("threadexact")?512:2;assert(h==(HANDLE)4&&t->dwSize==sizeof(*t));if(thread_at>=limit||(is("partial")&&thread_at==1)){err=is("partial")?5:is("zeroenum")?0:18;return 0;}t->th32ThreadID=7+thread_at;t->th32OwnerProcessID=thread_at?99:42;t->tpBasePri=is("wide")?INT32_MIN:251;t->tpDeltaPri=is("wide")?INT32_MAX:-1;thread_at++;return 1;}
static BOOL snapclose(HANDLE h){assert(h==(HANDLE)4);closed++;return !is("snapshotclosefail");}
static HANDLE openthread(DWORD access,BOOL inherit,DWORD tid){assert(access==0x40&&!inherit&&!writing);if(is("openfail")&&tid==8){err=5;return NULL;}opened++;return (HANDLE)(uintptr_t)(0x10000+tid);}
static BOOL times(HANDLE h,FILETIME*c,FILETIME*e,FILETIME*k,FILETIME*u){DWORD tid=(DWORD)((uintptr_t)h-0x10000);uint64_t value=((uint64_t)1<<32)+(uint64_t)elapsed*1000;if(is("wide"))value+=((uint64_t)1<<63);assert(tid>=7&&!writing);if(is("readfail")&&tid==8){err=5;return 0;}memset(c,0,sizeof(*c));memset(e,0,sizeof(*e));memset(k,0,sizeof(*k));memset(u,0,sizeof(*u));c->dwLowDateTime=is("zerocreation")&&tid==8?0:100+tid;k->dwLowDateTime=(DWORD)value;k->dwHighDateTime=(DWORD)(value>>32);u->dwLowDateTime=(DWORD)(value/2);u->dwHighDateTime=(DWORD)((value/2)>>32);return 1;}
static DWORD idle(void){return is("idleunsupported")?0xffffffffu:tick/2;}
void (*GetProcAddressW(HMODULE h,LPCWSTR n))(void){assert(h==(HMODULE)1||h==(HMODULE)2);if((is("missingexport")&&!wcscmp(n,L"GetThreadTimes"))||(is("noidle")&&!wcscmp(n,L"GetIdleTime")))return NULL;
#define RET(name,fn) if(!wcscmp(n,L##name))return (void(*)(void))fn
RET("CreateToolhelp32Snapshot",snap);RET("Process32First",process);RET("Process32Next",process);RET("Thread32First",thread);RET("Thread32Next",thread);RET("CloseToolhelp32Snapshot",snapclose);RET("OpenThread",openthread);RET("GetThreadTimes",times);RET("GetIdleTime",idle);assert(0);return NULL;}
HANDLE CreateFileW(LPCWSTR p,DWORD a,DWORD sh,void*s,DWORD d,DWORD attr,HANDLE t){char f[2048];assert(wcsstr(p,L"LOAD.TMP")&&a==GENERIC_WRITE&&sh==FILE_SHARE_READ&&!s&&d==CREATE_NEW&&attr==128&&!t);path(f,"LOAD.TMP");out=fopen(f,"wx");if(!out){err=80;return INVALID_HANDLE_VALUE;}return (HANDLE)out;}
BOOL WriteFile(HANDLE h,const void*b,DWORD n,DWORD*got,void*o){assert(h==(HANDLE)out&&!o);writing=1;if(is("writefail")){*got=0;err=112;writing=0;return 0;}if(is("zerowrite")){*got=0;writing=0;return 1;}if(is("shortwrite")&&n>3)n=3;*got=(DWORD)fwrite(b,1,n,out);writing=0;return *got==n;}
BOOL FlushFileBuffers(HANDLE h){assert(h==(HANDLE)out);if(is("flushfail")){err=1117;return 0;}return fflush(out)==0;}
BOOL CloseHandle(HANDLE h){if(h==(HANDLE)out){int r=fclose(out);out=NULL;return !r&&!is("fileclosefail");}assert((uintptr_t)h>=0x10007);closed++;return !is("threadclosefail");}
BOOL MoveFileW(LPCWSTR from,LPCWSTR to){char a[2048],b[2048];struct stat st;assert(wcsstr(from,L"LOAD.TMP")&&wcsstr(to,L"LOAD.CSV")&&!out);path(a,"LOAD.TMP");path(b,"LOAD.CSV");if(is("racedest")){FILE*f=fopen(b,"wb");assert(f);fputs("external",f);fclose(f);}if(is("movefail")||!stat(b,&st)){err=80;return 0;}return rename(a,b)==0;}
int MessageBoxW(HANDLE h,LPCWSTR text,LPCWSTR title,UINT flags){(void)h;(void)text;(void)title;(void)flags;return 1;}
int WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
int main(int argc,char**argv){int result;assert(argc==3);root=argv[1];mode=argv[2];if(is("tickwrap"))tick=0xfffff000u;result=WinMain(NULL,NULL,is("args")?L"unexpected":L"",0);assert(!out);assert(opened==closed);return result;}
'''


class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="s2am-load-host-"))
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "shim.c").write_text(SHIM)
        cls.program = cls.work / "collector"
        cmd = [shutil.which("clang") or "cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=address,undefined", "-DS2AM_LOAD_HOST_TEST", "-I", str(cls.work),
               "-I", str(ROOT / "s2am/native"), str(ROOT / "s2am/native/s2amload.c"),
               str(cls.work / "shim.c"), "-o", str(cls.program)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode:
            raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_case(self, mode="ok", existing=None):
        folder = Path(tempfile.mkdtemp(prefix="s2am-load-fixture-"))
        self.addCleanup(shutil.rmtree, folder)
        if existing:
            (folder / existing).write_bytes(b"untouched")
        p = subprocess.run([str(self.program), str(folder), mode], capture_output=True, text=True,
                           env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        self.assertNotIn("Sanitizer", p.stderr, p.stderr)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return p, folder

    def test_normal_publishes_full_width_data_and_sixty_rounds(self):
        p, f = self.run_case()
        self.assertEqual(p.returncode, 0, p.stderr)
        b = (f / "LOAD.CSV").read_bytes()
        self.assertFalse((f / "LOAD.TMP").exists())
        self.assertTrue(b.startswith(b"S2AM-LOAD,1\r\nmeta,60,5000,512,256,42,7\r\n"))
        self.assertEqual(b.count(b"\r\nround,"), 60)
        self.assertTrue(b.endswith(b"frequency,end,8000000\r\ncomplete,60\r\n"))
        self.assertIn(b"4294967296", b)

    def test_existing_csv_and_scratch_are_not_overwritten(self):
        for name in ("LOAD.CSV", "LOAD.TMP"):
            with self.subTest(name=name):
                p, f = self.run_case(existing=name)
                self.assertEqual(p.returncode, 1)
                self.assertEqual((f / name).read_bytes(), b"untouched")

    def test_failures_never_publish(self):
        for mode in ("args", "loadfail", "missingexport", "qpcfail", "frozen", "qpfchange",
                     "writefail", "zerowrite", "flushfail", "fileclosefail", "movefail",
                     "threadclosefail", "snapshotclosefail", "freefail", "pathfail", "pathfull",
                     "attrfail", "budget"):
            with self.subTest(mode=mode):
                p, f = self.run_case(mode)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertFalse((f / "LOAD.CSV").exists())

    def test_read_failures_and_snapshot_failures_are_explicit_partial_data(self):
        for mode, marker in (("openfail", b",open_fail,5\r\n"), ("readfail", b",times_fail,5\r\n"),
                             ("zerocreation", b",no_creation,0\r\n"),
                             ("idleunsupported", b"idle,0,0,"), ("partial", b",5,0,0,0\r\n"),
                             ("snapshotfail", b",5,0,5,0\r\n")):
            with self.subTest(mode=mode):
                p, f = self.run_case(mode)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn(marker, (f / "LOAD.CSV").read_bytes())

    def test_short_writes_are_completed(self):
        p, f = self.run_case("shortwrite")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((f / "LOAD.CSV").read_bytes().endswith(b"complete,60\r\n"))

    def test_thread_cap_is_flagged_and_bounded(self):
        p, f = self.run_case("truncated")
        self.assertEqual(p.returncode, 0, p.stderr)
        b = (f / "LOAD.CSV").read_bytes()
        self.assertEqual(b.count(b"\r\nthread,"), 60 * 512)
        self.assertIn(b",0,1,0,0\r\n", b)
        self.assertLess(len(b), 8 * 1024 * 1024)

    def test_exact_caps_and_process_overflow(self):
        for mode, processes, threads in (("processexact",256,2),("processcap",256,2),
                                         ("threadexact",2,512)):
            with self.subTest(mode=mode):
                p,f=self.run_case(mode)
                self.assertEqual(p.returncode,0,p.stderr)
                b=(f/"LOAD.CSV").read_bytes()
                self.assertEqual(b.count(b"\r\nprocess,"),60*processes)
                self.assertEqual(b.count(b"\r\nthread,"),60*threads)
                header=next(r for r in b.split(b"\r\n") if r.startswith(b"round,"))
                self.assertEqual(header.split(b",")[-1],b"1" if mode=="processcap" else b"0")
                self.assertEqual(header.split(b",")[-3],b"0")

    def test_optional_idle_and_unexpected_enum_zero_are_explicit(self):
        for mode, marker in (("noidle",b",0,127\r\n"),("zeroenum",b",13,0,0,0\r\n"),
                             ("processzeroenum",b",0,0,13,0\r\n")):
            with self.subTest(mode=mode):
                p,f=self.run_case(mode)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertIn(marker,(f/"LOAD.CSV").read_bytes())

    def test_tick_wrap_and_unsigned64_signed_priorities(self):
        for mode in ("tickwrap","wide"):
            p,f=self.run_case(mode)
            self.assertEqual(p.returncode,0,p.stderr)
            if mode=="wide":
                self.assertIn(b",-2147483648,2147483647,ok,0",(f/"LOAD.CSV").read_bytes())
                self.assertIn(b"922337204",(f/"LOAD.CSV").read_bytes())

    def test_destination_race_never_replaces_new_file(self):
        p,f=self.run_case("racedest")
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertEqual((f/"LOAD.CSV").read_bytes(),b"external")
        self.assertTrue((f/"LOAD.TMP").read_bytes().endswith(b"complete,60\r\n"))

    def test_process_basename_is_sanitized_without_path(self):
        p,f=self.run_case("sanitize")
        self.assertEqual(p.returncode,0,p.stderr)
        b=(f/"LOAD.CSV").read_bytes()
        self.assertIn(b"Auto?Kit.exe",b)
        self.assertNotIn(b"private",b)

    def test_real_producer_outputs_match_strict_host_parser(self):
        from s2am.load_observer import analyze
        modes=("ok","shortwrite","openfail","readfail","zerocreation","partial",
               "snapshotfail","noidle","truncated","processcap","processexact",
               "threadexact","zeroenum","processzeroenum","wide","tickwrap","sanitize")
        for mode in modes:
            with self.subTest(mode=mode):
                p,f=self.run_case(mode)
                self.assertEqual(p.returncode,0,p.stderr)
                r=analyze((f/"LOAD.CSV").read_bytes())
                self.assertEqual(len(r["rounds"]),60)
                self.assertFalse(r["qualified"] or r["cpu_rate_qualified"] or r["write_authorized"])
                self.assertEqual(r["rounds"][0]["self"]["creation"],107)
                self.assertGreater(r["rounds"][0]["self"]["kernel"],1<<32 if mode=="wide" else (1<<32)-1)
                if mode=="openfail": self.assertEqual(r["partial"]["open_fail"],60)
                if mode=="readfail": self.assertEqual(r["partial"]["times_fail"],60)
                if mode=="zerocreation": self.assertEqual(r["partial"]["no_creation"],60)
                if mode=="truncated": self.assertEqual(r["partial"]["thread_truncated_rounds"],60)
                if mode=="processcap": self.assertEqual(r["partial"]["process_truncated_rounds"],60)


if __name__ == "__main__":
    unittest.main()
