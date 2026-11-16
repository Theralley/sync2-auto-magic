/* One-shot experimental activation controller, deliberately outside native.py.
 * Usage: s2amclockctl.exe <run-id>; all paths derive from a fixed job root.
 * Build only after the DLL, binding its exact SHA-256 and size below.
 * No timeout, retry, process kill, DLL deletion, boot registration or MMIO write.
 * A parent timeout cannot cancel an activation or stalled physical-memory load.
 */
#ifndef _WIN32_WCE
#define _WIN32_WCE 0x0600
#endif
#include <windows.h>
#include "clock_probe_protocol.h"
#ifndef SCK_EXPECTED_DLL_SHA256
#error Build the DLL first and provide its SHA-256 as SCK_EXPECTED_DLL_SHA256
#endif
#ifndef SCK_EXPECTED_DLL_SIZE
#error Provide the exact DLL byte size as SCK_EXPECTED_DLL_SIZE
#endif
#if SCK_EXPECTED_DLL_SIZE < 1 || SCK_EXPECTED_DLL_SIZE > 1048576
#error DLL size outside the one-MiB verification bound
#endif

/* SHA-256, FIPS 180-4 section 6.2. Unsigned 32-bit operations only; no provider
 * dependency on CE's installed CryptoAPI algorithms. Tested against hashlib at
 * padding/block boundaries. The compiled digest is an artifact binding, not a
 * signature or a claim that the firmware candidate is trusted. */
