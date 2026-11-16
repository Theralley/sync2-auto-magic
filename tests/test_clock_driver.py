"""Run the real CE driver/controller C against bounded Windows API fakes."""
import shutil
import subprocess
import tempfile
import unittest
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WINDOWS = r'''
#ifndef FAKE_WINDOWS_H
#define FAKE_WINDOWS_H
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
typedef uint32_t DWORD, ULONG;
typedef int32_t LONG;
typedef unsigned char BYTE;
typedef int BOOL;
typedef void *HANDLE, *HINSTANCE, *HMODULE, *LPVOID, *HKEY;
typedef const void *LPCVOID;
typedef wchar_t WCHAR, *LPWSTR;
typedef const wchar_t *LPCWSTR;
typedef uintptr_t ULONG_PTR;
typedef union { int64_t QuadPart; struct { DWORD LowPart; int32_t HighPart; }; } LARGE_INTEGER;
typedef int (*FARPROC)(void);
typedef struct { DWORD dwSize; HANDLE hDevice, hParentDevice; WCHAR szLegacyName[6];
                 WCHAR szDeviceKey[260], szDeviceName[260], szBusName[260]; } DEVMGR_DEVICE_INFORMATION;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define GENERIC_READ 0x80000000U
#define GENERIC_WRITE 0x40000000U
#define FILE_SHARE_READ 1
#define CREATE_NEW 1
#define OPEN_EXISTING 3
#define FILE_ATTRIBUTE_NORMAL 128
#define DLL_PROCESS_ATTACH 1
#define HKEY_LOCAL_MACHINE ((HKEY)(intptr_t)10)
#define REG_SZ 1
#define REG_MULTI_SZ 7
#define REG_DWORD 4
#define REG_OPTION_NON_VOLATILE 0
#define REG_CREATED_NEW_KEY 1
#define REG_OPENED_EXISTING_KEY 2
#define ERROR_SUCCESS 0
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_ACCESS_DENIED 5
#define ERROR_INVALID_HANDLE 6
#define ERROR_NOT_SUPPORTED 50
#define ERROR_INVALID_PARAMETER 87
#define ERROR_INSUFFICIENT_BUFFER 122
#define ERROR_BUSY 170
#define ERROR_NO_MORE_ITEMS 259
#define ERROR_OPERATION_ABORTED 995
HANDLE CreateFileW(LPCWSTR,DWORD,DWORD,void *,DWORD,DWORD,HANDLE);
BOOL ReadFile(HANDLE,void *,DWORD,DWORD *,void *);
BOOL WriteFile(HANDLE,const void *,DWORD,DWORD *,void *);
BOOL FlushFileBuffers(HANDLE);
BOOL CloseHandle(HANDLE);
HMODULE LoadLibraryW(LPCWSTR);
FARPROC GetProcAddress(HMODULE,LPCWSTR);
BOOL FreeLibrary(HMODULE);
DWORD GetModuleFileNameW(HMODULE,LPWSTR,DWORD);
DWORD GetLastError(void);
void SetLastError(DWORD);
LONG InterlockedCompareExchange(volatile LONG *,LONG,LONG);
LONG InterlockedExchange(volatile LONG *,LONG);
HKEY OpenDeviceKey(LPCWSTR);
LONG RegCloseKey(HKEY);
LONG RegOpenKeyExW(HKEY,LPCWSTR,DWORD,DWORD,HKEY *);
LONG RegQueryValueExW(HKEY,LPCWSTR,DWORD *,DWORD *,BYTE *,DWORD *);
LONG RegEnumValueW(HKEY,DWORD,LPWSTR,DWORD *,DWORD *,DWORD *,BYTE *,DWORD *);
LONG RegEnumKeyExW(HKEY,DWORD,LPWSTR,DWORD *,DWORD *,LPWSTR,DWORD *,void *);
LONG RegCreateKeyExW(HKEY,LPCWSTR,DWORD,LPWSTR,DWORD,DWORD,void *,HKEY *,DWORD *);
LONG RegSetValueExW(HKEY,LPCWSTR,DWORD,DWORD,const BYTE *,DWORD);
LONG RegFlushKey(HKEY);
LONG RegDeleteKeyW(HKEY,LPCWSTR);
HANDLE ActivateDeviceEx(LPCWSTR,LPCVOID,DWORD,LPVOID);
BOOL DeactivateDevice(HANDLE);
BOOL GetDeviceInformationByDeviceHandle(HANDLE,DEVMGR_DEVICE_INFORMATION *);
BOOL GetDeviceInformationByFileHandle(HANDLE,DEVMGR_DEVICE_INFORMATION *);
BOOL DeviceIoControl(HANDLE,DWORD,void *,DWORD,void *,DWORD,DWORD *,void *);
#endif
'''

