/* Fixed single-port start/collect controller. Never resets claims, overwrites results,
 * changes configuration, selects arbitrary paths/processes, or terminates a process. */
#ifndef _WIN32_WCE
#define _WIN32_WCE 0x0600
#endif
#include <windows.h>
#include <string.h>
#include <wchar.h>
#include "load_sha256.h"
#ifndef LOAD_EXPECTED_SHA256
#error LOAD_EXPECTED_SHA256 must bind the collector artifact
#endif
#ifndef LOAD_EXPECTED_SIZE
#error LOAD_EXPECTED_SIZE must bind the collector artifact
#endif
typedef char load_hash_size[(sizeof(LOAD_EXPECTED_SHA256)==65)?1:-1];
#define RUN_DIR L"\\SyncExtendedPack\\_s2am\\load\\20261120-load-44748284729"
#define RUN_EXE RUN_DIR L"\\S2AMLOAD.EXE"
#define RUN_CLAIM RUN_DIR L"\\START.CLAIM"
#define RUN_RESULT RUN_DIR L"\\LOAD.CSV"
#define RUN_SCRATCH RUN_DIR L"\\LOAD.TMP"
#define MAX_CAPTURE (8u*1024u*1024u)
static DWORD started;
static WCHAR source[MAX_PATH],usb_result[MAX_PATH],usb_scratch[MAX_PATH],usb_receipt[MAX_PATH];
static BYTE chunk[4096];

/* load pure begin */
static char *append_text(char *at,const char *s) { while(*s) *at++=*s++; *at=0; return at; }
static char *append_number(char *at,DWORD n) {
    char digits[11];unsigned i=10;digits[i]=0;
    do { digits[--i]=(char)('0'+n%10); n/=10; } while(n);
    return append_text(at,digits+i);
}
static int header_ready(const BYTE *data,DWORD size,DWORD pid,DWORD tid) {
    char prefix[128],*at=prefix;DWORD i,n,value=0;
    at=append_text(at,"S2AM-LOAD,1\r\nmeta,60,5000,512,256,");
    at=append_number(at,pid);at=append_text(at,",");at=append_number(at,tid);
    at=append_text(at,"\r\nfrequency,start,");n=(DWORD)(at-prefix);
    if(size<=n||memcmp(data,prefix,n)||data[n]<'1'||data[n]>'9') return 0;
    i=n;
    while(i<size&&data[i]>='0'&&data[i]<='9') {
        DWORD digit=(DWORD)(data[i]-'0');
        if(value>(1000000000u-digit)/10u) return 0;
        value=value*10u+digit;i++;
    }
    return value&&i+1<size&&data[i]=='\r'&&data[i+1]=='\n';
}
/* load pure end */

