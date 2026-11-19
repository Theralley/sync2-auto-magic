/* Paired user-mode timing observations. This is not a CPU frequency meter. */
#include <windows.h>

typedef unsigned long long U64;

static int same_path(const WCHAR *a, const WCHAR *b)
{
    while (*a && *b) {
        WCHAR x = *a++, y = *b++;
        if (x >= L'a' && x <= L'z') x -= L'a' - L'A';
        if (y >= L'a' && y <= L'z') y -= L'a' - L'A';
        if (x != y) return 0;
    }
    return *a == *b;
}

/* Small fixed-format records. A short write or flush error ends the run. */
static int record(HANDLE f, const char *prefix, const U64 *fields, unsigned n)
{
    static const U64 powers[] = {
        10000000000000000000ULL,1000000000000000000ULL,100000000000000000ULL,
        10000000000000000ULL,1000000000000000ULL,100000000000000ULL,
        10000000000000ULL,1000000000000ULL,100000000000ULL,10000000000ULL,
        1000000000ULL,100000000ULL,10000000ULL,1000000ULL,100000ULL,
        10000ULL,1000ULL,100ULL,10ULL,1ULL
    };
    char row[144], *p = row;
    DWORD size, written = 0;
    unsigned i, j;
    while (*prefix) *p++ = *prefix++;
    for (i = 0; i < n; ++i) {
        U64 v = fields[i];
        int started = 0;
        *p++ = ',';
        for (j = 0; j < sizeof(powers)/sizeof(powers[0]); ++j) {
            char digit = '0';
            while (v >= powers[j]) { v -= powers[j]; ++digit; }
            if (started || digit != '0' || powers[j] == 1) {
                *p++ = digit;
                started = 1;
            }
        }
    }
    *p++ = '\r'; *p++ = '\n';
    size = (DWORD)(p - row);
    return WriteFile(f, row, size, &written, NULL) && written == size &&
           FlushFileBuffers(f);
}

#define A1 "add %[v], %[v], #1\n\t"
#define A2 A1 A1
#define A4 A2 A2
#define A8 A4 A4
#define A16 A8 A8
#define A32 A16 A16
#define KERNEL(body) __asm__ volatile("1:\n\t" body \
    "subs %[n], %[n], #1\n\tbne 1b" \
    : [v] "+&r" (v), [n] "+&r" (rounds) : : "cc", "memory")

static DWORD kernel(DWORD rounds, DWORD width)
{
#ifdef S2AM_PAIR_HOST_TEST
    /* Test only: the real timing kernel is ARM assembly. */
    return rounds * width;
#else
    DWORD v = 0;
    if (width == 32) { KERNEL(A32); }
    else { KERNEL(A32 A32); }
    return v;
#endif
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR cmd, int show)
{
    WCHAR path[MAX_PATH];
    const WCHAR *dest, *scratch;
    HANDLE f;
    LARGE_INTEGER rate, before, after;
    U64 fields[6], last = 0;
    DWORD block, slot, start, len;
    int rc = 1;
    (void)instance; (void)previous; (void)show;
    if (cmd && *cmd) return 1;
    len = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (!len || len >= MAX_PATH) return 1;
    path[len] = 0;
    if (same_path(path, L"\\USB Disk\\S2AM-PAIR\\S2AMPAIR.EXE")) {
        dest = L"\\USB Disk\\S2AM-PAIR\\RESULT.CSV";
        scratch = L"\\USB Disk\\S2AM-PAIR\\RESULT.TMP";
    } else if (same_path(path, L"\\USB Disk2\\S2AM-PAIR\\S2AMPAIR.EXE")) {
        dest = L"\\USB Disk2\\S2AM-PAIR\\RESULT.CSV";
        scratch = L"\\USB Disk2\\S2AM-PAIR\\RESULT.TMP";
    } else return 1;
    if (!QueryPerformanceFrequency(&rate) || rate.QuadPart <= 0) return 1;
    start = GetTickCount();
    if (GetFileAttributesW(dest) != (DWORD)-1 || GetLastError() != ERROR_FILE_NOT_FOUND) return 1;
    f = CreateFileW(scratch, GENERIC_WRITE, 0, NULL, CREATE_NEW,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return 1;
    fields[0] = 1;
    if (!record(f, "S2AM-PAIR", fields, 1)) goto done;
    fields[0] = (U64)rate.QuadPart;
    if (!record(f, "qpf", fields, 1)) goto done;
    for (block = 0; block < 8; ++block) {
        DWORD rounds = block < 4 ? 16384 : 32768;
        if (block) Sleep(1);
        for (slot = 0; slot < 4; ++slot) {
            DWORD v, inner = slot == 1 || slot == 2;
            DWORD width = (inner ^ (block & 1)) ? 64 : 32;
            if ((DWORD)(GetTickCount() - start) >= 15000 ||
                !QueryPerformanceCounter(&before) || before.QuadPart <= 0 ||
                (U64)before.QuadPart < last) goto done;
            v = kernel(rounds, width);
            if (!QueryPerformanceCounter(&after) || after.QuadPart <= before.QuadPart ||
                v != rounds * width || (DWORD)(GetTickCount() - start) >= 15000) goto done;
            fields[0] = block; fields[1] = slot; fields[2] = rounds; fields[3] = width;
            fields[4] = (U64)before.QuadPart; fields[5] = last = (U64)after.QuadPart;
            if (!record(f, "sample", fields, 6)) goto done;
        }
    }
    fields[0] = 32;
    if ((DWORD)(GetTickCount() - start) < 15000 && record(f, "complete", fields, 1)) rc = 0;
done:
    if (!CloseHandle(f)) rc = 1;
    if (!rc && !MoveFileW(scratch, dest)) rc = 1;
    return rc;
}
