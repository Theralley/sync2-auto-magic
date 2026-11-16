/*
 * Fixed, read-only i.MX51 clock snapshot. Usage: s2amclock.exe <output filename>.
 * Ordinary CE application; load only installed \Windows\ceddk.dll. No physical
 * address argument, register write, IOCTL, driver install or alternate loader.
 * MmMapIoSpace itself creates writable mappings; this application only loads
 * DWORDs. Mapping permission, module identity and hardware access are unverified
 * on the car. A child-process timeout cannot interrupt a stalled MMIO access.
 *
 * ABI (PHYSICAL_ADDRESS is LARGE_INTEGER, passed by value):
 * https://learn.microsoft.com/en-us/previous-versions/windows/embedded/aa447863(v=msdn.10)
 * Physical bases and fixed register offsets (Freescale-authored definitions):
 * https://github.com/torvalds/linux/blob/v3.0/arch/arm/plat-mxc/include/mach/mx51.h
 * https://github.com/torvalds/linux/blob/v3.0/arch/arm/mach-mx5/crm_regs.h
 * Candidate user ceddk.dll: MmMapIoSpace RVA 0x3d60; MmUnmapIoSpace 0x3e28.
 *
 * CRLF protocol, unsigned decimal numbers, no frequency claims:
 * S|s2am-clock-v1
 * B|load / B|resolve|export / B|map|block
 * B|read|pass|block|offset       (flushed BEFORE the volatile load)
 * R|pass|block|offset|value
 * B|unmap|block / B|free-library
 * E|stage|system-error          (zero is possible and is still failure)
 * T|complete                   (only after reads and mapping/DLL cleanup)
 *
 * Two passes, numbered 1 and 2. Each reads ccm-before (11 offsets), pll1
 * (10 offsets), ccm-after (same 11): exactly 64 R records, in that order.
 * The host must validate recordset, brackets/stability AND child exit status 0.
 * T alone cannot prove final FlushFileBuffers/CloseHandle succeeded: those
 * failures return nonzero even if completion bytes reached the file.
 * A write/flush failure stops all further sampling and manual library cleanup;
 * process exit releases resources without making another unlogged library call.
 */
#include <windows.h>
#include <string.h>
#include <wchar.h>

typedef LPVOID (WINAPI *MapIo)(LARGE_INTEGER, ULONG, BYTE);
typedef void (WINAPI *UnmapIo)(LPVOID, ULONG);

static const DWORD pll_offsets[] = {0, 4, 8, 12, 16, 28, 32, 36, 40, 44};
static const DWORD ccm_offsets[] = {0, 8, 12, 16, 20, 24, 28, 32, 72, 76, 84};
static HANDLE output = INVALID_HANDLE_VALUE;
static int output_failed;

static void put(const char *text)
{
    DWORD remaining = (DWORD)strlen(text);
    while (remaining && !output_failed) {
        DWORD written = 0;
        if (!WriteFile(output, text, remaining, &written, NULL) ||
            !written || written > remaining) {
            output_failed = 1;
            break;
        }
        text += written;
        remaining -= written;
    }
}