typedef struct { DWORD h[8]; BYTE block[64]; DWORD used, bytes; } SCK_SHA;
static DWORD rotate(DWORD value, unsigned int bits) { return (value >> bits) | (value << (32 - bits)); }
static void sha_block(SCK_SHA *hash)
{
    static const DWORD k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
    };
    DWORD w[64], a=hash->h[0], b=hash->h[1], c=hash->h[2], d=hash->h[3];
    DWORD e=hash->h[4], f=hash->h[5], g=hash->h[6], h=hash->h[7];
    unsigned int i;
    for (i=0; i<16; ++i) w[i]=((DWORD)hash->block[i*4]<<24)|((DWORD)hash->block[i*4+1]<<16)|
                              ((DWORD)hash->block[i*4+2]<<8)|hash->block[i*4+3];
    for (i=16; i<64; ++i) w[i]=w[i-16]+(rotate(w[i-15],7)^rotate(w[i-15],18)^(w[i-15]>>3))+
                               w[i-7]+(rotate(w[i-2],17)^rotate(w[i-2],19)^(w[i-2]>>10));
    for (i=0; i<64; ++i) {
        DWORD t1=h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^((~e)&g))+k[i]+w[i];
        DWORD t2=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    hash->h[0]+=a; hash->h[1]+=b; hash->h[2]+=c; hash->h[3]+=d;
    hash->h[4]+=e; hash->h[5]+=f; hash->h[6]+=g; hash->h[7]+=h;
}
static void sha_init(SCK_SHA *hash)
{
    static const DWORD initial[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    memset(hash,0,sizeof(*hash)); memcpy(hash->h,initial,sizeof(initial));
}
static void sha_update(SCK_SHA *hash, const BYTE *data, DWORD size)
{
    DWORD i;
    hash->bytes+=size;
    for (i=0; i<size; ++i) {
        hash->block[hash->used++]=data[i];
        if (hash->used==64) { sha_block(hash); hash->used=0; }
    }
}
static void sha_final(SCK_SHA *hash, char hex[65])
{
    static const char digits[]="0123456789abcdef";
    DWORD bits=hash->bytes*8;
    unsigned int i;
    hash->block[hash->used++]=0x80;
    if (hash->used>56) { memset(hash->block+hash->used,0,64-hash->used); sha_block(hash); hash->used=0; }
    memset(hash->block+hash->used,0,64-hash->used);
    for (i=0; i<4; ++i) hash->block[63-i]=(BYTE)(bits>>(i*8));
    sha_block(hash);
    for (i=0; i<32; ++i) {
        BYTE b=(BYTE)(hash->h[i/4]>>(24-(i%4)*8));
        hex[i*2]=digits[b>>4]; hex[i*2+1]=digits[b&15];
    }
    hex[64]=0;
}

static HANDLE journal = INVALID_HANDLE_VALUE;
static int journal_failed;
static void put(const char *text)
{
    DWORD left=(DWORD)strlen(text);
    while (left && !journal_failed) {
        DWORD done=0;
        if (!WriteFile(journal,text,left,&done,NULL) || !done || done>left) { journal_failed=1; return; }
        text+=done; left-=done;
    }
}
static void number(DWORD value)
{
    char digits[11]; unsigned int i=10; digits[i]=0;
    do { digits[--i]=(char)('0'+value%10); value/=10; } while (value && i);
    put(digits+i);
}
static void field(DWORD value) { put("|"); number(value); }
static int end_line(void)
{
    put("\r\n");
    if (!journal_failed && !FlushFileBuffers(journal)) journal_failed=1;
    return !journal_failed;
}
static int progress(const char *stage) { put("B|"); put(stage); return end_line(); }
static void failure(const char *stage, DWORD error) { put("E|"); put(stage); field(error); end_line(); }

static int verify_dll(HANDLE file)
{
    SCK_SHA hash;
    BYTE buffer[4096];
    char hex[65];
    DWORD total=0, got;
    if (strlen(SCK_EXPECTED_DLL_SHA256)!=64) return 0;
    sha_init(&hash);
    for (;;) {
        got=0;
        if (!ReadFile(file,buffer,sizeof(buffer),&got,NULL) || got>sizeof(buffer)) return 0;
        if (!got) break;
        if (got>SCK_EXPECTED_DLL_SIZE-total) return 0;
        sha_update(&hash,buffer,got); total+=got;
    }
    if (total!=SCK_EXPECTED_DLL_SIZE) return 0;
    sha_final(&hash,hex);
    return !strcmp(hex,SCK_EXPECTED_DLL_SHA256);
}

static int paths(LPCWSTR command, WCHAR key[MAX_PATH], WCHAR dll[MAX_PATH], WCHAR report[MAX_PATH])
{
    static const WCHAR root[]=L"\\SyncExtendedPack\\_s2am\\jobs\\";
    WCHAR own[MAX_PATH], expected[MAX_PATH];
    DWORD length;
    size_t n;
    if (!command) return 0;
    for (n=0; command[n]; ++n) {
        if (n>=40 || !((command[n]>=L'a' && command[n]<=L'z') ||
                      (command[n]>=L'0' && command[n]<=L'9') || command[n]==L'-')) return 0;
    }
    if (!n) return 0;
    /* One exclusive key for every run: an unresolved earlier activation must
     * block a fresh job ID as well as a replay of the same report. */
    wcscpy(key,L"Drivers\\S2AMClock");
    wcscpy(dll,root); wcscat(dll,command); wcscat(dll,L"\\s2amclkdrv.dll");
    wcscpy(report,root); wcscat(report,command); wcscat(report,L"\\clock-user-driver.txt");
    wcscpy(expected,root); wcscat(expected,command); wcscat(expected,L"\\s2amclockctl.exe");
    length=GetModuleFileNameW(NULL,own,MAX_PATH);
    return length && length<MAX_PATH && own[length]==0 && !wcscmp(own,expected);
}

static int host_configuration(void)
{
    static const WCHAR *const names[]={L"ProcName",L"ProcVolPrefix"};
    static const WCHAR *const expected[]={L"udevice.exe",L"$udevice"};
    HKEY key=NULL;
    WCHAR value[32];
    unsigned int i;
    int valid=1;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE,L"Drivers",0,0,&key)!=ERROR_SUCCESS) return 0;
    for (i=0; i<2; ++i) {
        DWORD type=0, size=sizeof(value);
        DWORD expected_size=(DWORD)(wcslen(expected[i])+1)*sizeof(WCHAR);
        if (RegQueryValueExW(key,names[i],NULL,&type,(BYTE *)value,&size)!=ERROR_SUCCESS ||
            type!=REG_SZ || size!=expected_size || memcmp(value,expected[i],size)) valid=0;
    }
    if (RegCloseKey(key)!=ERROR_SUCCESS) valid=0;
    return valid;
}

static int identity(const DEVMGR_DEVICE_INFORMATION *info, HANDLE activation, LPCWSTR key)
{
    size_t n;
    if (info->dwSize!=sizeof(*info) || info->hDevice!=activation) return 0;
    for (n=0; n<MAX_PATH && info->szDeviceKey[n]; ++n) { }
    if (n==MAX_PATH || wcscmp(info->szDeviceKey,key)) return 0;
    return info->szLegacyName[0]==L'S' && info->szLegacyName[1]==L'C' &&
           info->szLegacyName[2]==L'K' && info->szLegacyName[3]>=L'0' &&
           info->szLegacyName[3]<=L'9' && info->szLegacyName[4]==L':' && info->szLegacyName[5]==0;
}