REGISTRY_SHIM = r'''
#include "windows.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "clock_probe_protocol.h"
static const char *mode;
static DWORD error;
static WCHAR dll_path[MAX_PATH] = L"\\SyncExtendedPack\\_s2am\\jobs\\test-run\\s2amclkdrv.dll";
static const WCHAR key_path[] = L"Drivers\\S2AMClock";
/* Independent fixture: do not let a mistaken production resource range/type
 * change both the implementation and its expected registry bytes. */
static const DWORD fixture_user_mode=0x10,fixture_internal=0,fixture_bus=0;
static const WCHAR fixture_mem_base[]=L"83f80000\00073fd4000\000";
static const WCHAR fixture_mem_len[]=L"30\00058\000";
static const SCK_REG_VALUE fixture_values[] = {
    {L"Dll",REG_SZ,NULL,0},
    {L"Prefix",REG_SZ,L"SCK",4*sizeof(WCHAR)},
    {L"Flags",REG_DWORD,&fixture_user_mode,sizeof(DWORD)},
    {L"InterfaceType",REG_DWORD,&fixture_internal,sizeof(DWORD)},
    {L"BusNumber",REG_DWORD,&fixture_bus,sizeof(DWORD)},
    {L"MemBase",REG_MULTI_SZ,fixture_mem_base,sizeof(fixture_mem_base)},
    {L"MemLen",REG_MULTI_SZ,fixture_mem_len,sizeof(fixture_mem_len)}
};
#define FIXTURE_VALUE_COUNT 7U
static int ismode(const char *s) { return !strcmp(mode,s); }
DWORD GetLastError(void) { return error; }
void SetLastError(DWORD e) { error=e; }
LONG InterlockedCompareExchange(volatile LONG *p,LONG x,LONG c) {
    return __sync_val_compare_and_swap(p,c,x);
}
LONG InterlockedExchange(volatile LONG *p,LONG x) { return __sync_lock_test_and_set(p,x); }
DWORD GetModuleFileNameW(HMODULE module,LPWSTR out,DWORD count) {
    const WCHAR *path=module ? dll_path : L"\\SyncExtendedPack\\_s2am\\jobs\\test-run\\s2amclockctl.exe";
    assert(wcslen(path)<count); wcscpy(out,path); return (DWORD)wcslen(path);
}
HKEY OpenDeviceKey(LPCWSTR active) {
    assert(!wcscmp(active,L"Drivers\\Active\\42"));
    if (ismode("openkey-null")) return NULL;
    if (ismode("openkey-invalid")) return (HKEY)INVALID_HANDLE_VALUE;
    puts("open-key"); return (HKEY)(intptr_t)11;
}
LONG RegCloseKey(HKEY key) {
    if(key==(HKEY)(intptr_t)12) return ismode("host-close-fail") ? ERROR_ACCESS_DENIED : 0;
    assert(key==(HKEY)(intptr_t)11);
    return ismode("key-close-fail") ? ERROR_ACCESS_DENIED : 0;
}
LONG RegOpenKeyExW(HKEY root,LPCWSTR path,DWORD reserved,DWORD access,HKEY *key) {
    assert(root==HKEY_LOCAL_MACHINE && !wcscmp(path,L"Drivers") && !reserved && !access);
    if(ismode("host-open-fail")) return ERROR_ACCESS_DENIED;
    *key=(HKEY)(intptr_t)12; return 0;
}
LONG RegQueryValueExW(HKEY key,LPCWSTR name,DWORD *reserved,DWORD *type,BYTE *out,DWORD *size) {
    unsigned i; assert(!reserved);
    if(key==(HKEY)(intptr_t)12) {
        const WCHAR *expected=!wcscmp(name,L"ProcName") ? L"udevice.exe" : L"$udevice";
        DWORD length=(DWORD)(wcslen(expected)+1)*sizeof(WCHAR);
        assert(!wcscmp(name,L"ProcName") || !wcscmp(name,L"ProcVolPrefix"));
        assert(*size>=length); memcpy(out,expected,length); *size=length; *type=REG_SZ;
        if(ismode("host-proc-mismatch")) out[0]='x';
        if(ismode("host-prefix-type")) *type=REG_MULTI_SZ;
        return 0;
    }
    assert(key==(HKEY)(intptr_t)11);
    for(i=0;i<FIXTURE_VALUE_COUNT;i++) if(!wcscmp(name,fixture_values[i].name)) {
        const void *value=fixture_values[i].data; DWORD length=fixture_values[i].size;
        if(i==0) { value=dll_path; length=(DWORD)(wcslen(dll_path)+1)*sizeof(WCHAR); }
        if(ismode("missing-value") && i==5) return ERROR_FILE_NOT_FOUND;
        if(*size<length) return ERROR_INSUFFICIENT_BUFFER;
        memcpy(out,value,length); *size=length; *type=fixture_values[i].type;
        if(ismode("bad-type") && i==2) *type=REG_SZ;
        if(ismode("bad-flags") && i==2) *(DWORD *)out=0x12;
        if(ismode("bad-membase") && i==5) out[0]='9';
        if(ismode("bad-memlen") && i==6) out[0]='4';
        if(ismode("missing-double-nul") && i==6) *size-=sizeof(WCHAR);
        if(ismode("bad-bus") && i==4) *(DWORD *)out=1;
        return 0;
    }
    return ERROR_FILE_NOT_FOUND;
}
LONG RegEnumValueW(HKEY key,DWORD i,LPWSTR name,DWORD *count,DWORD *reserved,DWORD *type,BYTE *data,DWORD *size) {
    (void)key;(void)reserved;(void)type;(void)data;(void)size;
    if(i>=FIXTURE_VALUE_COUNT) {
        if(i==FIXTURE_VALUE_COUNT && ismode("extra-value")) { wcscpy(name,L"Context"); *count=7; return 0; }
        return ERROR_NO_MORE_ITEMS;
    }
    assert(*count>wcslen(fixture_values[i].name)); wcscpy(name,fixture_values[i].name);
    *count=(DWORD)wcslen(name); return 0;
}
LONG RegEnumKeyExW(HKEY key,DWORD i,LPWSTR name,DWORD *size,DWORD *r,LPWSTR cls,DWORD *cs,void *t) {
    (void)key;(void)i;(void)name;(void)size;(void)r;(void)cls;(void)cs;(void)t;
    return ismode("subkey") ? 0 : ERROR_NO_MORE_ITEMS;
}
'''

