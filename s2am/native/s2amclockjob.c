/* One-shot read-only clock diagnostic POST_APP. The child owns activation.
 * A timeout never kills/retries/deactivates it; preserve the local entry and
 * controller journal. No MortScript, decoder, frequency or voltage changes. */
#ifndef _WIN32_WCE
#define _WIN32_WCE 0x0600
#endif
#include <windows.h>
#include <string.h>
#include <wchar.h>

#define REPORT_LIMIT 32768UL
#define BUDGET_MS 60000UL
static const WCHAR root[]=L"\\SyncExtendedPack\\_s2am\\jobs\\";
static const WCHAR *const mounts[]={L"\\USB Disk",L"\\USB Disk2",L"\\USB Disk 2",L"\\USB Disk1",L"\\USB Disk3"};
static WCHAR own[MAX_PATH], own_id[29], usb[MAX_PATH], out[MAX_PATH];
static HANDLE report=INVALID_HANDLE_VALUE;
static DWORD started;
static int failed;

static int expired(void) { return (DWORD)(GetTickCount()-started)>=BUDGET_MS; }
static int path(WCHAR *to,LPCWSTR base,LPCWSTR tail)
{
    if (wcslen(base)+wcslen(tail)>=MAX_PATH) return 0;
    if (to!=base) wcscpy(to,base);
    wcscat(to,tail); return 1;
}
static int own_folder(void)
{
    WCHAR expected[MAX_PATH];
    DWORD n=GetModuleFileNameW(NULL,own,MAX_PATH);
    size_t i, prefix=wcslen(root);
    if (!n || n>=MAX_PATH || own[n] || wcsncmp(own,root,prefix)) return 0;
    if (wcslen(own+prefix)!=28+wcslen(L"\\s2amclockjob.exe")) return 0;
    memcpy(own_id,own+prefix,28*sizeof(WCHAR)); own_id[28]=0;
    if (own_id[8]!=L'-' || own_id[15]!=L'-' || wcsncmp(own_id+16,L"clkdiag-",8)) return 0;
    for (i=0; i<15; ++i) if (i!=8 && (own_id[i]<L'0' || own_id[i]>L'9')) return 0;
    for (i=24; i<28; ++i)
        if (!((own_id[i]>=L'0' && own_id[i]<=L'9') || (own_id[i]>=L'a' && own_id[i]<=L'f'))) return 0;
    if (!path(expected,root,own_id) || !path(expected,expected,L"\\s2amclockjob.exe") || wcscmp(own,expected)) return 0;
    return path(own,root,own_id);
}
static int write_all(HANDLE file,const void *data,DWORD size)
{
    const BYTE *p=data;
    while (size) {
        DWORD done=0;
        if (expired() || !WriteFile(file,p,size,&done,NULL) || !done || done>size) return 0;
        p+=done; size-=done;
    }
    return 1;
}
static void put(const char *s) { if (!failed && !write_all(report,s,(DWORD)strlen(s))) failed=1; }
static void number(DWORD n)
{
    char digits[11]; unsigned int i=10; digits[i]=0;
    do { digits[--i]=(char)('0'+n%10); n/=10; } while (n && i);
    put(digits+i);
}
static void field(DWORD n) { put("|"); number(n); }
static int line(void)
{
    put("\r\n"); if (!failed && !FlushFileBuffers(report)) failed=1; return !failed;
}
static int mark(LPCWSTR name,LPCWSTR id)
{
    HANDLE file; char ascii[40]; size_t i; int ok;
    for (i=0; id[i] && i<sizeof(ascii); ++i) ascii[i]=(char)id[i];
    if (i==sizeof(ascii)) return 0;
    file=CreateFileW(name,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if (file==INVALID_HANDLE_VALUE) return 0;
    ok=write_all(file,ascii,(DWORD)i) && FlushFileBuffers(file);
    if (!CloseHandle(file)) ok=0;
    return ok;
}
static int directory(LPCWSTR name,int fresh)
{
    WIN32_FILE_ATTRIBUTE_DATA info;
    if (CreateDirectoryW(name,NULL)) return 1;
    return !fresh && GetLastError()==ERROR_ALREADY_EXISTS &&
           GetFileAttributesExW(name,GetFileExInfoStandard,&info) && (info.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY);
}
static int find_usb(void)
{
    WCHAR suffix[80], p[MAX_PATH]; unsigned int i; int count=0;
    wcscpy(suffix,L"\\s2am\\pending\\"); wcscat(suffix,own_id); wcscat(suffix,L".json");
    for (i=0; i<sizeof(mounts)/sizeof(mounts[0]); ++i) {
        WIN32_FILE_ATTRIBUTE_DATA info;
        if (expired() || !path(p,mounts[i],suffix)) return 0;
        if (GetFileAttributesExW(p,GetFileExInfoStandard,&info)) {
            if (info.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY) return 0;
            wcscpy(usb,mounts[i]); ++count;
        } else if (GetLastError()!=ERROR_FILE_NOT_FOUND && GetLastError()!=ERROR_PATH_NOT_FOUND) return 0;
    }
    return count==1;
}
static DWORD crc_update(DWORD crc,const BYTE *data,DWORD size)
{
    DWORD i; unsigned int b;
    for (i=0; i<size; ++i) { crc^=data[i]; for (b=0; b<8; ++b) crc=(crc>>1)^((crc&1)?0xedb88320UL:0); }
    return crc;
}
static void copy_journal(void)
{
    WCHAR source[MAX_PATH], dest[MAX_PATH]; WIN32_FILE_ATTRIBUTE_DATA info;
    HANDLE input=INVALID_HANDLE_VALUE, output=INVALID_HANDLE_VALUE;
    BYTE buffer[4096]; DWORD remaining=0, copied=0, crc=0xffffffffUL;
    const char *status="copy-error";
    (void)path(source,own,L"\\clock-user-driver.txt");
    (void)path(dest,out,L"\\clock-user-driver.txt");
    if (expired()) goto emit;
    if (!GetFileAttributesExW(source,GetFileExInfoStandard,&info)) {
        if (GetLastError()==ERROR_FILE_NOT_FOUND || GetLastError()==ERROR_PATH_NOT_FOUND) status="missing";
        goto emit;
    }
    if ((info.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_ROMMODULE)) ||
        info.nFileSizeHigh || info.nFileSizeLow>REPORT_LIMIT) goto emit;
    remaining=info.nFileSizeLow;
    /* A timed-out child can still append: copy only this bounded observed prefix.
     * The timeout row can never be promoted by a later completion marker. */
    input=CreateFileW(source,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,0,NULL);
    if (input==INVALID_HANDLE_VALUE || expired()) goto cleanup;
    output=CreateFileW(dest,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if (output==INVALID_HANDLE_VALUE) goto cleanup;
    while (remaining) {
        DWORD got=0, want=remaining<sizeof(buffer)?remaining:(DWORD)sizeof(buffer);
        if (expired() || !ReadFile(input,buffer,want,&got,NULL) || !got || got>want || !write_all(output,buffer,got)) goto cleanup;
        crc=crc_update(crc,buffer,got); copied+=got; remaining-=got;
    }
    if (!expired() && FlushFileBuffers(output)) status="copied";
cleanup:
    if (output!=INVALID_HANDLE_VALUE && !CloseHandle(output)) status="copy-error";
    if (input!=INVALID_HANDLE_VALUE && !CloseHandle(input)) status="copy-error";
emit:
    put("J|"); put(status); field(copied); field(!strcmp(status,"copied")?crc^0xffffffffUL:0); line();
}
static void child(void)
{
    WCHAR exe[MAX_PATH], command[29]; PROCESS_INFORMATION pi;
    DWORD error=0, wait=WAIT_FAILED, valid=0, code=0;
    const char *status="launch-error";
    (void)path(exe,own,L"\\s2amclockctl.exe"); wcscpy(command,own_id);
    memset(&pi,0,sizeof(pi)); put("B|launch"); if (!line() || expired()) return;
    SetLastError(0);
    if (!CreateProcessW(exe,command,NULL,NULL,FALSE,0,NULL,NULL,NULL,&pi)) { error=GetLastError(); goto emit; }
    wait=WaitForSingleObject(pi.hProcess,15000UL);
    if (wait==WAIT_OBJECT_0) {
        if (GetExitCodeProcess(pi.hProcess,&code)) { valid=1; status="exited"; }
        else { status="exit-error"; error=GetLastError(); }
    } else if (wait==WAIT_TIMEOUT) status="timeout";
    else { status="wait-error"; error=GetLastError(); }
    if (!CloseHandle(pi.hThread)) { status="handle-error"; error=GetLastError(); }
    if (!CloseHandle(pi.hProcess)) { status="handle-error"; error=GetLastError(); }
emit:
    put("C|"); put(status); field(error); field(wait); field(valid); field(code); line();
}
int WINAPI WinMain(HINSTANCE instance,HINSTANCE previous,LPWSTR command,int show)
{
    WCHAR p[MAX_PATH]; char id[29]; unsigned int i; int ok;
    (void)instance; (void)previous; (void)show;
    started=GetTickCount();
    if ((command && *command) || !own_folder()) return 1;
    (void)path(p,own,L"\\clock-job-entry.txt"); if (!mark(p,own_id)) return 2;
    /* Claim BEFORE CreateProcess: a timed-out child may still be waiting before
     * registry creation. Keep this cross-run barrier on every outcome, including
     * success. A separate reviewed reconciliation must release it; never replay
     * merely because a driver key disappeared or a different job ID was built. */
    if (!mark(L"\\SyncExtendedPack\\_s2am\\clock-inspection-claim.txt",own_id)) return 2;
    if (!find_usb()) return 3;
    if (!path(p,usb,L"\\s2am") || !directory(p,0) ||
        !path(p,usb,L"\\s2am\\reports") || !directory(p,0) ||
        !path(out,p,L"\\") || !path(out,out,own_id) || !directory(out,1)) return 4;
    (void)path(p,out,L"\\clock-job.txt");
    report=CreateFileW(p,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if (report==INVALID_HANDLE_VALUE) return 5;
    for (i=0; i<28; ++i) id[i]=(char)own_id[i];
    id[28]=0;
    put("S|s2am-clock-job-v1|"); put(id);
    if (line()) child();
    if (!failed) copy_journal();
    put("T|complete"); line();
    ok=!failed; if (!CloseHandle(report)) ok=0;
    if (!ok) return 6;
    (void)path(p,out,L"\\done.txt"); return mark(p,own_id)?0:7;
}