static void number(DWORD value)
{
    char text[11];
    unsigned int i = sizeof(text) - 1;
    text[i] = '\0';
    do {
        text[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value && i);
    put(text + i);
}

static int end_line(void)
{
    put("\r\n");
    if (!output_failed && !FlushFileBuffers(output))
        output_failed = 1;
    return !output_failed;
}

static int progress(const char *stage)
{
    put("B|");
    put(stage);
    return end_line();
}

static void failure(const char *stage, DWORD error)
{
    put("E|");
    put(stage);
    put("|");
    number(error);
    end_line();
}

static void position(DWORD pass, const char *block, DWORD offset)
{
    number(pass);
    put("|");
    put(block);
    put("|");
    number(offset);
}

static int sample(LPVOID mapping, DWORD pass, const char *block,
                  const DWORD *offsets, unsigned int count)
{
    unsigned int i;
    for (i = 0; i < count; ++i) {
        DWORD value;
        put("B|read|");
        position(pass, block, offsets[i]);
        if (!end_line())
            return 0;
        value = *(volatile const DWORD *)((const BYTE *)mapping + offsets[i]);
        put("R|");
        position(pass, block, offsets[i]);
        put("|");
        number(value);
        if (!end_line())
            return 0;
    }
    return 1;
}

static int output_path(LPCWSTR command, WCHAR path[MAX_PATH])
{
    unsigned int n = 0;
    int quoted;
    while (*command == L' ' || *command == L'\t')
        ++command;
    quoted = *command == L'"';
    if (quoted)
        ++command;
    while (*command && (quoted ? *command != L'"' : (*command != L' ' && *command != L'\t'))) {
        if (n + 1 >= MAX_PATH || *command < L' ' || *command == L'"')
            return 0;
        path[n++] = *command++;
    }
    if (quoted && *command++ != L'"')
        return 0;
    while (*command == L' ' || *command == L'\t')
        ++command;
    path[n] = L'\0';
    return !*command && n > 1 && path[0] == L'\\' && path[n - 1] != L'\\';
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR path[MAX_PATH];
    HMODULE library = NULL;
    MapIo map = NULL;
    UnmapIo unmap = NULL;
    LPVOID pll = NULL, ccm = NULL;
    LARGE_INTEGER physical;
    DWORD pass;
    int result = 1;
    (void)instance;
    (void)previous;
    (void)show;

    if (!command || !output_path(command, path))
        return 1;
    output = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW,
                         FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE)
        return 2;
    put("S|s2am-clock-v1");
    if (!end_line() || !progress("load"))
        goto finish;
    SetLastError(0);
    library = LoadLibraryW(L"\\Windows\\ceddk.dll");
    if (!library) {
        failure("load", GetLastError());
        goto cleanup;
    }
    if (!progress("resolve|MmMapIoSpace"))
        goto finish;
    SetLastError(0);
    map = (MapIo)(void *)GetProcAddress(library, L"MmMapIoSpace");
    if (!map) {
        failure("resolve-map", GetLastError());
        goto cleanup;
    }
    if (!progress("resolve|MmUnmapIoSpace"))
        goto finish;
    SetLastError(0);
    unmap = (UnmapIo)(void *)GetProcAddress(library, L"MmUnmapIoSpace");
    if (!unmap) {
        failure("resolve-unmap", GetLastError());
        goto cleanup;
    }
    if (!progress("map|pll1"))
        goto finish;
    physical.QuadPart = 0x83f80000ULL;
    SetLastError(0);
    pll = map(physical, 0x30, 0);
    if (!pll) {
        failure("map-pll1", GetLastError());
        goto cleanup;
    }
    if (!progress("map|ccm"))
        goto finish;
    physical.QuadPart = 0x73fd4000ULL;
    SetLastError(0);
    ccm = map(physical, 0x58, 0);
    if (!ccm) {
        failure("map-ccm", GetLastError());
        goto cleanup;
    }
    for (pass = 1; pass <= 2; ++pass) {
        if (!sample(ccm, pass, "ccm-before", ccm_offsets, sizeof(ccm_offsets) / sizeof(ccm_offsets[0])) ||
            !sample(pll, pass, "pll1", pll_offsets, sizeof(pll_offsets) / sizeof(pll_offsets[0])) ||
            !sample(ccm, pass, "ccm-after", ccm_offsets, sizeof(ccm_offsets) / sizeof(ccm_offsets[0])))
            goto finish;
    }
    result = 0;

cleanup:
    if (output_failed)
        goto finish;
    if (ccm) {
        if (!progress("unmap|ccm"))
            goto finish;
        unmap(ccm, 0x58);
    }
    if (pll) {
        if (!progress("unmap|pll1"))
            goto finish;
        unmap(pll, 0x30);
    }
    if (library) {
        if (!progress("free-library"))
            goto finish;
        SetLastError(0);
        if (!FreeLibrary(library)) {
            failure("free-library", GetLastError());
            result = 1;
        }
    }
    if (!result && !output_failed) {
        put("T|complete");
        end_line();
    }
finish:
    if (!CloseHandle(output))
        result = 1;
    return result || output_failed ? 3 : 0;
}