static int valid_snapshot(const SCK_SNAPSHOT *snapshot, DWORD returned)
{
    DWORD pass, block, i, n=0;
    if (returned!=sizeof(*snapshot) || snapshot->magic!=SCK_MAGIC || snapshot->version!=SCK_VERSION ||
        snapshot->bytes!=sizeof(*snapshot) || snapshot->status!=SCK_STATUS_COMPLETE ||
        snapshot->stage!=SCK_STAGE_COMPLETE || snapshot->error || snapshot->reserved || snapshot->count!=SCK_COUNT)
        return 0;
    for (pass=1; pass<=2; ++pass) for (block=1; block<=3; ++block) {
        DWORD count=block==2 ? 10 : 11;
        const DWORD *offsets=block==2 ? sck_pll_offsets : sck_ccm_offsets;
        for (i=0; i<count; ++i) {
            const SCK_READING *r=&snapshot->reads[n++];
            if (r->pass!=pass || r->block!=block || r->offset!=offsets[i]) return 0;
        }
    }
    return n==SCK_COUNT;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR key_path[MAX_PATH], dll_path[MAX_PATH], report_path[MAX_PATH];
    HKEY key=NULL;
    HANDLE dll=INVALID_HANDLE_VALUE, activation=INVALID_HANDLE_VALUE, stream=INVALID_HANDLE_VALUE;
    DEVMGR_DEVICE_INFORMATION info, file_info;
    SCK_SNAPSHOT snapshot;
    DWORD disposition=0, returned=0, error;
    LONG reg_error;
    unsigned int i;
    int result=1, key_owned=0;
    (void)instance; (void)previous; (void)show;
    if (!paths(command,key_path,dll_path,report_path)) return 2;
    journal=CreateFileW(report_path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if (journal==INVALID_HANDLE_VALUE) return 3;
    put("S|s2am-clock-v1");
    if (!end_line() || !progress("verify-dll")) goto finish;
    SetLastError(0);
    /* Keep this handle until cleanup: FILE_SHARE_READ permits the loader but
     * denies a write/delete open while the verified DLL may be active. */
    dll=CreateFileW(dll_path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    if (dll==INVALID_HANDLE_VALUE || !verify_dll(dll)) { failure("verify-dll",GetLastError()); goto cleanup; }
    if (!progress("host-configuration")) goto finish;
    if (!host_configuration()) { failure("host-configuration",ERROR_INVALID_PARAMETER); goto cleanup; }
    if (!progress("registry-create")) goto finish;
    reg_error=RegCreateKeyExW(HKEY_LOCAL_MACHINE,key_path,0,NULL,REG_OPTION_NON_VOLATILE,0,NULL,&key,&disposition);
    if (reg_error!=ERROR_SUCCESS || disposition!=REG_CREATED_NEW_KEY) {
        failure("registry-create",reg_error==ERROR_SUCCESS ? ERROR_ACCESS_DENIED : (DWORD)reg_error);
        goto cleanup;
    }
    key_owned=1;
    if (!progress("registry-values")) goto finish;
    for (i=0; i<SCK_VALUE_COUNT; ++i) {
        const void *data=i ? sck_values[i].data : dll_path;
        DWORD size=i ? sck_values[i].size : (DWORD)(wcslen(dll_path)+1)*sizeof(WCHAR);
        reg_error=RegSetValueExW(key,sck_values[i].name,0,sck_values[i].type,(const BYTE *)data,size);
        if (reg_error!=ERROR_SUCCESS) { failure("registry-values",(DWORD)reg_error); goto cleanup; }
    }
    if (!progress("registry-verify")) goto finish;
    reg_error=RegFlushKey(key);
    if (reg_error!=ERROR_SUCCESS || !sck_verify_key(key,dll_path)) {
        failure("registry-verify",reg_error==ERROR_SUCCESS ? ERROR_INVALID_PARAMETER : (DWORD)reg_error);
        goto cleanup;
    }
    reg_error=RegCloseKey(key); key=NULL;
    if (reg_error!=ERROR_SUCCESS) { failure("registry-close",(DWORD)reg_error); goto cleanup; }
    if (!progress("activate")) goto finish;
    SetLastError(0);
    activation=ActivateDeviceEx(key_path,NULL,0,NULL);
    if (!activation || activation==INVALID_HANDLE_VALUE) {
        failure("activate",GetLastError()); goto cleanup;
    }
    if (!progress("activation-identity")) goto finish;
    memset(&info,0,sizeof(info)); info.dwSize=sizeof(info);
    SetLastError(0);
    if (!GetDeviceInformationByDeviceHandle(activation,&info) || !identity(&info,activation,key_path)) {
        failure("activation-identity",GetLastError()); goto cleanup;
    }
    if (!progress("stream-open")) goto finish;
    SetLastError(0);
    stream=CreateFileW(info.szLegacyName,GENERIC_READ,0,NULL,OPEN_EXISTING,0,NULL);
    if (!stream || stream==INVALID_HANDLE_VALUE) { failure("stream-open",GetLastError()); goto cleanup; }
    if (!progress("stream-identity")) goto finish;
    memset(&file_info,0,sizeof(file_info)); file_info.dwSize=sizeof(file_info);
    SetLastError(0);
    if (!GetDeviceInformationByFileHandle(stream,&file_info) || !identity(&file_info,activation,key_path) ||
        wcscmp(file_info.szLegacyName,info.szLegacyName)) {
        failure("stream-identity",GetLastError()); goto cleanup;
    }
    if (!progress("snapshot")) goto finish;
    memset(&snapshot,0,sizeof(snapshot));
    SetLastError(0);
    if (!DeviceIoControl(stream,SCK_IOCTL_SNAPSHOT,NULL,0,&snapshot,sizeof(snapshot),&returned,NULL)) {
        failure("snapshot-transport",GetLastError()); goto cleanup;
    }
    put("B|snapshot-result"); field(snapshot.status); field(snapshot.stage); field(snapshot.error); field(snapshot.count);
    if (!end_line()) goto finish;
    if (!valid_snapshot(&snapshot,returned)) { failure("snapshot-record",snapshot.error); goto cleanup; }
    for (i=0; i<SCK_COUNT; ++i) {
        const SCK_READING *r=&snapshot.reads[i];
        put("R|"); number(r->pass); put("|");
        put(r->block==1 ? "ccm-before" : r->block==2 ? "pll1" : "ccm-after");
        field(r->offset); field(r->value);
        if (!end_line()) goto finish;
    }
    result=0;
cleanup:
    if (journal_failed) goto finish;
    if (stream && stream!=INVALID_HANDLE_VALUE) {
        if (!progress("stream-close")) goto finish;
        SetLastError(0);
        if (!CloseHandle(stream)) { failure("stream-close",GetLastError()); result=1; goto finish; }
        stream=INVALID_HANDLE_VALUE;
    }
    if (activation && activation!=INVALID_HANDLE_VALUE) {
        if (!progress("deactivate")) goto finish;
        SetLastError(0);
        if (!DeactivateDevice(activation)) { failure("deactivate",GetLastError()); result=1; goto finish; }
        activation=INVALID_HANDLE_VALUE;
        if (key_owned) {
            if (!progress("registry-delete")) goto finish;
            reg_error=RegDeleteKeyW(HKEY_LOCAL_MACHINE,key_path);
            if (reg_error!=ERROR_SUCCESS) { failure("registry-delete",(DWORD)reg_error); result=1; }
        }
    }
    /* Before-activation failures and failed/ambiguous activation retain the key
     * as evidence. No attempt to infer inactive state and delete it. */
    if (key) {
        if (!progress("registry-close")) goto finish;
        reg_error=RegCloseKey(key); key=NULL;
        if (reg_error!=ERROR_SUCCESS) { failure("registry-close",(DWORD)reg_error); result=1; }
    }
    if (dll!=INVALID_HANDLE_VALUE) {
        if (!progress("dll-close")) goto finish;
        SetLastError(0);
        if (!CloseHandle(dll)) { failure("dll-close",GetLastError()); result=1; }
        dll=INVALID_HANDLE_VALUE;
    }
    if (!result && !journal_failed) { put("T|complete"); end_line(); }
finish:
    /* Journal failure is fail-closed: do not make further unlogged lifecycle
     * calls. Process exit closes file handles; it does NOT prove deactivation. */
    error=journal_failed;
    if (!CloseHandle(journal)) result=1;
    return result || error ? 4 : 0;
}