DRIVER_SHIM = REGISTRY_SHIM + r'''
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
DWORD SCK_Init(LPCWSTR,DWORD);
DWORD SCK_Open(DWORD,DWORD,DWORD);
BOOL SCK_IOControl(DWORD,DWORD,BYTE *,DWORD,BYTE *,DWORD,DWORD *);
BOOL SCK_PreClose(DWORD),SCK_Close(DWORD),SCK_PreDeinit(DWORD),SCK_Deinit(DWORD);
DWORD SCK_Read(DWORD,void *,DWORD),SCK_Write(DWORD,const void *,DWORD),SCK_Seek(DWORD,LONG,DWORD);
BOOL DllMain(HINSTANCE,DWORD,LPVOID);
static void *regions[2];
static unsigned maps,unmaps,translates;
static volatile LONG blocked,release_map;
static DWORD device,stream;
static int64_t physicals[2]={0x83f80000,0x73fd4000};
static BOOL translate(int type,ULONG bus,LARGE_INTEGER address,ULONG *space,LARGE_INTEGER *physical) {
    assert(type==0 && bus==0 && *space==0);
    assert(address.QuadPart==physicals[translates]); ++translates;
    puts("translate");
    *physical=address;
    if(ismode("translate-space")) *space=1;
    if(ismode("translate-address")) physical->LowPart+=4;
    return !ismode("translate-fail");
}
static LPVOID map_io(LARGE_INTEGER address,ULONG length,BYTE cached) {
    unsigned index=maps++,i; long page=sysconf(_SC_PAGESIZE);
    assert(index<2 && address.QuadPart==physicals[index] && !cached);
    assert(length==(index ? 0x58 : 0x30)); printf("map %u\n",index);
    if(ismode("map-fail") || (index==1 && ismode("partial-map"))) return NULL;
    if(index==0 && (ismode("concurrent") || ismode("preclose") || ismode("predeinit"))) {
        __sync_lock_test_and_set(&blocked,1);
        while(!release_map) usleep(1000);
    }
    regions[index]=mmap(NULL,(size_t)page,PROT_READ|PROT_WRITE,MAP_ANON|MAP_PRIVATE,-1,0);
    assert(regions[index]!=MAP_FAILED);
    for(i=0;i<length/4;i++) ((DWORD *)regions[index])[i]=0xf0000000U+index*0x1000+i*4;
    assert(!mprotect(regions[index],(size_t)page,PROT_READ));
    return regions[index];
}
static void unmap_io(LPVOID address,ULONG length) {
    unsigned index=address==regions[0] ? 0 : 1;
    assert(address==regions[index] && length==(index ? 0x58 : 0x30));
    assert(!munmap(address,(size_t)sysconf(_SC_PAGESIZE))); ++unmaps;
    printf("unmap %u\n",index);
}
HMODULE LoadLibraryW(LPCWSTR name) {
    assert(!wcscmp(name,L"\\Windows\\ceddk.dll")); puts("load");
    return ismode("load-fail") ? NULL : (HMODULE)(intptr_t)1;
}
FARPROC GetProcAddress(HMODULE module,LPCWSTR name) {
    assert(module==(HMODULE)(intptr_t)1);
    if(ismode("missing-export")) return NULL;
    if(!wcscmp(name,L"HalTranslateBusAddress")) return (FARPROC)(void *)translate;
    if(!wcscmp(name,L"MmMapIoSpace")) return (FARPROC)(void *)map_io;
    assert(!wcscmp(name,L"MmUnmapIoSpace")); return (FARPROC)(void *)unmap_io;
}
BOOL FreeLibrary(HMODULE module) { assert(module==(HMODULE)(intptr_t)1); puts("free"); return !ismode("free-fail"); }
static SCK_SNAPSHOT snap;
static void *snapshot_thread(void *unused) {
    DWORD done=0; (void)unused;
    assert(SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&snap,sizeof(snap),&done));
    assert(done==sizeof(snap)); return NULL;
}
int main(int argc,char **argv) {
    DWORD done=999; unsigned i; SCK_SNAPSHOT second; pthread_t thread;
    assert(argc==2); mode=argv[1]; setvbuf(stdout,NULL,_IONBF,0);
    assert(sizeof(DWORD)==4 && sizeof(SCK_SNAPSHOT)==1056);
    assert(DllMain((HINSTANCE)(intptr_t)3,DLL_PROCESS_ATTACH,NULL));
    device=SCK_Init(L"Drivers\\Active\\42",0);
    if(!device) { assert(!maps); puts("init-denied"); return 0; }
    assert(!maps && !translates);
    assert(!SCK_Open(device,GENERIC_WRITE,0));
    assert(!SCK_Open(device,GENERIC_READ|GENERIC_WRITE,0));
    assert(!SCK_Open(device+1,GENERIC_READ,0));
    stream=SCK_Open(device,GENERIC_READ,0); assert(stream && !maps);
    assert(!SCK_Open(device,GENERIC_READ,0));
    if(ismode("invalid-ioctl")) {
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT+4,NULL,0,(BYTE *)&snap,sizeof(snap),&done));
        assert(done==0);
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,(BYTE *)&snap,0,(BYTE *)&snap,sizeof(snap),&done));
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,1,(BYTE *)&snap,sizeof(snap),&done));
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&snap,sizeof(snap)-1,&done));
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&snap,sizeof(snap)+1,&done));
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,NULL,sizeof(snap),&done));
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&snap,sizeof(snap),NULL));
        assert(!SCK_IOControl(stream+1,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&snap,sizeof(snap),&done));
        assert(SCK_Read(stream,&snap,sizeof(snap))==(DWORD)-1);
        assert(SCK_Write(stream,&snap,sizeof(snap))==(DWORD)-1);
        assert(SCK_Seek(stream,0,0)==(DWORD)-1); assert(!maps);
        puts("invalid-denied");
    } else if(ismode("concurrent") || ismode("preclose") || ismode("predeinit")) {
        assert(!pthread_create(&thread,NULL,snapshot_thread,NULL));
        while(!blocked) usleep(1000);
        assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&second,sizeof(second),&done));
        assert(GetLastError()==ERROR_BUSY && !unmaps);
        if(ismode("preclose")) assert(SCK_PreClose(stream));
        if(ismode("predeinit")) assert(SCK_PreDeinit(device));
        assert(!unmaps);
        __sync_lock_test_and_set(&release_map,1); assert(!pthread_join(thread,NULL));
        printf("result %u %u %u\n",snap.status,snap.count,snap.error);
    } else {
        snapshot_thread(NULL);
        assert(snap.magic==SCK_MAGIC && snap.version==1 && snap.bytes==sizeof(snap));
        printf("result %u %u %u\n",snap.status,snap.count,snap.error);
        for(i=0;i<snap.count;i++) printf("R|%u|%u|%u|%u\n",snap.reads[i].pass,snap.reads[i].block,snap.reads[i].offset,snap.reads[i].value);
    }
    assert(SCK_PreClose(stream)); assert(SCK_Close(stream));
    assert(!SCK_IOControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,(BYTE *)&snap,sizeof(snap),&done));
    assert(!SCK_Open(device,GENERIC_READ,0));
    assert(SCK_PreDeinit(device)); assert(SCK_Deinit(device));
    assert(!SCK_Open(device,GENERIC_READ,0));
    return 0;
}
'''

