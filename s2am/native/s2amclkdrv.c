/* Experimental CE 6 USER-mode stream driver. No boot key, IRQ, kernel loader,
 * clock/voltage change, MMIO stores, or arbitrary-address interface.
 * Init/Open perform no mapping or hardware access. One lifetime, one open.
 * PreClose/PreDeinit invalidate without waiting; only the IOControl owner
 * touches mappings. A stuck MMIO load cannot be cancelled by these flags. */
#ifndef _WIN32_WCE
#define _WIN32_WCE 0x0600
#endif
#include <windows.h>
#include <devload.h>
#include "clock_probe_protocol.h"

/* CeGCC's import library has this CE API; its old devload.h omits the declaration. */
extern HKEY WINAPI OpenDeviceKey(LPCWSTR active_key);

typedef BOOL (WINAPI *TranslateBus)(int, ULONG, LARGE_INTEGER, ULONG *, LARGE_INTEGER *);
typedef LPVOID (WINAPI *MapIo)(LARGE_INTEGER, ULONG, BYTE);
typedef void (WINAPI *UnmapIo)(LPVOID, ULONG);
#define DEVICE_CONTEXT 0x53434b01UL
#define OPEN_CONTEXT 0x53434b02UL
static HMODULE own_module;
/* Device: 0 unused, 1 live, 2 invalidated, 3 initializing.
 * Open: 0 unused, 1 live, 2 invalidated. Never recycle an open context. */
static volatile LONG device_state, open_state, busy;

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) own_module = module;
    return TRUE;
}

static LONG state(volatile LONG *value) { return InterlockedCompareExchange(value, 0, 0); }
static int live(void) { return state(&device_state) == 1 && state(&open_state) == 1; }
static BOOL denied(DWORD error) { SetLastError(error); return FALSE; }

DWORD WINAPI SCK_Init(LPCWSTR active_key, DWORD context)
{
    HKEY key;
    WCHAR dll[MAX_PATH];
    DWORD length;
    int valid;
    if (!active_key || context || InterlockedCompareExchange(&device_state, 3, 0) != 0)
        return denied(ERROR_INVALID_PARAMETER);
    length = GetModuleFileNameW(own_module, dll, MAX_PATH);
    if (!length || length >= MAX_PATH || dll[0] != L'\\') goto fail;
    key = OpenDeviceKey(active_key);
    if (!key || key == (HKEY)INVALID_HANDLE_VALUE) goto fail;
    valid = sck_verify_key(key, dll);
    if (RegCloseKey(key) != ERROR_SUCCESS) valid = 0;
    if (!valid) goto fail;
    InterlockedExchange(&device_state, 1);
    return DEVICE_CONTEXT;
fail:
    InterlockedExchange(&device_state, 2);
    return denied(ERROR_INVALID_PARAMETER);
}

DWORD WINAPI SCK_Open(DWORD context, DWORD access, DWORD share)
{
    if (context != DEVICE_CONTEXT || access != GENERIC_READ || share || state(&device_state) != 1)
        return denied(ERROR_ACCESS_DENIED);
    if (InterlockedCompareExchange(&open_state, 1, 0) != 0) return denied(ERROR_BUSY);
    if (state(&device_state) != 1) {
        InterlockedExchange(&open_state, 2);
        return denied(ERROR_INVALID_HANDLE);
    }
    return OPEN_CONTEXT;
}

BOOL WINAPI SCK_PreClose(DWORD context)
{
    if (context != OPEN_CONTEXT || !state(&open_state)) return denied(ERROR_INVALID_HANDLE);
    InterlockedExchange(&open_state, 2);
    return TRUE;
}

BOOL WINAPI SCK_Close(DWORD context)
{
    if (!SCK_PreClose(context)) return FALSE;
    return state(&busy) ? denied(ERROR_BUSY) : TRUE;
}

BOOL WINAPI SCK_PreDeinit(DWORD context)
{
    if (context != DEVICE_CONTEXT || !state(&device_state)) return denied(ERROR_INVALID_HANDLE);
    InterlockedExchange(&device_state, 2);
    return TRUE;
}

BOOL WINAPI SCK_Deinit(DWORD context)
{
    if (!SCK_PreDeinit(context)) return FALSE;
    return state(&busy) ? denied(ERROR_BUSY) : TRUE;
}

static int sample(SCK_SNAPSHOT *out, LPVOID mapping, DWORD pass, DWORD block,
                  const DWORD *offsets, unsigned int count)
{
    unsigned int i;
    for (i = 0; i < count; ++i) {
        SCK_READING *reading;
        if (!live()) { out->error = ERROR_OPERATION_ABORTED; return 0; }
        reading = &out->reads[out->count];
        reading->pass = pass; reading->block = block; reading->offset = offsets[i];
        reading->value = *(volatile const DWORD *)((const BYTE *)mapping + offsets[i]);
        ++out->count;
    }
    return 1;
}

