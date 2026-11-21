"""Run the parked Desktop scheduler test under deterministic user-mode CE fakes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.test_load_native import WINDOWS, SHIM

ROOT=Path(__file__).resolve().parents[1]
REG='''
typedef void *HWND; HWND GetForegroundWindow(void); DWORD GetWindowThreadProcessId(HWND,DWORD*);
typedef void *HKEY;
#define HKEY_LOCAL_MACHINE ((HKEY)3)
#define KEY_READ 0x20019
#define REG_DWORD 4
LONG RegOpenKeyExW(HKEY,LPCWSTR,DWORD,DWORD,HKEY*);
LONG RegQueryValueExW(HKEY,LPCWSTR,DWORD*,DWORD*,BYTE*,DWORD*);
LONG RegCloseKey(HKEY);
'''
REG_SHIM=r'''
HWND GetForegroundWindow(void){return (HWND)11;} DWORD GetWindowThreadProcessId(HWND w,DWORD*p){assert(w==(HWND)11);*p=99;return 8;}
LONG RegOpenKeyExW(HKEY k,LPCWSTR p,DWORD zero,DWORD access,HKEY*outkey){
 assert(k==HKEY_LOCAL_MACHINE&&!wcscmp(p,L"Software\\Ford\\Flash")&&!zero&&access==0);
 if(is("denied")) return 5;
 *outkey=(HKEY)10; return 0;
}
LONG RegQueryValueExW(HKEY k,LPCWSTR p,DWORD*z,DWORD*t,BYTE*b,DWORD*s){
 DWORD val=253;assert(k==(HKEY)10&&!z&&*s==4);
 assert(!wcscmp(p,L"ThreadPrio256")||!wcscmp(p,L"FastThreadPrio256"));
 *t=is("badtype")?1:REG_DWORD;*s=4;memcpy(b,&val,4);return 0;
}
LONG RegCloseKey(HKEY k){assert(k==(HKEY)10);return is("regclosefail")?5:0;}
'''
class Deskcheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        d=Path(cls.tmp.name)
        (d/'windows.h').write_text(WINDOWS+REG)
        shim=SHIM.replace('S2AM-LOAD','S2AM-DESK').replace('S2AMLOAD.EXE','DESKTEST.EXE').replace('LOAD.CSV','DESK.CSV').replace('LOAD.TMP','DESK.TMP')
        shim=shim.replace('L"AutoKit.exe"', 'is("absent")?L"Other.exe":L"Desktop.exe"')
        # No thread in an unrelated process may be opened.
        shim=shim.replace('is("threadexact")?512:2','is("threadexact")?512:is("multiple")?3:2')
        shim=shim.replace('is("multiple")?3:2','is("multiple")?3:is("rows128")?129:is("rows129")?130:is("walk1024")?1024:is("walk1025")?1025:2')
        shim=shim.replace('t->th32OwnerProcessID=thread_at?99:42','t->th32OwnerProcessID=(is("walk1024")||is("walk1025"))?42:thread_at?99:42')
        shim=shim.replace('assert(access==0x40', 'assert(tid!=7);assert(access==0x40')
        (d/'shim.c').write_text(shim+REG_SHIM);cls.exe=d/'desk'
        subprocess.run(['clang','-std=c99','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-DS2AM_LOAD_HOST_TEST','-I',str(d),'-I',str(ROOT/'s2am/native'),str(ROOT/'s2am/native/deskcheck.c'),str(d/'shim.c'),'-o',str(cls.exe)],check=True)

    def run_case(self,mode,existing=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);d=Path(tmp.name)
        if existing:(d/existing).write_bytes(b'untouched')
        r=subprocess.run([str(self.exe),str(d),mode],capture_output=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        self.assertNotIn(b'Sanitizer',r.stderr)
        self.assertIn(r.returncode,(0,1),r.stderr)
        return r.returncode,d

    def test_report(self):
        code,d=self.run_case('ok');self.assertEqual(code,0)
        s=(d/'DESK.CSV').read_bytes()
        self.assertTrue(s.startswith(b'S2AM-DESK,1\r\n'))
        self.assertIn(b'config,ThreadPrio256,ok,253,0',s)
        self.assertEqual(s.count(b'\r\nthread,'),7)
        self.assertNotIn(b'AutoKit',s)
        self.assertTrue(s.endswith(b'complete,7\r\n'))

    def test_unknown_config(self):
        for mode in ('denied','badtype'):
            code,d=self.run_case(mode);self.assertEqual(code,0)
            self.assertIn(b'config,FastThreadPrio256,unknown,', (d/'DESK.CSV').read_bytes())

    def test_absent(self):
        code,d=self.run_case('absent');self.assertEqual(code,0)
        self.assertNotIn(b'\r\nthread,',(d/'DESK.CSV').read_bytes())
        self.assertIn(b',absent,',(d/'DESK.CSV').read_bytes())

    def test_no_overwrite(self):
        for name in ['DESK.CSV','DESK.TMP']:
            code,d=self.run_case('ok',name);self.assertEqual(code,1)
            self.assertEqual((d/name).read_bytes(),b'untouched')

    def test_fail_closed(self):
        for mode in ('args','pathfail','flushfail','movefail','fileclosefail','snapshotclosefail','budget','freefail','threadclosefail','regclosefail','missingexport','writefail','zerowrite'):
            with self.subTest(mode=mode):
                code,d=self.run_case(mode);self.assertEqual(code,1)
                self.assertFalse((d/'DESK.CSV').exists())

    def test_multiple_threads(self):
        code,d=self.run_case('multiple');self.assertEqual(code,0)
        self.assertEqual((d/'DESK.CSV').read_bytes().count(b'\r\nthread,'),14)

    def test_partial_evidence(self):
        for mode,status in [('snapshotfail',b'snap_error'),('partial',b'thread_error')]:
            code,d=self.run_case(mode);self.assertEqual(code,0)
            self.assertIn(b','+status+b',',(d/'DESK.CSV').read_bytes())

    def test_foreground_and_missing_thread_times(self):
        code,d=self.run_case('readfail');self.assertEqual(code,0)
        s=(d/'DESK.CSV').read_text()
        self.assertIn(',desktop,1',s)
        self.assertTrue(all(line.split(',')[7:]==['','','','5'] for line in s.splitlines() if line.startswith('thread,')))

    def test_limits(self):
        for mode,status,num in [('rows128','ok',128),('rows129','row_limit',128),('walk1024','ok',0),
                                ('walk1025','thread_limit',0),('processexact','ambiguous',0),('processcap','process_limit',0)]:
            with self.subTest(mode=mode):
                code,d=self.run_case(mode);self.assertEqual(code,0)
                lines=(d/'DESK.CSV').read_text().splitlines()
                self.assertEqual(len([x for x in lines if x.startswith('thread,')]),7*num)
                self.assertTrue(all(x.split(',')[4]==status for x in lines if x.startswith('round,')))

    def test_short_writes_and_race(self):
        code,d=self.run_case('shortwrite');self.assertEqual(code,0)
        self.assertTrue((d/'DESK.CSV').read_bytes().endswith(b'complete,7\r\n'))
        code,d=self.run_case('racedest');self.assertEqual(code,1)
        self.assertEqual((d/'DESK.CSV').read_bytes(),b'external')

    def test_priority_and_full_width_raw_times(self):
        code,d=self.run_case('wide');self.assertEqual(code,0)
        lines=[r.split(',') for r in (d/'DESK.CSV').read_text().splitlines() if r.startswith('thread,')]
        self.assertEqual(len(lines),7)
        for seq,r in enumerate(lines):
            self.assertEqual(len(r),11)
            time=(1<<63)+(1<<32)+seq*5000*1000
            self.assertEqual([int(n) for n in r[1:]], [seq,99,8,-(1<<31),(1<<31)-1,seq*5000,108,time,time//2,0])