CONTROLLER_SHIM = REGISTRY_SHIM + r'''
static char journal[20000],durable[20000];
static size_t used,dll_position;
static unsigned created,values,activated,deactivated,deleted,ioctls;
static HANDLE activation=(HANDLE)(intptr_t)55,stream=(HANDLE)(intptr_t)56;
static int held;
static void before(const char *stage) {
    size_t n=strlen(durable),m=strlen(stage); assert(n>=m && !strcmp(durable+n-m,stage));
}
HANDLE CreateFileW(LPCWSTR path,DWORD access,DWORD share,void *security,DWORD disposition,DWORD flags,HANDLE template) {
    (void)flags; assert(!security && !template);
    if(!wcscmp(path,dll_path)) {
        before("B|verify-dll\r\n"); assert(access==GENERIC_READ && share==FILE_SHARE_READ && disposition==OPEN_EXISTING);
        held=1; puts("dll-open"); return (HANDLE)(intptr_t)20;
    }
    if(!wcscmp(path,L"SCK4:")) {
        before("B|stream-open\r\n"); assert(access==GENERIC_READ && !share && disposition==OPEN_EXISTING && held);
        puts("stream-open"); return ismode("stream-open-fail") ? INVALID_HANDLE_VALUE : stream;
    }
    assert(!wcscmp(path,L"\\SyncExtendedPack\\_s2am\\jobs\\test-run\\clock-user-driver.txt"));
    assert(access==GENERIC_WRITE && share==FILE_SHARE_READ && disposition==CREATE_NEW);
    return ismode("journal-exists") ? INVALID_HANDLE_VALUE : (HANDLE)(intptr_t)21;
}
BOOL ReadFile(HANDLE h,void *out,DWORD n,DWORD *done,void *overlap) {
    const char *data="abc"; size_t length=3; assert(h==(HANDLE)(intptr_t)20 && !overlap && held);
    if(ismode("dll-changed")) data="abd";
    if(ismode("dll-short")) length=2;
    if(ismode("dll-long")) { data="abcd"; length=4; }
    if(ismode("dll-read-fail")) return 0;
    if(ismode("dll-oversize-read")) { *done=n+1; return 1; }
    if(ismode("dll-short-reads") && n>1) n=1;
    *done=(DWORD)(length-dll_position); if(*done>n) *done=n;
    memcpy(out,data+dll_position,*done); dll_position+=*done; return 1;
}
BOOL WriteFile(HANDLE h,const void *data,DWORD n,DWORD *done,void *overlap) {
    assert(h==(HANDLE)(intptr_t)21 && !overlap);
    if(ismode("journal-write-fail")) { *done=0; return 0; }
    if(ismode("journal-short-writes") && n>1) n=1;
    assert(used+n<sizeof(journal)); memcpy(journal+used,data,n); used+=n; journal[used]=0;
    *done=n; return 1;
}
BOOL FlushFileBuffers(HANDLE h) {
    assert(h==(HANDLE)(intptr_t)21);
    if(!strncmp(mode,"flush-at-",9)) {
        char marker[80]; assert(strlen(mode+9)<60);
        snprintf(marker,sizeof(marker),"B|%s\r\n",mode+9);
        if(strstr(journal,marker)) return 0;
    }
    if(ismode("journal-flush-fail") ||
       (ismode("flush-before-activate") && strstr(journal,"B|activate\r\n")) ||
       (ismode("flush-before-ioctl") && strstr(journal,"B|snapshot\r\n")) ||
       (ismode("final-flush-fail") && strstr(journal,"T|complete\r\n"))) return 0;
    strcpy(durable,journal); return 1;
}
BOOL CloseHandle(HANDLE h) {
    assert(h!=activation);
    if(h==stream) { before("B|stream-close\r\n"); puts("stream-close"); return !ismode("stream-close-fail"); }
    if(h==(HANDLE)(intptr_t)20) { held=0; puts("dll-close"); return !ismode("dll-close-fail"); }
    assert(h==(HANDLE)(intptr_t)21); return !ismode("journal-close-fail");
}
LONG RegCreateKeyExW(HKEY root,LPCWSTR path,DWORD zero,LPWSTR cls,DWORD opt,DWORD access,void *security,HKEY *key,DWORD *disposition) {
    (void)access; assert(root==HKEY_LOCAL_MACHINE && !wcscmp(path,key_path) && !zero && !cls && !opt && !security);
    before("B|registry-create\r\n"); assert(held); ++created;
    *key=(HKEY)(intptr_t)11; *disposition=ismode("key-exists") ? REG_OPENED_EXISTING_KEY : REG_CREATED_NEW_KEY;
    puts("key-create"); return ismode("key-create-fail") ? ERROR_ACCESS_DENIED : 0;
}
LONG RegSetValueExW(HKEY key,LPCWSTR name,DWORD zero,DWORD type,const BYTE *data,DWORD size) {
    const SCK_REG_VALUE *value=&fixture_values[values]; const void *expected=value->data; DWORD n=value->size;
    assert(key==(HKEY)(intptr_t)11 && !zero && values<FIXTURE_VALUE_COUNT);
    assert(!wcscmp(name,value->name) && type==value->type);
    if(!values) { expected=dll_path; n=(DWORD)(wcslen(dll_path)+1)*sizeof(WCHAR); }
    assert(size==n && !memcmp(data,expected,n)); ++values;
    return ismode("key-set-fail") ? ERROR_ACCESS_DENIED : 0;
}
LONG RegFlushKey(HKEY key) { assert(key==(HKEY)(intptr_t)11); return ismode("key-flush-fail") ? ERROR_ACCESS_DENIED : 0; }
LONG RegDeleteKeyW(HKEY root,LPCWSTR path) {
    assert(root==HKEY_LOCAL_MACHINE && !wcscmp(path,key_path) && deactivated && held);
    before("B|registry-delete\r\n"); ++deleted; puts("key-delete");
    return ismode("key-delete-fail") ? ERROR_ACCESS_DENIED : 0;
}
HANDLE ActivateDeviceEx(LPCWSTR path,LPCVOID reg,DWORD count,LPVOID param) {
    assert(!wcscmp(path,key_path) && !reg && !count && !param && held && values==FIXTURE_VALUE_COUNT);
    before("B|activate\r\n"); ++activated; puts("activate");
    if(ismode("activate-crash")) exit(91);
    if(ismode("activate-null")) return NULL;
    if(ismode("activate-invalid")) return INVALID_HANDLE_VALUE;
    return activation;
}
BOOL DeactivateDevice(HANDLE h) {
    assert(h==activation && held); before("B|deactivate\r\n"); puts("deactivate");
    if(ismode("deactivate-fail")) return 0;
    ++deactivated; return 1;
}
static BOOL info(DEVMGR_DEVICE_INFORMATION *out,int from_file) {
    assert(out->dwSize==sizeof(*out) && held);
    out->hDevice=activation; wcscpy(out->szLegacyName,L"SCK4:"); wcscpy(out->szDeviceKey,key_path);
    if(ismode(from_file ? "file-info-fail" : "device-info-fail")) return 0;
    if(ismode(from_file ? "file-handle-mismatch" : "device-handle-mismatch")) out->hDevice=(HANDLE)(intptr_t)57;
    if(ismode(from_file ? "file-key-mismatch" : "device-key-mismatch")) out->szDeviceKey[0]='X';
    if(ismode("legacy-invalid")) wcscpy(out->szLegacyName,L"COM4:");
    if(ismode("legacy-unterminated")) out->szLegacyName[5]='X';
    if(ismode("key-unterminated")) { unsigned i; for(i=0;i<MAX_PATH;i++) out->szDeviceKey[i]='A'; }
    if(ismode("info-size-mismatch")) out->dwSize=0;
    if(from_file && ismode("file-name-mismatch")) out->szLegacyName[3]='5';
    return 1;
}
BOOL GetDeviceInformationByDeviceHandle(HANDLE h,DEVMGR_DEVICE_INFORMATION *out) { assert(h==activation); before("B|activation-identity\r\n"); return info(out,0); }
BOOL GetDeviceInformationByFileHandle(HANDLE h,DEVMGR_DEVICE_INFORMATION *out) { assert(h==stream); before("B|stream-identity\r\n"); return info(out,1); }
BOOL DeviceIoControl(HANDLE h,DWORD code,void *input,DWORD in_size,void *output,DWORD out_size,DWORD *done,void *overlap) {
    SCK_SNAPSHOT *s=output; DWORD pass,block,i; assert(h==stream && code==SCK_IOCTL_SNAPSHOT && !input && !in_size && !overlap);
    assert(out_size==sizeof(*s) && held); before("B|snapshot\r\n"); ++ioctls; puts("snapshot");
    if(ismode("ioctl-fail")) return 0;
    memset(s,0,sizeof(*s)); s->magic=SCK_MAGIC; s->version=1; s->bytes=sizeof(*s); s->stage=SCK_STAGE_COMPLETE;
    for(pass=1;pass<=2;pass++) for(block=1;block<=3;block++) for(i=0;i<(block==2 ? 10U : 11U);i++) {
        SCK_READING *r=&s->reads[s->count++]; r->pass=pass; r->block=block;
        r->offset=block==2 ? sck_pll_offsets[i] : sck_ccm_offsets[i]; r->value=0;
    }
    *done=sizeof(*s);
    if(ismode("snapshot-bad-magic")) s->magic=0;
    if(ismode("snapshot-bad-count")) s->count=65;
    if(ismode("snapshot-bad-offset")) s->reads[10].offset=999;
    if(ismode("snapshot-bad-order")) s->reads[3].pass=2;
    if(ismode("snapshot-short")) --*done;
    if(ismode("snapshot-failed")) { s->status=1; s->stage=SCK_STAGE_MAP_PLL; s->error=87; s->count=0; }
    return 1;
}
int WinMain(HINSTANCE,HINSTANCE,LPWSTR,int);
int main(int argc,char **argv) {
    int result; WCHAR command[256]; size_t i;
    assert(argc>=2); mode=argv[1];
    for(i=0;argv[argc-1][i] && i<255;i++) command[i]=(WCHAR)argv[argc-1][i]; command[i]=0;
    if(argc==2) wcscpy(command,L"test-run");
    result=WinMain(NULL,NULL,command,0);
    printf("COUNTS %u %u %u %u %u %u\n",created,values,activated,deactivated,deleted,ioctls);
    printf("JOURNAL\n%s",journal); return result;
}
'''


