#ifndef S2AM_CLOCK_PROBE_PROTOCOL_H
#define S2AM_CLOCK_PROBE_PROTOCOL_H
#include <windows.h>
#include <string.h>
#include <wchar.h>

/* FILE_DEVICE_UNKNOWN, function 0x801, METHOD_BUFFERED, FILE_READ_ACCESS.
 * There is no caller-provided address, pass count, operation or write payload. */
#define SCK_IOCTL_SNAPSHOT ((DWORD)0x00226004UL)
#define SCK_MAGIC ((DWORD)0x314b4353UL)
#define SCK_VERSION 1UL
#define SCK_COUNT 64UL
#define SCK_STATUS_COMPLETE 0UL
#define SCK_STATUS_FAILED 1UL
#define SCK_STAGE_LOAD 1UL
#define SCK_STAGE_RESOLVE 2UL
#define SCK_STAGE_TRANSLATE_PLL 3UL
#define SCK_STAGE_MAP_PLL 4UL
#define SCK_STAGE_TRANSLATE_CCM 5UL
#define SCK_STAGE_MAP_CCM 6UL
#define SCK_STAGE_READ 7UL
#define SCK_STAGE_CLEANUP 8UL
#define SCK_STAGE_COMPLETE 9UL
typedef struct { DWORD pass, block, offset, value; } SCK_READING;
typedef struct {
    DWORD magic, version, bytes, status, stage, error, count, reserved;
    SCK_READING reads[SCK_COUNT];
} SCK_SNAPSHOT;
typedef char sck_wire_size_must_be_1056[(sizeof(SCK_SNAPSHOT) == 1056) ? 1 : -1];

static const DWORD sck_pll_offsets[] = {0, 4, 8, 12, 16, 28, 32, 36, 40, 44};
static const DWORD sck_ccm_offsets[] = {0, 8, 12, 16, 20, 24, 28, 32, 72, 76, 84};
static const DWORD sck_user_mode = 0x10, sck_internal = 0, sck_bus = 0;
static const WCHAR sck_mem_base[] = L"83f80000\00073fd4000\000";
static const WCHAR sck_mem_len[] = L"30\00058\000";
typedef struct { LPCWSTR name; DWORD type; const void *data; DWORD size; } SCK_REG_VALUE;
/* The DLL path is supplied separately, and is the only variable value. */
static const SCK_REG_VALUE sck_values[] = {
    {L"Dll", REG_SZ, NULL, 0},
    {L"Prefix", REG_SZ, L"SCK", 4 * sizeof(WCHAR)},
    {L"Flags", REG_DWORD, &sck_user_mode, sizeof(DWORD)},
    {L"InterfaceType", REG_DWORD, &sck_internal, sizeof(DWORD)},
    {L"BusNumber", REG_DWORD, &sck_bus, sizeof(DWORD)},
    {L"MemBase", REG_MULTI_SZ, sck_mem_base, sizeof(sck_mem_base)},
    {L"MemLen", REG_MULTI_SZ, sck_mem_len, sizeof(sck_mem_len)}
};
#define SCK_VALUE_COUNT (sizeof(sck_values) / sizeof(sck_values[0]))

/* Shared exact registry contract. Reject surplus values and any subkey, not
 * merely a known subset: Context/Index/UserProcGroup/IO/IRQ values must be absent. */
static __inline int sck_verify_key(HKEY key, LPCWSTR dll)
{
    unsigned int i;
    WCHAR name[32];
    BYTE data[MAX_PATH * sizeof(WCHAR)];
    DWORD type, size, chars;
    for (i = 0; i < SCK_VALUE_COUNT; ++i) {
        const void *expected = i ? sck_values[i].data : dll;
        DWORD expected_size = i ? sck_values[i].size : (DWORD)(wcslen(dll) + 1) * sizeof(WCHAR);
        size = sizeof(data);
        if (expected_size > size ||
            RegQueryValueExW(key, sck_values[i].name, NULL, &type, data, &size) != ERROR_SUCCESS ||
            type != sck_values[i].type || size != expected_size || memcmp(data, expected, size))
            return 0;
    }
    for (i = 0; i < SCK_VALUE_COUNT; ++i) {
        unsigned int j;
        chars = sizeof(name) / sizeof(name[0]);
        memset(name, 0, sizeof(name));
        if (RegEnumValueW(key, i, name, &chars, NULL, NULL, NULL, NULL) != ERROR_SUCCESS ||
            chars >= sizeof(name) / sizeof(name[0]) || name[chars])
            return 0;
        for (j = 0; j < SCK_VALUE_COUNT && wcscmp(name, sck_values[j].name); ++j) { }
        if (j == SCK_VALUE_COUNT) return 0;
    }
    chars = sizeof(name) / sizeof(name[0]);
    if (RegEnumValueW(key, SCK_VALUE_COUNT, name, &chars, NULL, NULL, NULL, NULL) != ERROR_NO_MORE_ITEMS)
        return 0;
    chars = sizeof(name) / sizeof(name[0]);
    return RegEnumKeyExW(key, 0, name, &chars, NULL, NULL, NULL, NULL) == ERROR_NO_MORE_ITEMS;
}
#endif
