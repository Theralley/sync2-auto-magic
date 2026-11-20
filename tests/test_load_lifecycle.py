"""Focused start/collect controller tests under deterministic CE fakes.

Target: the lead's s2amloadctl.c (WinMain, no args), compiled for the host against a
fake windows.h + mode-driven shim, same pattern as tests/test_load_native.py. The
portable default native root is this repo (Path(__file__).resolve().parents[1]) so the
file works under GHA/Linux after cherry-pick; for peer-local RED/GREEN against the lead
tree set S2AM_LOAD_NATIVE_ROOT explicitly. Frozen contract: docs/LOAD-START-COLLECT.md.

A bounded synthetic payload is hash-pinned via LOAD_EXPECTED_SHA256 / LOAD_EXPECTED_SIZE;
the fake filesystem maps ONLY the fixed USB folder and the fixed car run path into a
per-test temp root. No real device, server or filesystem outside testtmp. A start receipt
is a startup observation, not proof of journal completion; the desktop strict parser
stays authoritative for observations. Fault modes are stage-specific (internal copy,
readback, receipt, USB readback) and the process count is asserted, including repeated
invocation on the same fixture to prove the controller never relaunches.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

NATIVE_ROOT = Path(os.environ.get("S2AM_LOAD_NATIVE_ROOT",
                                  Path(__file__).resolve().parents[1]))
CONTROLLER = NATIVE_ROOT / "s2am/native/s2amloadctl.c"

RUN_DIR_NAME = "20261120-load-44748284729"
PAYLOAD = b"S2AM-LOAD-SYNTHETIC-PAYLOAD\x00" + bytes(range(256)) * 4
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
PAYLOAD_SIZE = len(PAYLOAD)
CLAIM = b"S2AM-LOAD-START,1\r\n" + PAYLOAD_SHA.encode() + b"\r\n"
# Multi-chunk journal so scan/copy exercise positive read accumulation (>4096 bytes).
JOURNAL = b"S2AM-LOAD,1\r\n" + b"x" * 9000 + b"complete,60\r\n"

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
typedef struct { HANDLE hProcess,hThread; DWORD dwProcessId,dwThreadId; } PROCESS_INFORMATION;
typedef struct { DWORD dwSize; } STARTUPINFOW;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define INVALID_FILE_ATTRIBUTES 0xffffffffu
#define GENERIC_READ 0x80000000u
#define GENERIC_WRITE 0x40000000u
#define FILE_SHARE_READ 1
#define FILE_SHARE_WRITE 2
#define CREATE_NEW 1
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 128
#define FILE_ATTRIBUTE_DIRECTORY 16
#define FILE_BEGIN 0
#define WAIT_TIMEOUT 258
#define WAIT_OBJECT_0 0
#define WAIT_FAILED 0xffffffffu
#define MB_OK 0
#define MB_ICONINFORMATION 64
#define MB_ICONEXCLAMATION 48
DWORD GetTickCount(void),GetLastError(void),GetCurrentProcessId(void),GetCurrentThreadId(void);
void SetLastError(DWORD),Sleep(DWORD);
DWORD GetModuleFileNameW(HINSTANCE,LPWSTR,DWORD),GetFileAttributesW(LPCWSTR),GetFileSize(HANDLE,DWORD*);
DWORD WaitForSingleObject(HANDLE,DWORD),SetFilePointer(HANDLE,LONG,LONG*,DWORD);
HMODULE GetModuleHandleW(LPCWSTR),LoadLibraryW(LPCWSTR);
BOOL FreeLibrary(HMODULE),QueryPerformanceCounter(LARGE_INTEGER*),QueryPerformanceFrequency(LARGE_INTEGER*);
void (*GetProcAddressW(HMODULE,LPCWSTR))(void);
HANDLE CreateFileW(LPCWSTR,DWORD,DWORD,void*,DWORD,DWORD,HANDLE);
BOOL CreateProcessW(LPCWSTR,LPWSTR,void*,void*,BOOL,DWORD,void*,LPCWSTR,STARTUPINFOW*,PROCESS_INFORMATION*);
BOOL CreateDirectoryW(LPCWSTR,void*);
BOOL ReadFile(HANDLE,void*,DWORD,DWORD*,void*);
BOOL WriteFile(HANDLE,const void*,DWORD,DWORD*,void*),FlushFileBuffers(HANDLE),CloseHandle(HANDLE),MoveFileW(LPCWSTR,LPCWSTR);
int MessageBoxW(HANDLE,LPCWSTR,LPCWSTR,UINT);
'''

SHIM = r'''
#include "windows.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <sys/stat.h>
#include <errno.h>
#define RUN_DIR_NAME "20261120-load-44748284729"
static const char *root,*mode; static DWORD tick,err,sleeps,wrap_count; static int process_created,opened,closed,wait_calls;
static int is(const char*s){return !strcmp(mode,s);}
static void w2c(char*out,const WCHAR*in){while(*in){*out++=(*in==L'\\')?'/':(char)*in;in++;}*out=0;}
static void hostpath(char*out,LPCWSTR p){
    const WCHAR*u=wcsstr(p,L"\\S2AM-LOAD\\");const WCHAR*c=wcsstr(p,L"\\SyncExtendedPack\\");char rest[2048];
    if(u){w2c(rest,u+11);snprintf(out,2048,"%s/usb/%s",root,rest);}
    else if(c){w2c(rest,c+18);snprintf(out,2048,"%s/car/%s",root,rest);}
    else assert(0);
}
#define MAXH 24
static struct{FILE*f;int kind;char path[2048];}handles[MAXH];
static HANDLE alloc(FILE*f,int kind,const char*path){int i;for(i=0;i<MAXH;i++)if(!handles[i].kind){handles[i].f=f;handles[i].kind=kind;snprintf(handles[i].path,2048,"%s",path);opened++;return (HANDLE)(intptr_t)(0x1000+i);}assert(0);return INVALID_HANDLE_VALUE;}
static int idx(HANDLE h){int i=(int)((intptr_t)h-0x1000);assert(i>=0&&i<MAXH&&handles[i].kind);return i;}
static int car_exe(HANDLE h){return strstr(handles[idx(h)].path,"/car/")&&strstr(handles[idx(h)].path,"S2AMLOAD.EXE");}
static int usb_scratch(HANDLE h){return strstr(handles[idx(h)].path,"/usb/")&&strstr(handles[idx(h)].path,"LOAD.TMP");}
static int receipt(HANDLE h){return strstr(handles[idx(h)].path,"STARTED.TXT")!=NULL;}
static int car_scratch(HANDLE h){return strstr(handles[idx(h)].path,"/car/")&&strstr(handles[idx(h)].path,"LOAD.TMP");}
DWORD GetTickCount(void){return tick;} DWORD GetLastError(void){return err;} void SetLastError(DWORD e){err=e;}
DWORD GetCurrentProcessId(void){return 42;} DWORD GetCurrentThreadId(void){return 7;}
void Sleep(DWORD n){DWORD before=tick;assert(n==250);sleeps++;tick+=n;if(tick<before)wrap_count++;if(is("budget"))tick+=400000;}
DWORD GetModuleFileNameW(HINSTANCE h,LPWSTR p,DWORD n){const WCHAR*s=L"\\USB Disk\\S2AM-LOAD\\S2AMCTL.EXE";assert(!h&&n==260);if(is("pathfail"))return 0;if(is("pathfull"))return 260;wcscpy(p,s);return (DWORD)wcslen(s);}
DWORD GetFileAttributesW(LPCWSTR p){char f[2048];struct stat st;hostpath(f,p);if(!stat(f,&st))return S_ISDIR(st.st_mode)?16:128;err=2;return 0xffffffffu;}
BOOL CreateDirectoryW(LPCWSTR p,void*s){char f[2048];assert(!s);hostpath(f,p);if(!mkdir(f,0755))return 1;err=(errno==EEXIST)?183:5;return 0;}
static void child_scratch(void){char f[2048],buf[256];int n;FILE*g;
    snprintf(f,2048,"%s/car/_s2am/load/%s/LOAD.TMP",root,RUN_DIR_NAME);
    n=snprintf(buf,256,"S2AM-LOAD,1\r\nmeta,60,5000,512,256,%d,%d\r\nfrequency,start,8000000\r\n",is("wrongpid")?9999:4242,is("wrongtid")?8888:7777);
    g=fopen(f,"wb");assert(g);fwrite(buf,1,n,g);fclose(g);}
BOOL CreateProcessW(LPCWSTR app,LPWSTR cmd,void*pa,void*ta,BOOL inh,DWORD flags,void*env,LPCWSTR dir,STARTUPINFOW*si,PROCESS_INFORMATION*pi){
    assert(wcsstr(app,L"\\SyncExtendedPack\\")&&wcsstr(app,L"S2AMLOAD.EXE"));
    assert(!cmd&&!pa&&!ta&&!inh&&!flags&&!env&&!dir&&!si);
    pi->dwProcessId=4242;pi->dwThreadId=7777;pi->hProcess=alloc(NULL,2,"");pi->hThread=alloc(NULL,3,"");process_created++;
    if(!is("neverready")&&!is("delayed")&&!is("budget")&&!is("childexit")&&!is("waiterror")&&!is("tickwrap"))child_scratch();
    return 1;
}
DWORD WaitForSingleObject(HANDLE h,DWORD ms){assert(handles[idx(h)].kind==2&&ms==0);wait_calls++;
    if(is("childexit"))return 0;if(is("waiterror"))return 0xffffffffu;if(is("readythenexit")&&wait_calls>=2)return 0;return 258;}
HANDLE CreateFileW(LPCWSTR p,DWORD a,DWORD sh,void*s,DWORD d,DWORD attr,HANDLE t){
    char f[2048];FILE*g;assert(!s&&!t&&attr==128);hostpath(f,p);
    if(a==0x40000000u){assert(sh==1&&d==1);g=fopen(f,"wx");if(!g){err=80;return INVALID_HANDLE_VALUE;}return alloc(g,1,f);}
    assert(a==0x80000000u&&d==3&&(sh==1||sh==3));
    if(wcsstr(p,L"LOAD.TMP")&&wcsstr(p,L"\\SyncExtendedPack\\")&&(is("delayed")||is("budget")||is("tickwrap"))&&sleeps>=3){struct stat st;if(stat(f,&st))child_scratch();}
    g=fopen(f,"rb");if(!g){err=2;return INVALID_HANDLE_VALUE;}return alloc(g,1,f);
}
BOOL ReadFile(HANDLE h,void*b,DWORD n,DWORD*got,void*o){FILE*f=handles[idx(h)].f;DWORD r=n;long offset=ftell(f);assert(f&&!o);
    if(is("readfail")||(is("readbackfail")&&car_exe(h))||(is("usbreadbackfail")&&usb_scratch(h))){err=5;return 0;}
    if(is("shortread")&&n>3&&!car_scratch(h))r=3;
    *got=(DWORD)fread(b,1,r,f);
    if(*got&&is("readbackcorrupt")&&car_exe(h)&&offset==0)((BYTE*)b)[0]^=1;
    if(*got&&is("usbreadbackcorrupt")&&usb_scratch(h)&&offset<=13&&offset+(long)*got>13)((BYTE*)b)[13-offset]^=1;
    return 1;}
BOOL WriteFile(HANDLE h,const void*b,DWORD n,DWORD*got,void*o){FILE*f=handles[idx(h)].f;assert(f&&!o);
    if(is("writefail")||(is("copyfail")&&car_exe(h))||(is("receiptfail")&&receipt(h))){*got=0;err=112;return 0;}
    if(is("zerowrite")){*got=0;return 1;}
    if(is("shortio")&&n>3)n=3;
    *got=(DWORD)fwrite(b,1,n,f);return *got==n;}
BOOL FlushFileBuffers(HANDLE h){FILE*f=handles[idx(h)].f;assert(f);
    if(is("flushfail")||(is("copyflushfail")&&car_exe(h))||(is("receiptflushfail")&&receipt(h))){err=1117;return 0;}
    return fflush(f)==0;}
DWORD GetFileSize(HANDLE h,DWORD*high){FILE*f=handles[idx(h)].f;long cur,end;assert(f&&high);*high=0;cur=ftell(f);fseek(f,0,SEEK_END);end=ftell(f);fseek(f,cur,SEEK_SET);return (DWORD)end;}
DWORD SetFilePointer(HANDLE h,LONG dist,LONG*high,DWORD method){FILE*f=handles[idx(h)].f;assert(f&&!high&&method==0&&dist==0);return fseek(f,0,SEEK_SET)==0?0:1;}
BOOL CloseHandle(HANDLE h){int i=idx(h);int fail=0;
    if(handles[i].kind==1){int r;
        if(is("closefail")||(is("copyclosefail")&&car_exe(h))||(is("receiptclosefail")&&receipt(h)))fail=1;
        r=fclose(handles[i].f);handles[i].kind=0;closed++;return !r&&!fail;}
    handles[i].kind=0;closed++;return 1;}
BOOL MoveFileW(LPCWSTR from,LPCWSTR to){char a[2048],b[2048];struct stat st;hostpath(a,from);hostpath(b,to);assert(wcsstr(from,L"LOAD.TMP")&&wcsstr(to,L"LOAD.CSV"));
    if(is("racedest")){FILE*g=fopen(b,"wb");assert(g);fputs("external",g);fclose(g);}
    if(is("movefail")||!stat(b,&st)){err=80;return 0;}return rename(a,b)==0;}
int MessageBoxW(HANDLE h,LPCWSTR text,LPCWSTR title,UINT flags){(void)h;(void)text;(void)title;(void)flags;return 1;}
int WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
int main(int argc,char**argv){int result,i;char pc[2048];FILE*m;assert(argc==3);root=argv[1];mode=argv[2];if(is("tickwrap"))tick=0xffffff00u;
    result=WinMain(NULL,NULL,is("args")?L"unexpected":L"",0);
    for(i=0;i<MAXH;i++)assert(!handles[i].kind);assert(opened==closed);
    snprintf(pc,2048,"%s/proc_count",root);m=fopen(pc,"w");assert(m);fprintf(m,"%d",process_created);fclose(m);
    snprintf(pc,2048,"%s/wrap_count",root);m=fopen(pc,"w");assert(m);fprintf(m,"%u",wrap_count);fclose(m);
    return result;}
'''


class Lifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CONTROLLER.exists():
            raise AssertionError(f"controller source missing: {CONTROLLER}")
        cls.work = Path(tempfile.mkdtemp(prefix="s2am-loadctl-host-"))
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "shim.c").write_text(SHIM)
        cls.program = cls.work / "controller"
        cmd = [shutil.which("clang") or "cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=address,undefined", "-DS2AM_LOAD_HOST_TEST",
               f'-DLOAD_EXPECTED_SHA256="{PAYLOAD_SHA}"', f"-DLOAD_EXPECTED_SIZE={PAYLOAD_SIZE}",
               "-I", str(cls.work), "-I", str(NATIVE_ROOT / "s2am/native"),
               str(CONTROLLER), str(cls.work / "shim.c"), "-o", str(cls.program)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode:
            raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def make_fixture(self, preset="start", usb_existing=None, claim=None, payload=None, journal=None):
        root = Path(tempfile.mkdtemp(prefix="s2am-loadctl-fixture-"))
        self.addCleanup(shutil.rmtree, root)
        usb = root / "usb"
        usb.mkdir()
        (usb / "S2AMLOAD.EXE").write_bytes(PAYLOAD if payload is None else payload)
        car = root / "car"
        car.mkdir()
        run = car / "_s2am" / "load" / RUN_DIR_NAME
        if preset == "collect":
            run.mkdir(parents=True)
            (run / "START.CLAIM").write_bytes(CLAIM if claim is None else claim)
            (run / "S2AMLOAD.EXE").write_bytes(PAYLOAD if payload is None else payload)
            (run / "LOAD.CSV").write_bytes(JOURNAL if journal is None else journal)
        elif preset == "emptyrun":
            run.mkdir(parents=True)
        if usb_existing:
            (usb / usb_existing).write_bytes(b"untouched")
        return root

    def execute(self, root, mode="ok"):
        p = subprocess.run([str(self.program), str(root), mode], capture_output=True, text=True,
                           env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        self.assertNotIn("Sanitizer", p.stderr, p.stderr)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return p

    def run_case(self, mode="ok", preset="start", **kw):
        root = self.make_fixture(preset, **kw)
        return self.execute(root, mode), root

    def run_dir(self, root):
        return root / "car" / "_s2am" / "load" / RUN_DIR_NAME

    def proc_count(self, root):
        return int((root / "proc_count").read_text())

    def test_first_start_claims_copies_and_receipts_without_usb_result(self):
        p, root = self.run_case("ok", "start")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.proc_count(root), 1)
        run = self.run_dir(root)
        self.assertEqual((run / "START.CLAIM").read_bytes(), CLAIM)
        self.assertEqual((run / "S2AMLOAD.EXE").read_bytes(), PAYLOAD)
        self.assertTrue((run / "LOAD.TMP").exists())
        receipt = (root / "usb" / "STARTED.TXT").read_bytes()
        self.assertTrue(receipt.startswith(b"S2AM-LOAD-STARTED,1\r\npid,4242\r\ntid,7777\r\n"))
        self.assertIn(PAYLOAD_SHA.encode(), receipt)
        self.assertFalse((root / "usb" / "LOAD.CSV").exists())

    def test_later_collect_verifies_and_publishes_without_relaunch(self):
        p, root = self.run_case("ok", "collect")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.proc_count(root), 0)
        self.assertEqual((root / "usb" / "LOAD.CSV").read_bytes(), JOURNAL)
        self.assertFalse((root / "usb" / "LOAD.TMP").exists())
        self.assertTrue((self.run_dir(root) / "LOAD.CSV").exists())  # internal not deleted

    def test_repeated_after_start_collects_without_relaunch(self):
        root = self.make_fixture("start")
        first = self.execute(root, "ok")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.proc_count(root), 1)
        # simulate the internal child finishing its recording before collection
        (self.run_dir(root) / "LOAD.CSV").write_bytes(JOURNAL)
        second = self.execute(root, "ok")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.proc_count(root), 0)  # no second process on the same fixture
        self.assertEqual((root / "usb" / "LOAD.CSV").read_bytes(), JOURNAL)

    def test_repeated_after_failed_copy_does_not_relaunch(self):
        root = self.make_fixture("start")
        first = self.execute(root, "copyfail")
        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertTrue(self.run_dir(root).exists())  # claim/run left in place
        second = self.execute(root, "ok")
        self.assertEqual(second.returncode, 1, second.stderr)  # not ready, no takeover
        self.assertEqual(self.proc_count(root), 0)
        self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_repeated_after_neverready_does_not_relaunch(self):
        root = self.make_fixture("start")
        first = self.execute(root, "neverready")
        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertEqual(self.proc_count(root), 1)  # first start did launch a child
        second = self.execute(root, "ok")
        self.assertEqual(second.returncode, 1, second.stderr)
        self.assertEqual(self.proc_count(root), 0)  # collect path never relaunches
        self.assertEqual((self.run_dir(root) / "START.CLAIM").read_bytes(), CLAIM)

    def test_wrong_payload_hash_refuses_start(self):
        p, root = self.run_case("ok", "start", payload=b"wrong-payload")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_wrong_claim_refuses_collect_without_relaunch(self):
        p, root = self.run_case("ok", "collect", claim=b"S2AM-LOAD-START,1\r\nbad\r\n")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(self.proc_count(root), 0)
        self.assertFalse((root / "usb" / "LOAD.CSV").exists())

    def test_empty_run_directory_is_refusal_without_relaunch(self):
        p, root = self.run_case("ok", "emptyrun")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(self.proc_count(root), 0)
        self.assertFalse((root / "usb" / "LOAD.CSV").exists())

    def test_existing_usb_outputs_refuse_before_action(self):
        for preset in ("start", "collect"):
            for name in ("LOAD.CSV", "LOAD.TMP"):
                with self.subTest(preset=preset, name=name):
                    p, root = self.run_case("ok", preset, usb_existing=name)
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertEqual((root / "usb" / name).read_bytes(), b"untouched")
                    self.assertEqual(self.proc_count(root), 0)

    def test_stale_started_receipt_refuses_new_run_before_claim(self):
        p, root = self.run_case("ok", "start", usb_existing="STARTED.TXT")
        self.assertEqual(p.returncode, 1, p.stderr)
        # guard refuses before any car folder creation when the run dir is absent
        self.assertFalse(self.run_dir(root).exists())
        self.assertFalse((root / "car" / "_s2am").exists())
        self.assertFalse((self.run_dir(root) / "START.CLAIM").exists())
        self.assertEqual((root / "usb" / "STARTED.TXT").read_bytes(), b"untouched")
        self.assertEqual(self.proc_count(root), 0)

    def test_earliest_io_failures_leave_claim_and_run_directory(self):
        for mode in ("writefail", "zerowrite", "flushfail", "closefail", "readfail"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "start")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertTrue(self.run_dir(root).exists())  # never removed on failure
                self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_internal_copy_and_readback_fail_before_receipt(self):
        for mode in ("copyfail", "copyflushfail", "copyclosefail", "readbackfail"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "start")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertEqual(self.proc_count(root), 0)  # failed before CreateProcessW
                self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_receipt_errors_fail_start_after_readiness(self):
        for mode in ("receiptfail", "receiptflushfail", "receiptclosefail"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "start")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertEqual(self.proc_count(root), 1)  # readiness reached, receipt failed

    def test_collect_io_rename_and_usb_readback_failures_never_publish(self):
        for mode in ("readfail", "writefail", "flushfail", "closefail", "movefail", "usbreadbackfail"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "collect")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertFalse((root / "usb" / "LOAD.CSV").exists())

    def test_destination_race_never_replaces_new_file(self):
        p, root = self.run_case("racedest", "collect")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual((root / "usb" / "LOAD.CSV").read_bytes(), b"external")
        self.assertTrue((root / "usb" / "LOAD.TMP").exists())  # partial copy remains scratch

    def test_never_ready_does_not_clear_claim_or_terminate(self):
        p, root = self.run_case("neverready", "start")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual((self.run_dir(root) / "START.CLAIM").read_bytes(), CLAIM)
        self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_wrong_child_pid_tid_is_not_ready(self):
        p, root = self.run_case("wrongpid", "start")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_child_exit_and_wait_error_are_uncertain(self):
        for mode in ("childexit", "waiterror", "readythenexit"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "start")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_delayed_readiness_still_confirms(self):
        p, root = self.run_case("delayed", "start")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((root / "usb" / "STARTED.TXT").exists())

    def test_positive_short_streams_are_accumulated(self):
        for mode in ("shortio", "shortread"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "start")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual((self.run_dir(root) / "S2AMLOAD.EXE").read_bytes(), PAYLOAD)
                self.assertTrue((root / "usb" / "STARTED.TXT").exists())
                pc, rc = self.run_case(mode, "collect")
                self.assertEqual(pc.returncode, 0, pc.stderr)
                self.assertEqual((rc / "usb" / "LOAD.CSV").read_bytes(), JOURNAL)

    def test_budget_expiry_refuses(self):
        p, root = self.run_case("budget", "start")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertFalse((root / "usb" / "STARTED.TXT").exists())

    def test_tick_wrap_is_admitted(self):
        p, root = self.run_case("tickwrap", "start")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((root / "usb" / "STARTED.TXT").exists())
        self.assertGreater(int((root/"wrap_count").read_text()),0)

    def test_arguments_and_bad_module_path_refuse(self):
        for mode in ("args", "pathfail", "pathfull"):
            with self.subTest(mode=mode):
                p, root = self.run_case(mode, "start")
                self.assertEqual(p.returncode, 1, p.stderr)

    def test_same_length_payload_corruption_reaches_hash_guard(self):
        corrupted=bytes([PAYLOAD[0]^1])+PAYLOAD[1:]
        self.assertEqual(len(corrupted),len(PAYLOAD))
        p,root=self.run_case("ok","start",payload=corrupted)
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertEqual(self.proc_count(root),0)
        self.assertFalse((root/"usb"/"STARTED.TXT").exists())

    def test_same_length_claim_corruption_reaches_content_guard(self):
        wrong_hash=(("0" if PAYLOAD_SHA[0]!="0" else "1")+PAYLOAD_SHA[1:]).encode()
        corrupted=CLAIM.replace(PAYLOAD_SHA.encode(),wrong_hash)
        self.assertEqual(len(corrupted),len(CLAIM))
        p,root=self.run_case("ok","collect",claim=corrupted)
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertEqual(self.proc_count(root),0)
        self.assertFalse((root/"usb"/"LOAD.CSV").exists())
        self.assertEqual((self.run_dir(root)/"START.CLAIM").read_bytes(),corrupted)

    def test_same_size_successful_readback_corruption_is_rejected(self):
        for mode,preset in (("readbackcorrupt","start"),("usbreadbackcorrupt","collect")):
            with self.subTest(mode=mode):
                p,root=self.run_case(mode,preset)
                self.assertEqual(p.returncode,1,p.stderr)
                self.assertEqual(self.proc_count(root),0)
                self.assertFalse((root/"usb"/"STARTED.TXT").exists())
                self.assertFalse((root/"usb"/"LOAD.CSV").exists())

    def test_correct_pid_but_wrong_tid_is_not_ready(self):
        p,root=self.run_case("wrongtid","start")
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertEqual(self.proc_count(root),1)
        self.assertFalse((root/"usb"/"STARTED.TXT").exists())


if __name__ == "__main__":
    unittest.main()