@unittest.skipUnless(shutil.which("cc"), "needs a host C compiler")
class NativeClockDriver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "devload.h").write_text('#include "windows.h"\n')
        (cls.work / "driver-shim.c").write_text(DRIVER_SHIM)
        cls.program = cls.work / "driver"
        result = subprocess.run(
            ["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-const-variable",
             "-pthread", "-I", str(cls.work), "-I", str(ROOT / "s2am/native"),
             str(ROOT / "s2am/native/s2amclkdrv.c"), str(cls.work / "driver-shim.c"), "-o", str(cls.program)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_driver(self, mode):
        result = subprocess.run([str(self.program), mode], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_exact_bracketed_reads_from_readonly_fake_mmio(self):
        output = self.run_driver("ok")
        expected = []
        pll = (0, 4, 8, 12, 16, 28, 32, 36, 40, 44)
        ccm = (0, 8, 12, 16, 20, 24, 28, 32, 72, 76, 84)
        for sample in (1, 2):
            for block, offsets, bias in ((1, ccm, 0x1000), (2, pll, 0), (3, ccm, 0x1000)):
                expected.extend(f"R|{sample}|{block}|{offset}|{0xf0000000+bias+offset}" for offset in offsets)
        self.assertEqual([line for line in output.splitlines() if line.startswith("R|")], expected)
        self.assertIn("result 0 64 0", output)
        self.assertLess(output.index("unmap 1"), output.index("unmap 0"))

    def test_rejects_unknown_and_malformed_requests_without_loading(self):
        output = self.run_driver("invalid-ioctl")
        self.assertIn("invalid-denied", output)
        self.assertNotIn("load", output)

    def test_registry_is_an_exact_typed_contract(self):
        for mode in ("openkey-null", "openkey-invalid", "missing-value", "bad-type", "bad-flags", "bad-membase", "bad-memlen", "missing-double-nul", "bad-bus", "key-close-fail", "extra-value", "subkey"):
            with self.subTest(mode=mode):
                output = self.run_driver(mode)
                self.assertIn("init-denied", output)
                self.assertNotIn("load", output)

    def test_mapping_and_translation_failures_do_not_sample(self):
        for mode in ("load-fail", "missing-export", "translate-fail", "translate-space", "translate-address", "map-fail", "partial-map"):
            with self.subTest(mode=mode):
                output = self.run_driver(mode)
                self.assertIn("result 1 0", output)
                self.assertNotIn("R|", output)
                if mode == "partial-map":
                    self.assertIn("unmap 0", output)
                    self.assertNotIn("unmap 1", output)

    def test_calls_serialize_and_preclose_predeinit_never_unmap_inflight(self):
        for mode in ("concurrent", "preclose", "predeinit"):
            with self.subTest(mode=mode):
                output = self.run_driver(mode)
                self.assertIn("result 0 64 0" if mode == "concurrent" else "result 1 0 995", output)
                self.assertIn("unmap 0", output)

    def test_library_cleanup_failure_is_not_a_complete_sample(self):
        self.assertIn("result 1 64", self.run_driver("free-fail"))


@unittest.skipUnless(shutil.which("cc"), "needs a host C compiler")
class NativeClockController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "windows.h").write_text(WINDOWS)
        (cls.work / "devload.h").write_text('#include "windows.h"\n')
        (cls.work / "controller-shim.c").write_text(CONTROLLER_SHIM)
        cls.program = cls.work / "controller"
        result = subprocess.run(
            ["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-const-variable",
             "-DSCK_EXPECTED_DLL_SIZE=3", '-DSCK_EXPECTED_DLL_SHA256="' + hashlib.sha256(b"abc").hexdigest() + '"',
             "-I", str(cls.work), "-I", str(ROOT / "s2am/native"),
             str(ROOT / "s2am/native/s2amclockctl.c"), str(cls.work / "controller-shim.c"), "-o", str(cls.program)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.hash_program = cls.work / "hash"
        (cls.work / "hash-shim.c").write_text(
            '#define journal controller_journal\n#include "s2amclockctl.c"\n#undef journal\n#define main controller_test_main\n'
            '#include "controller-shim.c"\n#undef main\n'
            'int main(void) { SCK_SHA h; BYTE b[37]; size_t n; char hex[65]; sha_init(&h); '
            'while ((n=fread(b,1,sizeof(b),stdin))) sha_update(&h,b,(DWORD)n); '
            'sha_final(&h,hex); puts(hex); return 0; }\n'
        )
        result = subprocess.run(
            ["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-unused-const-variable",
             "-DSCK_EXPECTED_DLL_SIZE=3", '-DSCK_EXPECTED_DLL_SHA256="' + hashlib.sha256(b"abc").hexdigest() + '"',
             "-I", str(cls.work), "-I", str(ROOT / "s2am/native"),
             str(cls.work / "hash-shim.c"), "-o", str(cls.hash_program)], capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_ctl(self, mode="ok", argument=None):
        command = [str(self.program), mode]
        if argument is not None:
            command.append(argument)
        return subprocess.run(command, capture_output=True, text=True, timeout=5)

    def test_success_requires_typed_registry_two_identities_snapshot_and_cleanup(self):
        result = self.run_ctl()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COUNTS 1 7 1 1 1 1", result.stdout)
        self.assertTrue(result.stdout.endswith("T|complete\n"))
        self.assertEqual(sum(line.startswith("R|") for line in result.stdout.splitlines()), 64)
        from s2am.clock_snapshot import analyze
        report = self.work / "successful-report.txt"
        report.write_text(result.stdout.split("JOURNAL\n", 1)[1])
        parsed = analyze(report, {"status": "exited", "exit_valid": True, "exit": 0,
                                  "wait": 0, "error": 0, "marker": True})
        self.assertTrue(parsed["complete"])
        self.assertTrue(parsed["stable"])

    def test_sha256_known_answers_and_padding_boundaries(self):
        vectors = [b"", b"abc", b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", b"a" * 1000000]
        vectors.extend(bytes(i % 251 for i in range(n)) for n in (55, 56, 63, 64, 65, 119, 120, 127, 128, 4096, 4097))
        for data in vectors:
            with self.subTest(length=len(data)):
                result = subprocess.run([str(self.hash_program)], input=data, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.decode().strip(), hashlib.sha256(data).hexdigest())

    def test_hash_size_or_read_failure_never_creates_registry_key(self):
        for mode in ("dll-changed", "dll-short", "dll-long", "dll-read-fail", "dll-oversize-read"):
            with self.subTest(mode=mode):
                result = self.run_ctl(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("COUNTS 0 0 0 0 0 0", result.stdout)

    def test_short_reads_and_writes_are_supported(self):
        for mode in ("dll-short-reads", "journal-short-writes"):
            result = self.run_ctl(mode)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_registry_failures_or_collisions_never_activate_or_delete(self):
        for mode in ("key-exists", "key-create-fail", "key-set-fail", "key-flush-fail", "key-close-fail", "bad-type", "bad-flags", "bad-memlen", "missing-double-nul", "bad-bus", "extra-value", "subkey"):
            with self.subTest(mode=mode):
                result = self.run_ctl(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("\nactivate\n", result.stdout)
                self.assertNotIn("key-delete", result.stdout)

    def test_both_activation_sentinels_leave_evidence_without_deactivation(self):
        for mode in ("activate-null", "activate-invalid"):
            result = self.run_ctl(mode)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("COUNTS 1 7 1 0 0 0", result.stdout)
            self.assertIn("E|activate|", result.stdout)

    def test_host_configuration_is_verified_before_creating_activation_state(self):
        for mode in ("host-open-fail", "host-proc-mismatch", "host-prefix-type", "host-close-fail"):
            with self.subTest(mode=mode):
                result = self.run_ctl(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("COUNTS 0 0 0 0 0 0", result.stdout)
                self.assertNotIn("T|complete", result.stdout)

    def test_identity_failures_prevent_any_snapshot(self):
        for mode in ("device-info-fail", "device-handle-mismatch", "device-key-mismatch", "file-info-fail", "file-handle-mismatch", "file-key-mismatch", "file-name-mismatch", "legacy-invalid", "legacy-unterminated", "key-unterminated", "info-size-mismatch"):
            with self.subTest(mode=mode):
                result = self.run_ctl(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("\nsnapshot\n", result.stdout)
                self.assertIn("\ndeactivate\n", result.stdout)

    def test_malformed_or_failed_snapshot_has_no_read_records_or_completion(self):
        for mode in ("ioctl-fail", "snapshot-bad-magic", "snapshot-bad-count", "snapshot-bad-offset", "snapshot-bad-order", "snapshot-short", "snapshot-failed"):
            with self.subTest(mode=mode):
                result = self.run_ctl(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("R|", result.stdout)
                self.assertNotIn("T|complete", result.stdout)

    def test_cleanup_failure_is_distinct_and_preserves_key_on_failed_deactivation(self):
        for mode, stage in (("stream-close-fail", "stream-close"), ("deactivate-fail", "deactivate"), ("key-delete-fail", "registry-delete"), ("dll-close-fail", "dll-close")):
            result = self.run_ctl(mode)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("E|" + stage + "|", result.stdout)
            self.assertNotIn("T|complete", result.stdout)
            if mode in ("stream-close-fail", "deactivate-fail"):
                self.assertNotIn("key-delete", result.stdout)

    def test_failed_journal_stops_before_next_potentially_blocking_operation(self):
        for mode in ("journal-exists", "journal-write-fail", "journal-flush-fail", "flush-before-activate", "flush-before-ioctl"):
            with self.subTest(mode=mode):
                result = self.run_ctl(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("T|complete", result.stdout)
                self.assertNotIn("\nsnapshot\n", result.stdout)
                if mode != "flush-before-ioctl":
                    self.assertNotIn("\nactivate\n", result.stdout)
                else:
                    self.assertNotIn("\ndeactivate\n", result.stdout)

    def test_cleanup_flush_failure_preserves_the_last_confirmed_lifecycle_state(self):
        cases = (("stream-close", "1 7 1 0 0 1", ("stream-close", "deactivate", "key-delete", "dll-close")),
                 ("deactivate", "1 7 1 0 0 1", ("deactivate", "key-delete", "dll-close")),
                 ("registry-delete", "1 7 1 1 0 1", ("key-delete", "dll-close")),
                 ("dll-close", "1 7 1 1 1 1", ("dll-close",)))
        for stage, counts, forbidden in cases:
            with self.subTest(stage=stage):
                result = self.run_ctl("flush-at-" + stage)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("COUNTS " + counts, result.stdout)
                self.assertNotIn("T|complete", result.stdout)
                for action in forbidden:
                    self.assertNotIn("\n" + action + "\n", result.stdout)

    def test_final_storage_failure_still_requires_nonzero_child_status(self):
        for mode in ("final-flush-fail", "journal-close-fail"):
            result = self.run_ctl(mode)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("T|complete", result.stdout)

    def test_only_a_bounded_run_id_is_accepted(self):
        for argument in ("", "../test-run", "test-run extra", "test/run", "x" * 41, "TEST-RUN"):
            result = self.run_ctl(argument=argument)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("COUNTS 0 0 0 0 0 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
