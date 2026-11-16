"""Exercise the real native clock launcher and its job/import boundary without hardware."""
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from s2am import cli, clock_driver, clock_snapshot, stick
from s2am.job import Job, meta, stage
from s2am.state import Store
from test_decdiag_native import WINDOWS

ROOT = Path(__file__).resolve().parents[1]
OWN = "20261116-210000-clkdiag-ab12"
JOB = f"SyncExtendedPack/_s2am/jobs/{OWN}"
REPORT = f"USB Disk/s2am/reports/{OWN}"
SERIAL = "XV31M13H"


def job():
    payload = {name: name.encode() for name in clock_driver.BINARIES}
    params = {"artifacts": {name: hashlib.sha256(body).hexdigest() for name, body in payload.items()},
              "sources": {name: "1" * 64 for name in clock_driver.SOURCES}}
    return Job(SERIAL, "clkdiag", id=OWN, params=params), payload


SHIM = r'''
#include "windows.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <sys/stat.h>
#include <errno.h>
#define OWN "20261116-210000-clkdiag-ab12"
#define JOB "/SyncExtendedPack/_s2am/jobs/" OWN
#define REPORT "/USB Disk/s2am/reports/" OWN
typedef struct { FILE *file; char path[512]; int write; } File;
static const char *root,*mode; static DWORD error,tick;
static int ismode(const char *s) { return !strcmp(mode,s); }
static void narrow(const WCHAR *w,char *s) {
    unsigned i; for(i=0;w[i];++i) { assert(i<511); s[i]=w[i]=='\\'?'/':(char)w[i]; } s[i]=0;
}
static void host(const char *p,char *out) { assert(p[0]=='/'); snprintf(out,1024,"%s%s",root,p); }
DWORD GetLastError(void) { return error; }
void SetLastError(DWORD e) { error=e; }
DWORD GetTickCount(void) { return tick; }
DWORD GetModuleFileNameW(HINSTANCE module,LPWSTR out,DWORD count) {
    const char *p=ismode("wrong-path")?"/elsewhere/s2amclockjob.exe":JOB "/s2amclockjob.exe";
    unsigned i; (void)module; assert(strlen(p)<count);
    for(i=0;p[i];++i) out[i]=p[i]=='/'?'\\':p[i]; out[i]=0; return i;
}
BOOL GetFileAttributesExW(LPCWSTR path,GET_FILEEX_INFO_LEVELS level,void *out) {
    char p[512],full[1024]; struct stat st; WIN32_FILE_ATTRIBUTE_DATA *info=out;
    assert(level==GetFileExInfoStandard); narrow(path,p); host(p,full);
    if(ismode("mount-error") && !strncmp(p,"/USB Disk2/",11)) { error=5; return 0; }
    if(stat(full,&st)) { error=2; return 0; }
    memset(info,0,sizeof(*info)); info->dwFileAttributes=S_ISDIR(st.st_mode)?16:128;
    info->nFileSizeLow=(DWORD)st.st_size;
    if(ismode("journal-oversize") && strstr(p,"clock-user-driver.txt")) info->nFileSizeLow=32769;
    return 1;
}
BOOL CreateDirectoryW(LPCWSTR path,void *security) {
    char p[512],full[1024]; assert(!security); narrow(path,p); host(p,full);
    assert(!strncmp(p,"/USB Disk/s2am",14));
    if(!mkdir(full,0700)) return 1; error=errno==EEXIST?183:5; return 0;
}
HANDLE CreateFileW(LPCWSTR path,DWORD access,DWORD share,void *sec,DWORD disposition,DWORD flags,HANDLE tmpl) {
    char p[512],full[1024]; struct stat st; File *f; FILE *stream;
    assert(!sec && !tmpl); (void)flags; narrow(path,p); host(p,full);
    if(access==GENERIC_READ) {
        assert(!strcmp(p,JOB "/clock-user-driver.txt") && share==3 && disposition==OPEN_EXISTING);
        stream=fopen(full,"rb");
    } else {
        assert(access==GENERIC_WRITE && share==FILE_SHARE_READ && disposition==CREATE_NEW);
        assert(!strcmp(p,JOB "/clock-job-entry.txt") ||
               !strcmp(p,"/SyncExtendedPack/_s2am/clock-inspection-claim.txt") ||
               !strncmp(p,REPORT "/",strlen(REPORT)+1));
        if(!stat(full,&st)) { error=80; return INVALID_HANDLE_VALUE; }
        stream=fopen(full,"wb");
    }
    if(!stream) { error=5; return INVALID_HANDLE_VALUE; }
    f=calloc(1,sizeof(*f)); f->file=stream; f->write=access==GENERIC_WRITE; strcpy(f->path,p); return f;
}
BOOL ReadFile(HANDLE handle,void *out,DWORD count,DWORD *done,void *overlap) {
    File *f=handle; assert(!f->write && !overlap);
    if(ismode("read-fail")) return 0;
    if(ismode("short-io") && count>17) count=17;
    *done=(DWORD)fread(out,1,count,f->file); return 1;
}
BOOL WriteFile(HANDLE handle,const void *data,DWORD count,DWORD *done,void *overlap) {
    File *f=handle; assert(f->write && !overlap);
    if(ismode("report-write-fail") && strstr(f->path,"clock-job.txt")) { *done=0; return 0; }
    if(ismode("zero-write") && strstr(f->path,"clock-user-driver.txt")) { *done=0; return 1; }
    if(ismode("short-io") && count>17) count=17;
    *done=(DWORD)fwrite(data,1,count,f->file); return *done==count;
}
BOOL FlushFileBuffers(HANDLE handle) {
    File *f=handle;
    if(ismode("entry-flush-fail") && strstr(f->path,"clock-job-entry.txt")) return 0;
    if(ismode("report-flush-fail") && strstr(f->path,"clock-job.txt")) return 0;
    return !fflush(f->file);
}
BOOL CloseHandle(HANDLE handle) {
    File *f; int fail;
    if(handle==(HANDLE)1 || handle==(HANDLE)2) return !ismode("handle-close-fail");
    f=handle; fail=ismode("report-close-fail") && strstr(f->path,"clock-job.txt");
    fclose(f->file); free(f); return !fail;
}
BOOL CreateProcessW(LPCWSTR path,LPWSTR command,void *a,void *b,BOOL inherit,DWORD flags,
                    void *env,void *cwd,void *startup,PROCESS_INFORMATION *pi) {
    char p[512],cmd[512],source[1024],dest[1024]; FILE *input,*output; int c;
    assert(!a && !b && !inherit && !flags && !env && !cwd && !startup);
    narrow(path,p); narrow(command,cmd); assert(!strcmp(p,JOB "/s2amclockctl.exe") && !strcmp(cmd,OWN));
    puts("launched");
    if(ismode("launch-error")) { error=2; return 0; }
    if(!ismode("journal-missing")) {
        host("/fixture.txt",source); host(JOB "/clock-user-driver.txt",dest);
        input=fopen(source,"rb"); output=fopen(dest,"wb"); assert(input && output);
        while((c=fgetc(input))!=EOF) fputc(c,output); fclose(input); fclose(output);
    }
    pi->hProcess=(HANDLE)1; pi->hThread=(HANDLE)2; return 1;
}
DWORD WaitForSingleObject(HANDLE process,DWORD limit) {
    assert(process==(HANDLE)1 && limit==15000);
    if(ismode("timeout")) { tick=15000; return WAIT_TIMEOUT; }
    if(ismode("wait-fail")) { error=6; return WAIT_FAILED; }
    return WAIT_OBJECT_0;
}
BOOL GetExitCodeProcess(HANDLE process,DWORD *code) {
    assert(process==(HANDLE)1);
    if(ismode("exit-fail")) { error=6; return 0; }
    *code=ismode("child-fail")?4:0; return 1;
}
int WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
int main(int argc,char **argv) { assert(argc==3); root=argv[1]; mode=argv[2]; return WinMain(NULL,NULL,L"",0); }
'''