static int admitted(void) { return (DWORD)(GetTickCount()-started)<30000u; }
static void hex_digest(const BYTE bytes[32],char out[65]) {
    static const char hex[]="0123456789abcdef";unsigned i;
    for(i=0;i<32;i++) { out[i*2]=hex[bytes[i]>>4];out[i*2+1]=hex[bytes[i]&15]; }
    out[64]=0;
}
static int missing(LPCWSTR path) {
    DWORD attributes;SetLastError(0);attributes=GetFileAttributesW(path);
    return attributes==INVALID_FILE_ATTRIBUTES&&GetLastError()==2;
}
static int directory(LPCWSTR path) {
    DWORD attributes;
    if(CreateDirectoryW(path,NULL)) return 1;
    attributes=GetFileAttributesW(path);
    return attributes!=INVALID_FILE_ATTRIBUTES&&(attributes&FILE_ATTRIBUTE_DIRECTORY)!=0;
}
static int write_all(HANDLE h,const BYTE *data,DWORD size) {
    DWORD at=0;
    while(at<size) {
        DWORD got=0;
        if(!admitted()||!WriteFile(h,data+at,size-at,&got,NULL)||!got||got>size-at) return 0;
        at+=got;
    }
    return 1;
}
static int size_of(HANDLE h,DWORD expected,DWORD *size) {
    DWORD high=0,low;SetLastError(0);low=GetFileSize(h,&high);
    if(high||low==0xffffffffu||!low||low>MAX_CAPTURE||(expected&&low!=expected)) return 0;
    *size=low;return 1;
}
/* Stream has a bounded expected size; source remains locked read-only. */
static int scan(HANDLE h,DWORD size,int result,char digest[65]) {
    Sha256 sha;BYTE hash[32],prefix[13],tail[13],extra;DWORD total=0,tail_used=0;
    const char footer[]="complete,60\r\n";
    sha256_init(&sha);memset(prefix,0,sizeof(prefix));memset(tail,0,sizeof(tail));
    while(total<size) {
        DWORD want=size-total,got=0,keep;
        if(want>sizeof(chunk)) want=sizeof(chunk);
        if(!admitted()||!ReadFile(h,chunk,want,&got,NULL)||!got||got>want) return 0;
        if(total<sizeof(prefix)) {
            keep=(DWORD)sizeof(prefix)-total;if(keep>got) keep=got;
            memcpy(prefix+total,chunk,keep);
        }
        if(got>=sizeof(tail)) { memcpy(tail,chunk+got-sizeof(tail),sizeof(tail));tail_used=sizeof(tail); }
        else {
            if(tail_used+got>sizeof(tail)) {
                keep=(DWORD)sizeof(tail)-got;memmove(tail,tail+tail_used-keep,keep);tail_used=keep;
            }
            memcpy(tail+tail_used,chunk,got);tail_used+=got;
        }
        sha256_update(&sha,chunk,got);total+=got;
    }
    { DWORD got=0;if(!ReadFile(h,&extra,1,&got,NULL)||got) return 0; }
    sha256_final(&sha,hash);hex_digest(hash,digest);
    if(result&&(size<sizeof(prefix)+sizeof(tail)||
                memcmp(prefix,"S2AM-LOAD,1\r\n",13)||tail_used!=sizeof(tail)||
                memcmp(tail,footer,sizeof(tail)))) return 0;
    return 1;
}
static HANDLE verified(LPCWSTR path,DWORD expected,int result,DWORD *size,char digest[65]) {
    HANDLE h=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(h==INVALID_HANDLE_VALUE) return h;
    if(!size_of(h,expected,size)||!scan(h,*size,result,digest)) { CloseHandle(h);return INVALID_HANDLE_VALUE; }
    return h;
}
static int rewind_file(HANDLE h) { return SetFilePointer(h,0,NULL,FILE_BEGIN)==0; }
static int copy_stream(HANDLE in,HANDLE out,DWORD size,char digest[65]) {
    Sha256 sha;BYTE hash[32];DWORD total=0;
    sha256_init(&sha);
    while(total<size) {
        DWORD want=size-total,got=0;
        if(want>sizeof(chunk)) want=sizeof(chunk);
        if(!admitted()||!ReadFile(in,chunk,want,&got,NULL)||!got||got>want||!write_all(out,chunk,got)) return 0;
        sha256_update(&sha,chunk,got);total+=got;
    }
    sha256_final(&sha,hash);hex_digest(hash,digest);return 1;
}
static void claim_text(char out[128]) {
    char *at=append_text(out,"S2AM-LOAD-START,1\r\n");
    at=append_text(at,LOAD_EXPECTED_SHA256);append_text(at,"\r\n");
}
static int write_new(LPCWSTR path,const char *text) {
    HANDLE h=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    int ok;
    if(h==INVALID_HANDLE_VALUE) return 0;
    ok=write_all(h,(const BYTE*)text,(DWORD)strlen(text));
    if(!FlushFileBuffers(h)) ok=0;
    if(!CloseHandle(h)) ok=0;
    return ok;
}
static int matching_claim(void) {
    HANDLE h;char expected[128],body[128];DWORD size=0,got=0;int ok;
    claim_text(expected);
    h=CreateFileW(RUN_CLAIM,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(h==INVALID_HANDLE_VALUE) return 0;
    ok=size_of(h,(DWORD)strlen(expected),&size)&&size<sizeof(body)&&
       ReadFile(h,body,size,&got,NULL)&&got==size&&!memcmp(body,expected,size);
    if(!CloseHandle(h)) ok=0;
    return ok;
}
static HANDLE copy_collector(void) {
    HANDLE in=INVALID_HANDLE_VALUE,out=INVALID_HANDLE_VALUE,lock=INVALID_HANDLE_VALUE;
    DWORD size=0,check_size=0;char digest[65],copied[65];int ok=0;
    in=verified(source,LOAD_EXPECTED_SIZE,0,&size,digest);
    if(in==INVALID_HANDLE_VALUE||strcmp(digest,LOAD_EXPECTED_SHA256)||!rewind_file(in)) goto done;
    out=CreateFileW(RUN_EXE,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(out==INVALID_HANDLE_VALUE) goto done;
    if(!copy_stream(in,out,size,copied)||strcmp(digest,copied)||!FlushFileBuffers(out)) goto done;
    { HANDLE h=out;out=INVALID_HANDLE_VALUE;if(!CloseHandle(h)) goto done; }
    lock=verified(RUN_EXE,LOAD_EXPECTED_SIZE,0,&check_size,copied);
    if(lock==INVALID_HANDLE_VALUE||strcmp(copied,digest)) goto done;
    ok=1;
done:
    if(out!=INVALID_HANDLE_VALUE&&!CloseHandle(out)) ok=0;
    if(in!=INVALID_HANDLE_VALUE&&!CloseHandle(in)) ok=0;
    if(!ok&&lock!=INVALID_HANDLE_VALUE) { CloseHandle(lock);lock=INVALID_HANDLE_VALUE; }
    return lock;
}
static int ready_file(DWORD pid,DWORD tid) {
    HANDLE h;BYTE data[256];DWORD got=0;int ready=0;
    h=CreateFileW(RUN_SCRATCH,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,
                  OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(h==INVALID_HANDLE_VALUE) return 0;
    if(ReadFile(h,data,sizeof(data),&got,NULL)&&got<=sizeof(data)) ready=header_ready(data,got,pid,tid);
    if(!CloseHandle(h)) return -1;
    return ready;
}
static int start(void) {
    HANDLE lock;PROCESS_INFORMATION pi;unsigned i;int confirmed=0,ok=0;char receipt[256],*at;
    lock=copy_collector();if(lock==INVALID_HANDLE_VALUE) return 0;
    memset(&pi,0,sizeof(pi));
    if(!admitted()||!CreateProcessW(RUN_EXE,NULL,NULL,NULL,FALSE,0,NULL,NULL,NULL,&pi)) { CloseHandle(lock);return 0; }
    ok=CloseHandle(lock)!=0;
    if(!pi.hProcess||pi.hProcess==INVALID_HANDLE_VALUE||!pi.hThread||
       pi.hThread==INVALID_HANDLE_VALUE||!pi.dwProcessId||!pi.dwThreadId) ok=0;
    for(i=0;ok&&i<20&&admitted();i++) {
        int ready;
        if(WaitForSingleObject(pi.hProcess,0)!=258u) break;
        ready=ready_file(pi.dwProcessId,pi.dwThreadId);
        if(ready<0) break;
        if(ready==1) {
            if(WaitForSingleObject(pi.hProcess,0)==258u) confirmed=1;
            break;
        }
        Sleep(250);
    }
    if(pi.hThread&&pi.hThread!=INVALID_HANDLE_VALUE&&!CloseHandle(pi.hThread)) ok=0;
    if(pi.hProcess&&pi.hProcess!=INVALID_HANDLE_VALUE&&!CloseHandle(pi.hProcess)) ok=0;
    if(!ok||!confirmed) return 0;
    at=append_text(receipt,"S2AM-LOAD-STARTED,1\r\npid,");at=append_number(at,pi.dwProcessId);
    at=append_text(at,"\r\ntid,");at=append_number(at,pi.dwThreadId);
    at=append_text(at,"\r\npayload,");at=append_text(at,LOAD_EXPECTED_SHA256);append_text(at,"\r\n");
    return write_new(usb_receipt,receipt);
}
static int collect(void) {
    HANDLE in=INVALID_HANDLE_VALUE,out=INVALID_HANDLE_VALUE,check=INVALID_HANDLE_VALUE;
    DWORD size=0,check_size=0;char expected[65],digest[65],copied[65];int ok=0;
    check=verified(RUN_EXE,LOAD_EXPECTED_SIZE,0,&check_size,digest);
    if(check==INVALID_HANDLE_VALUE||strcmp(digest,LOAD_EXPECTED_SHA256)) goto done;
    { HANDLE h=check;check=INVALID_HANDLE_VALUE;if(!CloseHandle(h)) goto done; }
    if(!missing(usb_result)||!missing(usb_scratch)) goto done;
    in=verified(RUN_RESULT,0,1,&size,expected);
    if(in==INVALID_HANDLE_VALUE||!rewind_file(in)) goto done;
    out=CreateFileW(usb_scratch,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(out==INVALID_HANDLE_VALUE) goto done;
    if(!copy_stream(in,out,size,copied)||strcmp(expected,copied)||!FlushFileBuffers(out)) goto done;
    { HANDLE h=out;out=INVALID_HANDLE_VALUE;if(!CloseHandle(h)) goto done; }
    check=verified(usb_scratch,size,1,&check_size,digest);
    if(check==INVALID_HANDLE_VALUE||strcmp(digest,expected)) goto done;
    { HANDLE h=check;check=INVALID_HANDLE_VALUE;if(!CloseHandle(h)) goto done; }
    { HANDLE h=in;in=INVALID_HANDLE_VALUE;if(!CloseHandle(h)) goto done; }
    if(!admitted()||!MoveFileW(usb_scratch,usb_result)) goto done;
    ok=1;
done:
    if(check!=INVALID_HANDLE_VALUE&&!CloseHandle(check)) ok=0;
    if(out!=INVALID_HANDLE_VALUE&&!CloseHandle(out)) ok=0;
    if(in!=INVALID_HANDLE_VALUE&&!CloseHandle(in)) ok=0;
    return ok;
}
static int wide_equal(LPCWSTR a,LPCWSTR b) {
    while(*a&&*b) {
        WCHAR x=*a++,y=*b++;
        if(x>=L'a'&&x<=L'z') { x-=32; }
        if(y>=L'a'&&y<=L'z') { y-=32; }
        if(x!=y) return 0;
    }
    return !*a&&!*b;
}
static int paths(void) {
    static const WCHAR *const roots[]={L"\\USB Disk",L"\\USB Disk1",L"\\USB Disk2",L"\\USB Disk 2",L"\\USB Disk3"};
    WCHAR actual[MAX_PATH],expected[MAX_PATH];DWORD n;unsigned i;
    n=GetModuleFileNameW(NULL,actual,MAX_PATH);if(!n||n>=MAX_PATH) return 0;
    for(i=0;i<sizeof(roots)/sizeof(roots[0]);i++) {
        wcscpy(expected,roots[i]);wcscat(expected,L"\\S2AM-LOAD\\S2AMCTL.EXE");
        if(wide_equal(actual,expected)) {
            wcscpy(source,roots[i]);wcscat(source,L"\\S2AM-LOAD\\S2AMLOAD.EXE");
            wcscpy(usb_result,roots[i]);wcscat(usb_result,L"\\S2AM-LOAD\\LOAD.CSV");
            wcscpy(usb_scratch,roots[i]);wcscat(usb_scratch,L"\\S2AM-LOAD\\LOAD.TMP");
            wcscpy(usb_receipt,roots[i]);wcscat(usb_receipt,L"\\S2AM-LOAD\\STARTED.TXT");
            return 1;
        }
    }
    return 0;
}
int WINAPI WinMain(HINSTANCE instance,HINSTANCE prior,LPWSTR command,int show) {
    char claim[128];int action=0;DWORD error;
    (void)instance;(void)prior;(void)show;started=GetTickCount();
    if((command&&*command)||!paths()) goto done;
    if(!missing(usb_result)||!missing(usb_scratch)) goto done;
    if(!directory(L"\\SyncExtendedPack\\_s2am")||!directory(L"\\SyncExtendedPack\\_s2am\\load")) goto done;
    SetLastError(0);
    if(CreateDirectoryW(RUN_DIR,NULL)) {
        if(!missing(usb_receipt)) goto done;
        claim_text(claim);
        if(!write_new(RUN_CLAIM,claim)||!start()) goto done;
        action=1;
    } else {
        error=GetLastError();
        if((error!=183u&&error!=80u)||!matching_claim()||!collect()) goto done;
        action=2;
    }
done:
    MessageBoxW(NULL,action==1?
        L"Logging started internally. Close this dialog, remove the USB, then connect CarPlay. Keep SYNC on while parked for at least 6 minutes. Reconnect the USB and run S2AMCTL.EXE to collect; it will not start another recording.":
        action==2?L"LOAD.CSV collected and verified on the USB. Close this dialog and return the USB. Do not start another recording.":
        L"Start or collection not confirmed. Do not run S2AMLOAD.EXE or delete any files. If you already started recording, wait at least 6 minutes before collection. Return the USB for analysis if collection still fails.",
        L"SYNC 2 load logger",MB_OK|(action?MB_ICONINFORMATION:MB_ICONEXCLAMATION));
    return action?0:1;
}