static LPVOID fixed_map(TranslateBus translate, MapIo map, DWORD address, DWORD length,
                        DWORD translate_stage, DWORD map_stage, SCK_SNAPSHOT *out)
{
    LARGE_INTEGER bus_address, physical;
    ULONG space = 0;
    LPVOID mapping;
    if (!live()) { out->error = ERROR_OPERATION_ABORTED; return NULL; }
    bus_address.QuadPart = address; physical.QuadPart = 0;
    out->stage = translate_stage;
    SetLastError(0);
    if (!translate(0 /* Internal */, 0, bus_address, &space, &physical)) {
        out->error = GetLastError(); return NULL;
    }
    if (space != 0 || physical.QuadPart != bus_address.QuadPart) {
        out->error = ERROR_INVALID_PARAMETER; return NULL;
    }
    if (!live()) { out->error = ERROR_OPERATION_ABORTED; return NULL; }
    out->stage = map_stage;
    SetLastError(0);
    mapping = map(physical, length, 0);
    if (!mapping) out->error = GetLastError();
    return mapping;
}

static void snapshot(SCK_SNAPSHOT *out)
{
    HMODULE library;
    TranslateBus translate = NULL;
    MapIo map = NULL;
    UnmapIo unmap = NULL;
    LPVOID pll = NULL, ccm = NULL;
    DWORD pass;
    memset(out, 0, sizeof(*out));
    out->magic = SCK_MAGIC; out->version = SCK_VERSION; out->bytes = sizeof(*out);
    out->status = SCK_STATUS_FAILED; out->stage = SCK_STAGE_LOAD;
    SetLastError(0);
    library = LoadLibraryW(L"\\Windows\\ceddk.dll");
    if (!library) { out->error = GetLastError(); return; }
    out->stage = SCK_STAGE_RESOLVE;
    SetLastError(0);
    translate = (TranslateBus)(void *)GetProcAddress(library, L"HalTranslateBusAddress");
    map = (MapIo)(void *)GetProcAddress(library, L"MmMapIoSpace");
    unmap = (UnmapIo)(void *)GetProcAddress(library, L"MmUnmapIoSpace");
    if (!translate || !map || !unmap) { out->error = GetLastError(); goto cleanup; }
    pll = fixed_map(translate, map, 0x83f80000UL, 0x30, SCK_STAGE_TRANSLATE_PLL, SCK_STAGE_MAP_PLL, out);
    if (!pll) goto cleanup;
    ccm = fixed_map(translate, map, 0x73fd4000UL, 0x58, SCK_STAGE_TRANSLATE_CCM, SCK_STAGE_MAP_CCM, out);
    if (!ccm) goto cleanup;
    out->stage = SCK_STAGE_READ;
    for (pass = 1; pass <= 2; ++pass) {
        if (!sample(out, ccm, pass, 1, sck_ccm_offsets, 11) ||
            !sample(out, pll, pass, 2, sck_pll_offsets, 10) ||
            !sample(out, ccm, pass, 3, sck_ccm_offsets, 11)) goto cleanup;
    }
    if (!live()) { out->error = ERROR_OPERATION_ABORTED; goto cleanup; }
    out->status = SCK_STATUS_COMPLETE;
cleanup:
    if (ccm) unmap(ccm, 0x58);
    if (pll) unmap(pll, 0x30);
    SetLastError(0);
    if (!FreeLibrary(library)) {
        out->status = SCK_STATUS_FAILED; out->stage = SCK_STAGE_CLEANUP; out->error = GetLastError();
    }
    if (out->status == SCK_STATUS_COMPLETE) out->stage = SCK_STAGE_COMPLETE;
}

BOOL WINAPI SCK_IOControl(DWORD context, DWORD code, BYTE *input, DWORD input_size,
                          BYTE *output, DWORD output_size, DWORD *returned)
{
    SCK_SNAPSHOT result;
    if (returned) *returned = 0;
    if (code != SCK_IOCTL_SNAPSHOT) return denied(ERROR_NOT_SUPPORTED);
    if (input || input_size || !output || output_size != sizeof(result) || !returned)
        return denied(ERROR_INVALID_PARAMETER);
    if (context != OPEN_CONTEXT || !live()) return denied(ERROR_INVALID_HANDLE);
    if (InterlockedCompareExchange(&busy, 1, 0) != 0) return denied(ERROR_BUSY);
    if (!live()) { InterlockedExchange(&busy, 0); return denied(ERROR_INVALID_HANDLE); }
    snapshot(&result);
    /* METHOD_BUFFERED/CE user-driver marshaling owns these caller buffers.
     * No output pointer is retained and no nested pointer crosses the boundary. */
    memcpy(output, &result, sizeof(result));
    *returned = sizeof(result);
    InterlockedExchange(&busy, 0);
    return TRUE; /* The record reports sampling failure separately from transport. */
}

DWORD WINAPI SCK_Read(DWORD context, LPVOID buffer, DWORD size)
{
    (void)context; (void)buffer; (void)size; SetLastError(ERROR_NOT_SUPPORTED); return (DWORD)-1;
}
DWORD WINAPI SCK_Write(DWORD context, LPCVOID buffer, DWORD size)
{
    (void)context; (void)buffer; (void)size; SetLastError(ERROR_NOT_SUPPORTED); return (DWORD)-1;
}
DWORD WINAPI SCK_Seek(DWORD context, LONG offset, DWORD type)
{
    (void)context; (void)offset; (void)type; SetLastError(ERROR_NOT_SUPPORTED); return (DWORD)-1;
}