@unittest.skipUnless(shutil.which("cc"), "needs a host C compiler")
class Launcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = Path(tempfile.mkdtemp())
        (cls.build / "windows.h").write_text(WINDOWS + "\ntypedef unsigned char BYTE;\n#define FILE_SHARE_WRITE 2\n")
        (cls.build / "shim.c").write_text(SHIM)
        cls.exe = cls.build / "clock-job"
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
                        "-I", str(cls.build), str(ROOT / "s2am/native/s2amclockjob.c"),
                        str(cls.build / "shim.c"), "-o", str(cls.exe)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.build)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / JOB).mkdir(parents=True)
        self.pending = self.root / f"USB Disk/s2am/pending/{OWN}.json"
        self.pending.parent.mkdir(parents=True)
        self.pending.write_text("{}")
        rows = ["S|s2am-clock-v1", *(f"R|{p}|{b}|{o}|0" for p, b, o in clock_snapshot.EXPECTED), "T|complete"]
        (self.root / "fixture.txt").write_text("\n".join(rows) + "\n")
        self.job, _ = job()

    def run_mode(self, mode):
        result = subprocess.run([str(self.exe), str(self.root), mode], capture_output=True, text=True, timeout=5)
        return result, clock_driver.analyze(self.root / REPORT, self.job)

    def test_real_launcher_output_is_accepted_by_importer(self):
        result, parsed = self.run_mode("ok")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(parsed["complete"])
        self.assertTrue(parsed["snapshot"]["complete"])
        self.assertTrue((self.root / JOB / "clock-job-entry.txt").exists())
        self.assertEqual((self.root / "SyncExtendedPack/_s2am/clock-inspection-claim.txt").read_text(), OWN)

    def test_corrupt_or_rebound_return_is_not_a_verified_snapshot(self):
        self.run_mode("ok")
        report = self.root / REPORT
        journal = report / "clock-user-driver.txt"
        body = journal.read_bytes()
        journal.write_bytes(body.replace(b"pll1", b"pll2", 1))
        self.assertFalse(clock_driver.analyze(report, self.job)["complete"])
        journal.write_bytes(body)
        envelope = report / "clock-job.txt"
        original = envelope.read_text()
        envelope.write_text(original.replace(OWN, OWN[:-4] + "ffff"))
        self.assertFalse(clock_driver.analyze(report, self.job)["complete"])
        envelope.write_text(original)
        journal.unlink()
        journal.symlink_to(self.root / "fixture.txt")
        self.assertFalse(clock_driver.analyze(report, self.job)["complete"])

    def test_failed_or_pending_child_is_not_promoted_by_complete_snapshot(self):
        for mode in ("timeout", "child-fail", "wait-fail", "exit-fail", "handle-close-fail", "launch-error"):
            with self.subTest(mode=mode):
                self.setUp()
                result, parsed = self.run_mode(mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(parsed["complete"])
                self.assertFalse(parsed["snapshot"]["complete"])

    def test_missing_partial_oversize_journal_never_becomes_a_snapshot(self):
        for mode in ("journal-missing", "journal-oversize", "read-fail", "zero-write"):
            with self.subTest(mode=mode):
                self.setUp()
                _, parsed = self.run_mode(mode)
                self.assertTrue(parsed["complete"])
                self.assertFalse(parsed["snapshot"]["complete"])

    def test_short_io_and_same_job_replay(self):
        first, parsed = self.run_mode("short-io")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(parsed["snapshot"]["complete"])
        second, _ = self.run_mode("ok")
        self.assertNotEqual(second.returncode, 0)
        self.assertNotIn("launched", second.stdout)

    def test_another_run_claim_blocks_even_before_the_old_child_creates_registry_state(self):
        claim = self.root / "SyncExtendedPack/_s2am/clock-inspection-claim.txt"
        claim.write_text("20261116-200000-clkdiag-dead")
        result, parsed = self.run_mode("ok")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("launched", result.stdout)
        self.assertFalse(parsed["complete"])
        self.assertEqual(claim.read_text(), "20261116-200000-clkdiag-dead")

    def test_mount_and_initial_storage_failures_prevent_child_launch(self):
        for mode in ("mount-error", "wrong-path", "entry-flush-fail", "report-write-fail", "report-flush-fail"):
            with self.subTest(mode=mode):
                self.setUp()
                result, parsed = self.run_mode(mode)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("launched", result.stdout)
                self.assertFalse(parsed["complete"])

    def test_duplicate_pending_mount_and_close_failure(self):
        second = self.root / f"USB Disk2/s2am/pending/{OWN}.json"
        second.parent.mkdir(parents=True)
        second.write_text("{}")
        result, _ = self.run_mode("ok")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("launched", result.stdout)
        self.setUp()
        result, parsed = self.run_mode("report-close-fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(parsed["complete"])


class Boundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job, self.payload = job()

    def test_clock_cli_only_stages_even_without_no_pack(self):
        work = self.root / "staged"
        with patch("s2am.clock_driver.artifacts", return_value=(self.job.params, self.payload)), \
                patch("s2am.pack.build", side_effect=AssertionError("pack only on server")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["job", "clock-inspect", "--serial", SERIAL,
                                       "--artifacts", str(self.root), "--work", str(work)]), 0)
        self.assertTrue((work / "job.json").is_file())
        self.assertFalse((work / "install.bin").exists())
        self.assertFalse(cli.parser().parse_args(["job", "inventory", "--serial", SERIAL]).no_pack)

    def test_stage_is_native_only_and_all_payload_stays_in_own_job_folder(self):
        stage(self.job, self.root / "no-upstream", self.root / "staged", self.payload)
        folder = self.root / "staged/payload" / self.job.job_dir.lstrip("/")
        self.assertEqual({p.name for p in folder.iterdir()}, {*clock_driver.BINARIES, "job.json"})
        self.assertIn("/s2amclockjob.exe", meta(self.job).decode("utf-16-le"))
        self.assertNotIn("NEED_REBOOT", meta(self.job).decode("utf-16-le"))

    def test_modified_payload_or_extra_destination_refused_before_staging(self):
        for change in ("bytes", "extra", "destination"):
            with self.subTest(change=change):
                payload = dict(self.payload)
                if change == "bytes":
                    payload["s2amclockctl.exe"] += b"changed"
                if change == "extra":
                    payload["extra.exe"] = b"extra"
                with self.assertRaises(ValueError):
                    stage(self.job, self.root, self.root / "never", payload,
                          [(self.root / "source", "/Windows/file")] if change == "destination" else None)
                self.assertFalse((self.root / "never").exists())

    def test_usb_cannot_replace_trusted_artifact_binding_or_disguise_kind(self):
        store = Store(self.root / "store")
        store.save_job(SERIAL, OWN, json.loads(self.job.to_json()))
        for change in ("hash", "kind"):
            usb = self.root / change
            pending = usb / "s2am/pending" / f"{OWN}.json"
            pending.parent.mkdir(parents=True)
            data = json.loads(self.job.to_json())
            if change == "hash":
                data["params"]["artifacts"]["s2amclockctl.exe"] = "9" * 64
            else:
                data["kind"] = "inv"
            pending.write_text(json.dumps(data))
            result = stick.import_reports(usb, store, require_volume=False)
            self.assertEqual(result[0]["status"], "rejected")
            self.assertEqual(store.job(SERIAL, OWN), json.loads(self.job.to_json()))

    def test_source_bound_bundle_loader_never_builds_and_checks_controller_dll_binding(self):
        manifest = {"format": "s2am-clock-artifacts-v1", "sources": {
            name: hashlib.sha256((ROOT / "s2am/native" / name).read_bytes()).hexdigest()
            for name in clock_driver.SOURCES}}
        payload = dict(self.payload)
        payload["s2amclockctl.exe"] += hashlib.sha256(payload["s2amclkdrv.dll"]).hexdigest().encode()
        manifest["binaries"] = {name: hashlib.sha256(body).hexdigest() for name, body in payload.items()}
        for name, body in payload.items():
            (self.root / name).write_bytes(body)
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        with patch("s2am.native.check"), patch("s2am.native.build", side_effect=AssertionError("no local build")):
            params, loaded = clock_driver.artifacts(self.root)
            self.assertEqual(loaded, payload)
            self.assertEqual(params["artifacts"], manifest["binaries"])
            (self.root / "s2amclockctl.exe").write_bytes(b"unbound-controller")
            manifest["binaries"]["s2amclockctl.exe"] = hashlib.sha256(b"unbound-controller").hexdigest()
            (self.root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "not bound"):
                clock_driver.artifacts(self.root)
            manifest["sources"]["s2amclockctl.c"] = "0" * 64
            (self.root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "source differs"):
                clock_driver.artifacts(self.root)


if __name__ == "__main__":
    unittest.main()
