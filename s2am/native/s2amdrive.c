/*
 * s2am drive: records what a redesign of SYNC 2's screens needs, while you drive.
 * Usage: s2amdrive.exe <seconds> <output folder>
 *
 * At the start it writes the system's facts to drive.log: CE version, memory, screen,
 * and every root folder with its free space. A thread of its own then lists every file
 * on SYNC (files.txt) and copies Ford's screens, \8inchSkins, to <folder>\skins, with
 * the size and SHA-256 of each file (skins.txt). Every 10 s it logs how busy the
 * processor is, the free memory, and the programs that used the processor most. Every
 * second it copies the screen; a picture that has changed and then held still for a
 * second (or every 30 s while it keeps changing, like a moving map) is saved as a BMP
 * in <folder>\screens.
 *
 * It only reads from the car: everything it writes goes to the stick. Its threads run
 * below normal priority, so SYNC's own work always comes first. It stops after
 * <seconds>, or when the stick is gone. It runs next to s2amwatch.exe, as a program of
 * its own, so a failure here cannot cost the watcher's log.
 *
 * Line format: <hh:mm:ss.mmm>|<event>|<details>
 * Only COREDLL is imported. toolhelp.dll and the processor-time calls are looked up at
 * run time, so one that is missing costs that measurement, not the program.
 */
#include <windows.h>
#include <string.h>

#define TICK_MS 1000
#define LOAD_EVERY_MS 10000
#define HEARTBEAT_MS 60000
#define SHOT_EVERY_MS 30000
#define MAX_SHOTS 3000
#define MAX_LINES 400000
#define DUMP_RESERVE_MB 600  /* the copy of the screens leaves this much for screenshots */
#define SHOT_RESERVE_MB 150
#define DUMP_LIMIT (1536UL * 1024 * 1024)
#define MAX_DEPTH 16
#define MAX_PROCS 160
#define TOP 5
#define LOG_LIMIT (8 * 1024 * 1024)
#define SKINS L"\\8inchSkins"
#define TH32CS_SNAPPROCESS 0x00000002
#define TH32CS_SNAPTHREAD 0x00000004
#define TH32CS_SNAPNOHEAPS 0x40000000
#define QUERY_THREAD 0x0040
#ifndef SPI_GETPLATFORMTYPE
#define SPI_GETPLATFORMTYPE 257
#endif
#ifndef SPI_GETOEMINFO
#define SPI_GETOEMINFO 258
#endif

/* pure: begin. Everything up to "pure: end" uses only C, BYTE, DWORD and BOOL, so the tests
 * build it on the Mac. */

/* ---- SHA-256 (FIPS 180-4) ---- */

typedef struct {
    DWORD state[8], bytes_low, bytes_high, fill;
    BYTE block[64];
} Sha256;

static const DWORD sha_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha256_block(Sha256 *sha, const BYTE *p)
{
    DWORD w[64], v[8], t1, t2;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (DWORD)p[4 * i] << 24 | (DWORD)p[4 * i + 1] << 16 | (DWORD)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3)) + w[i - 7] +
               (ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10));
    for (i = 0; i < 8; i++)
        v[i] = sha->state[i];
    for (i = 0; i < 64; i++) {
        t1 = v[7] + (ROR(v[4], 6) ^ ROR(v[4], 11) ^ ROR(v[4], 25)) + ((v[4] & v[5]) ^ (~v[4] & v[6])) +
             sha_k[i] + w[i];
        t2 = (ROR(v[0], 2) ^ ROR(v[0], 13) ^ ROR(v[0], 22)) + ((v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]));
        v[7] = v[6];
        v[6] = v[5];
        v[5] = v[4];
        v[4] = v[3] + t1;
        v[3] = v[2];
        v[2] = v[1];
        v[1] = v[0];
        v[0] = t1 + t2;
    }
    for (i = 0; i < 8; i++)
        sha->state[i] += v[i];
}

static void sha256_init(Sha256 *sha)
{
    static const DWORD start[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(sha->state, start, sizeof(start));
    sha->bytes_low = sha->bytes_high = sha->fill = 0;
}

static void sha256_update(Sha256 *sha, const BYTE *data, DWORD length)
{
    DWORD before = sha->bytes_low;
    sha->bytes_low += length;
    if (sha->bytes_low < before)
        sha->bytes_high++;
    if (sha->fill) {
        while (length && sha->fill < 64) {
            sha->block[sha->fill++] = *data++;
            length--;
        }
        if (sha->fill < 64)
            return;
        sha256_block(sha, sha->block);
        sha->fill = 0;
    }
    for (; length >= 64; data += 64, length -= 64)
        sha256_block(sha, data);
    while (length--)
        sha->block[sha->fill++] = *data++;
}

static void sha256_final(Sha256 *sha, BYTE digest[32])
{
    DWORD high = sha->bytes_high << 3 | sha->bytes_low >> 29, low = sha->bytes_low << 3;
    int i;
    sha->block[sha->fill++] = 0x80;
    if (sha->fill > 56) {
        while (sha->fill < 64)
            sha->block[sha->fill++] = 0;
        sha256_block(sha, sha->block);
        sha->fill = 0;
    }
    while (sha->fill < 56)
        sha->block[sha->fill++] = 0;
    for (i = 0; i < 4; i++) {
        sha->block[56 + i] = (BYTE)(high >> (24 - 8 * i));
        sha->block[60 + i] = (BYTE)(low >> (24 - 8 * i));
    }
    sha256_block(sha, sha->block);
    for (i = 0; i < 32; i++)
        digest[i] = (BYTE)(sha->state[i / 4] >> (24 - 8 * (i % 4)));
}

/* ---- screenshots ---- */

/* A cheap fingerprint of a 24-bit bottom-up picture: every 4th pixel of every 4th row.
 * *black says whether all of those pixels were black. */
static DWORD frame_hash(const BYTE *bits, int width, int height, int stride, BOOL *black)
{
    DWORD hash = 2166136261u;
    int x, y;
    *black = TRUE;
    for (y = 0; y < height; y += 4)
        for (x = 0; x < width; x += 4) {
            const BYTE *p = bits + y * stride + x * 3;
            DWORD value = p[0] | (DWORD)p[1] << 8 | (DWORD)p[2] << 16;
            if (value)
                *black = FALSE;
            hash = (hash ^ value) * 16777619u;
        }
    return hash;
}

/* Whether to save this picture: never twice the same one; otherwise the first one, one
 * that held still since the last look, or one that kept changing for SHOT_EVERY_MS. */
static BOOL want_shot(DWORD hash, DWORD previous, DWORD saved, BOOL any_saved, DWORD since_saved)
{
    if (!any_saved)
        return TRUE;
    if (hash == saved)
        return FALSE;
    return hash == previous || since_saved >= SHOT_EVERY_MS;
}

static void put_le(BYTE *at, DWORD value, int bytes)
{
    while (bytes-- > 0) {
        *at++ = (BYTE)value;
        value >>= 8;
    }
}

/* The 54-byte header of a 24-bit bottom-up BMP. */
static void bmp_header(BYTE header[54], int width, int height, int stride)
{
    DWORD image = (DWORD)stride * (DWORD)height;
    memset(header, 0, 54);
    header[0] = 'B';
    header[1] = 'M';
    put_le(header + 2, 54 + image, 4);
    put_le(header + 10, 54, 4);
    put_le(header + 14, 40, 4);
    put_le(header + 18, (DWORD)width, 4);
    put_le(header + 22, (DWORD)height, 4);
    put_le(header + 26, 1, 2);
    put_le(header + 28, 24, 2);
    put_le(header + 34, image, 4);
}

/* pure: end */

/* ---- toolhelp and processor time, looked up at run time ---- */

typedef struct {
    DWORD dwSize, cntUsage, th32ProcessID, th32DefaultHeapID, th32ModuleID, cntThreads;
    DWORD th32ParentProcessID;
    LONG pcPriClassBase;
    DWORD dwFlags;
    WCHAR szExeFile[MAX_PATH];
    DWORD th32MemoryBase, th32AccessKey;
} ProcessEntry;

typedef struct {
    DWORD dwSize, cntUsage, th32ThreadID, th32OwnerProcessID;
    LONG tpBasePri, tpDeltaPri;
    DWORD dwFlags, th32AccessKey, th32CurrentProcessID;
} ThreadEntry;

typedef HANDLE (WINAPI *SnapshotFn)(DWORD, DWORD);
typedef BOOL (WINAPI *ProcessFn)(HANDLE, ProcessEntry *);
typedef BOOL (WINAPI *ThreadFn)(HANDLE, ThreadEntry *);
typedef BOOL (WINAPI *CloseSnapshotFn)(HANDLE);
typedef DWORD (WINAPI *IdleTimeFn)(void);
typedef HANDLE (WINAPI *OpenThreadFn)(DWORD, BOOL, DWORD);
typedef BOOL (WINAPI *ThreadTimesFn)(HANDLE, FILETIME *, FILETIME *, FILETIME *, FILETIME *);

static SnapshotFn snapshot;
static ProcessFn first_process, next_process;
static ThreadFn first_thread, next_thread;
static CloseSnapshotFn close_snapshot;
static IdleTimeFn idle_time;
static OpenThreadFn open_thread;
static ThreadTimesFn thread_times;

/* via void (*)(void): GCC's sanctioned way to cast between function types */
#define LOOKUP(module, type, name) ((type)(void (*)(void))GetProcAddressW(module, name))

static void load_functions(void)
{
    HMODULE toolhelp = LoadLibraryW(L"toolhelp.dll"), core = GetModuleHandleW(L"coredll.dll");
    if (toolhelp) {
        snapshot = LOOKUP(toolhelp, SnapshotFn, L"CreateToolhelp32Snapshot");
        first_process = LOOKUP(toolhelp, ProcessFn, L"Process32First");
        next_process = LOOKUP(toolhelp, ProcessFn, L"Process32Next");
        first_thread = LOOKUP(toolhelp, ThreadFn, L"Thread32First");
        next_thread = LOOKUP(toolhelp, ThreadFn, L"Thread32Next");
        close_snapshot = LOOKUP(toolhelp, CloseSnapshotFn, L"CloseToolhelp32Snapshot");
    }
    if (core) {
        idle_time = LOOKUP(core, IdleTimeFn, L"GetIdleTime");
        open_thread = LOOKUP(core, OpenThreadFn, L"OpenThread");
        thread_times = LOOKUP(core, ThreadTimesFn, L"GetThreadTimes");
    }
}

/* ---- drive.log, written by the main thread only ---- */

static WCHAR folder[MAX_PATH], log_path[MAX_PATH];
static char buffer[8192];
static int used, write_failures;
static BOOL full, skipping;

static void put(const char *text)
{
    if (skipping)
        return;
    while (*text && used < (int)sizeof(buffer) - 1)
        buffer[used++] = *text++;
}

static void put_uint(unsigned long value)
{
    char digits[12];
    int i = 11;
    digits[i] = '\0';
    do {
        digits[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0 && i > 0);
    put(digits + i);
}

static void put_hex(unsigned long value)
{
    static const char hex[] = "0123456789abcdef";
    char digits[9];
    int i;
    for (i = 7; i >= 0; i--) {
        digits[i] = hex[value & 15];
        value >>= 4;
    }
    digits[8] = '\0';
    put(digits);
}

static void put_wide(const WCHAR *text, int limit)
{
    char one[2] = {0, 0};
    while (*text && limit-- > 0) {
        one[0] = (*text < 127 && *text >= 32 && *text != '|') ? (char)*text : '?';
        put(one);
        text++;
    }
}

static void begin(const char *event)
{
    SYSTEMTIME now;
    skipping = full && strncmp(event, "tick|", 5) != 0 && strcmp(event, "end") != 0;
    GetLocalTime(&now);
    if (now.wHour < 10)
        put("0");
    put_uint(now.wHour);
    put(":");
    if (now.wMinute < 10)
        put("0");
    put_uint(now.wMinute);
    put(":");
    if (now.wSecond < 10)
        put("0");
    put_uint(now.wSecond);
    put(".");
    if (now.wMilliseconds < 100)
        put("0");
    if (now.wMilliseconds < 10)
        put("0");
    put_uint(now.wMilliseconds);
    put("|");
    put(event);
}

static void end_line(void)
{
    put("\r\n");
    skipping = FALSE;
}

/* Appends and closes every time, so a power cut loses at most one tick. */
static void flush(void)
{
    DWORD written;
    HANDLE file;
    if (used == 0)
        return;
    file = CreateFileW(log_path, GENERIC_WRITE, FILE_SHARE_READ, NULL, OPEN_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        write_failures++;
        used = 0;
        return;
    }
    write_failures = 0;
    if (!full && GetFileSize(file, NULL) > LOG_LIMIT) {
        full = TRUE;
        used = 0;
        put("log full, only the heartbeat from here\r\n");
    }
    SetFilePointer(file, 0, NULL, FILE_END);
    WriteFile(file, buffer, (DWORD)used, &written, NULL);
    FlushFileBuffers(file);
    CloseHandle(file);
    used = 0;
}

/* <folder><tail>, FALSE if it would not fit */
static BOOL in_folder(WCHAR *target, const WCHAR *tail)
{
    if (wcslen(folder) + wcslen(tail) >= MAX_PATH)
        return FALSE;
    wcscpy(target, folder);
    wcscat(target, tail);
    return TRUE;
}

static DWORD free_mb(const WCHAR *path, DWORD *total_mb)
{
    ULARGE_INTEGER free_bytes, total, total_free;
    if (!GetDiskFreeSpaceExW(path, &free_bytes, &total, &total_free)) {
        if (total_mb)
            *total_mb = 0;
        return 0;
    }
    if (total_mb)
        *total_mb = total.HighPart << 12 | total.LowPart >> 20;
    return free_bytes.HighPart << 12 | free_bytes.LowPart >> 20;
}

/* ---- the system's facts, once ---- */

static void system_facts(void)
{
    OSVERSIONINFOW version;
    MEMORYSTATUS memory;
    WIN32_FIND_DATAW found;
    WCHAR text[256], path[MAX_PATH];  /* 256 characters; we promise 256 bytes, whichever CE reads */
    HANDLE search;
    HDC screen;

    memset(&version, 0, sizeof(version));
    version.dwOSVersionInfoSize = sizeof(version);
    begin("system|ce ");
    if (GetVersionExW(&version)) {
        put_uint(version.dwMajorVersion);
        put(".");
        put_uint(version.dwMinorVersion);
        put(" build ");
        put_uint(version.dwBuildNumber);
    } else {
        put("?");
    }
    if (SystemParametersInfoW(SPI_GETPLATFORMTYPE, sizeof(text) / 2, text, 0)) {
        text[255] = L'\0';
        put("|platform ");
        put_wide(text, 64);
    }
    if (SystemParametersInfoW(SPI_GETOEMINFO, sizeof(text) / 2, text, 0)) {
        text[255] = L'\0';
        put("|oem ");
        put_wide(text, 64);
    }
    end_line();

    memset(&memory, 0, sizeof(memory));
    memory.dwLength = sizeof(memory);
    GlobalMemoryStatus(&memory);
    begin("memory|load ");
    put_uint(memory.dwMemoryLoad);
    put("%|physical ");
    put_uint(memory.dwTotalPhys / 1024);
    put(" KB|free ");
    put_uint(memory.dwAvailPhys / 1024);
    put(" KB");
    end_line();

    begin("screen|");
    put_uint((unsigned long)GetSystemMetrics(SM_CXSCREEN));
    put("x");
    put_uint((unsigned long)GetSystemMetrics(SM_CYSCREEN));
    screen = GetDC(NULL);
    if (screen) {
        put("|bits ");
        put_uint((unsigned long)GetDeviceCaps(screen, BITSPIXEL));
        ReleaseDC(NULL, screen);
    }
    end_line();

    begin("functions|toolhelp ");
    put_uint(snapshot && first_process && next_process && close_snapshot);
    put(" threads ");
    put_uint(first_thread && next_thread);
    put("|GetIdleTime ");
    put_uint(idle_time != NULL);
    put(" OpenThread ");
    put_uint(open_thread != NULL);
    put(" GetThreadTimes ");
    put_uint(thread_times != NULL);
    end_line();

    search = FindFirstFileW(L"\\*", &found);
    if (search == INVALID_HANDLE_VALUE)
        return;
    do {
        DWORD total_mb, available;
        if (!(found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || wcslen(found.cFileName) + 2 >= MAX_PATH)
            continue;
        path[0] = L'\\';
        wcscpy(path + 1, found.cFileName);
        available = free_mb(path, &total_mb);
        begin("root|");
        put_wide(found.cFileName, 60);
        put("|attributes ");
        put_hex(found.dwFileAttributes);
        put("|free ");
        put_uint(available);
        put(" MB of ");
        put_uint(total_mb);
        put(" MB");
        end_line();
    } while (FindNextFileW(search, &found));
    FindClose(search);
}

/* ---- the file list and the copy of Ford's screens, in a thread of their own ---- */

typedef struct {
    HANDLE file;
    char data[8192];
    int used;
    BOOL failed;
} Out;

static Out listing, manifest;
static BYTE chunk[32768];
static volatile BOOL stop_dump, listing_done, dump_done, stick_gone, listing_broken, manifest_broken;
static DWORD room_mb, room_bytes;  /* free space when last asked, and dump_bytes then */
static volatile DWORD listed_lines, dump_files, dump_bytes, dump_errors;
static WCHAR stick_root[MAX_PATH];

static BOOL out_open(Out *out, const WCHAR *path)
{
    out->used = 0;
    out->file = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    out->failed = out->file == INVALID_HANDLE_VALUE;
    return !out->failed;
}

static void out_flush(Out *out)
{
    DWORD written;
    if (!out->failed && out->used &&
        (!WriteFile(out->file, out->data, (DWORD)out->used, &written, NULL) || written != (DWORD)out->used))
        out->failed = TRUE;
    out->used = 0;
}

static void out_text(Out *out, const char *text)
{
    for (; *text; text++) {
        if (out->used == (int)sizeof(out->data))
            out_flush(out);
        out->data[out->used++] = *text;
    }
}

static void out_uint(Out *out, unsigned long value)
{
    char digits[12];
    int i = 11;
    digits[i] = '\0';
    do {
        digits[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value != 0 && i > 0);
    out_text(out, digits + i);
}

static void out_wide(Out *out, const WCHAR *text)
{
    char one[2] = {0, 0};
    for (; *text; text++) {
        one[0] = (*text < 127 && *text >= 32 && *text != '|') ? (char)*text : '?';
        out_text(out, one);
    }
}

static void out_close(Out *out)
{
    out_flush(out);
    if (out->file != INVALID_HANDLE_VALUE) {
        FlushFileBuffers(out->file);
        CloseHandle(out->file);
        out->file = INVALID_HANDLE_VALUE;
    }
}

/* The stick (and any other USB disk) is not part of SYNC. */
static BOOL skip_root(const WCHAR *name)
{
    return _wcsnicmp(name, L"USB", 3) == 0 || _wcsicmp(name, stick_root) == 0;
}

/* D|<folder> and F|<file>|<size> for everything below path (a MAX_PATH buffer, restored). */
static void list_tree(WCHAR *path, int depth)
{
    WIN32_FIND_DATAW found;
    HANDLE search;
    size_t length = wcslen(path);
    if (depth > MAX_DEPTH || length + 3 >= MAX_PATH || listed_lines >= MAX_LINES || listing.failed || stop_dump)
        return;
    wcscat(path, L"\\*");
    search = FindFirstFileW(path, &found);
    path[length] = L'\0';
    if (search == INVALID_HANDLE_VALUE)
        return;
    do {
        if (wcscmp(found.cFileName, L".") == 0 || wcscmp(found.cFileName, L"..") == 0 ||
            length + 2 + wcslen(found.cFileName) >= MAX_PATH)
            continue;
        path[length] = L'\\';
        wcscpy(path + length + 1, found.cFileName);
        if (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            out_text(&listing, "D|");
            out_wide(&listing, path);
            if (depth == 0 && skip_root(found.cFileName)) {
                out_text(&listing, "|skipped\r\n");
            } else {
                out_text(&listing, "\r\n");
                list_tree(path, depth + 1);
            }
        } else {
            out_text(&listing, "F|");
            out_wide(&listing, path);
            out_text(&listing, "|");
            out_uint(&listing, found.nFileSizeLow);
            out_text(&listing, "\r\n");
        }
        path[length] = L'\0';
        listed_lines++;
    } while (listed_lines < MAX_LINES && !stop_dump && FindNextFileW(search, &found));
    FindClose(search);
}

/* Copies one file and hashes what it read; *error is GetLastError() on failure. */
static BOOL copy_file(const WCHAR *from, const WCHAR *to, BYTE digest[32], DWORD *size, DWORD *error)
{
    Sha256 sha;
    DWORD got, written;
    BOOL ok = TRUE;
    HANDLE in, out;
    *size = 0;
    in = CreateFileW(from, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                     FILE_ATTRIBUTE_NORMAL, NULL);
    if (in == INVALID_HANDLE_VALUE) {
        *error = GetLastError();
        return FALSE;
    }
    out = CreateFileW(to, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE) {
        *error = GetLastError();
        CloseHandle(in);
        return FALSE;
    }
    sha256_init(&sha);
    for (;;) {
        if (!ReadFile(in, chunk, sizeof(chunk), &got, NULL)) {
            *error = GetLastError();
            ok = FALSE;
            break;
        }
        if (got == 0)
            break;
        sha256_update(&sha, chunk, got);
        if (!WriteFile(out, chunk, got, &written, NULL) || written != got) {
            *error = GetLastError();
            ok = FALSE;
            stick_gone = TRUE;
            break;
        }
        *size += got;
        dump_bytes += got;
        if (stop_dump) {
            *error = 0;
            ok = FALSE;
            break;
        }
        Sleep(2);  /* room for SYNC between chunks */
    }
    CloseHandle(out);
    CloseHandle(in);
    if (ok)
        sha256_final(&sha, digest);
    return ok;
}

/* Whether a file of this size still fits above the reserve. Free space is slow to ask for, so it
 * is asked every 100 files and estimated in between from what was copied since. */
static BOOL dump_has_room(DWORD size)
{
    DWORD used_mb;
    if (dump_files % 100 == 0 || room_mb == 0) {
        room_mb = free_mb(folder, NULL);
        room_bytes = dump_bytes;
    }
    used_mb = (dump_bytes - room_bytes) >> 20;
    return used_mb < room_mb && room_mb - used_mb > DUMP_RESERVE_MB + (size >> 20) + 1;
}

/* Copies everything below source to target (MAX_PATH buffers, restored); one manifest line
 * per file: F|<car path>|<size>|<sha256>, or E|<car path>|error <code>. */
static void copy_tree(WCHAR *source, WCHAR *target, int depth)
{
    static const char hex[] = "0123456789abcdef";
    WIN32_FIND_DATAW found;
    HANDLE search;
    size_t source_length = wcslen(source), target_length = wcslen(target);
    if (depth > MAX_DEPTH || source_length + 3 >= MAX_PATH || stop_dump || stick_gone)
        return;
    CreateDirectoryW(target, NULL);
    wcscat(source, L"\\*");
    search = FindFirstFileW(source, &found);
    source[source_length] = L'\0';
    if (search == INVALID_HANDLE_VALUE)
        return;
    do {
        size_t name = wcslen(found.cFileName);
        if (wcscmp(found.cFileName, L".") == 0 || wcscmp(found.cFileName, L"..") == 0)
            continue;
        if (source_length + 2 + name >= MAX_PATH || target_length + 2 + name >= MAX_PATH) {
            dump_errors++;
            continue;
        }
        source[source_length] = target[target_length] = L'\\';
        wcscpy(source + source_length + 1, found.cFileName);
        wcscpy(target + target_length + 1, found.cFileName);
        if (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            copy_tree(source, target, depth + 1);
        } else if (dump_bytes + found.nFileSizeLow > DUMP_LIMIT || !dump_has_room(found.nFileSizeLow)) {
            stop_dump = TRUE;
        } else {
            BYTE digest[32];
            DWORD size, error = 0;
            int i;
            if (copy_file(source, target, digest, &size, &error)) {
                char text[65];
                for (i = 0; i < 32; i++) {
                    text[2 * i] = hex[digest[i] >> 4];
                    text[2 * i + 1] = hex[digest[i] & 15];
                }
                text[64] = '\0';
                out_text(&manifest, "F|");
                out_wide(&manifest, source);
                out_text(&manifest, "|");
                out_uint(&manifest, size);
                out_text(&manifest, "|");
                out_text(&manifest, text);
                out_text(&manifest, "\r\n");
                dump_files++;
            } else {
                out_text(&manifest, "E|");
                out_wide(&manifest, source);
                out_text(&manifest, "|error ");
                out_uint(&manifest, error);
                out_text(&manifest, "\r\n");
                dump_errors++;
            }
        }
        source[source_length] = target[target_length] = L'\0';
        out_flush(&manifest);
        if (manifest.failed)
            stop_dump = TRUE;
    } while (!stop_dump && !stick_gone && FindNextFileW(search, &found));
    FindClose(search);
}

static DWORD WINAPI dump(LPVOID unused)
{
    WCHAR path[MAX_PATH], target[MAX_PATH];
    (void)unused;
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    if (in_folder(path, L"\\files.txt") && out_open(&listing, path)) {
        path[0] = L'\0';
        list_tree(path, 0);
        out_close(&listing);
    }
    listing_broken = listing.failed || listing.file == NULL;
    listing_done = TRUE;
    if (in_folder(path, L"\\skins.txt") && out_open(&manifest, path) && in_folder(target, L"\\skins")) {
        CreateDirectoryW(target, NULL);
        if (wcslen(target) + wcslen(SKINS) < MAX_PATH) {
            wcscat(target, SKINS);
            wcscpy(path, SKINS);
            copy_tree(path, target, 0);
        }
        out_text(&manifest, stop_dump ? "T|stopped|" : "T|complete|");
        out_uint(&manifest, dump_files);
        out_text(&manifest, " files|");
        out_uint(&manifest, dump_bytes);
        out_text(&manifest, " bytes|");
        out_uint(&manifest, dump_errors);
        out_text(&manifest, " errors\r\n");
        out_close(&manifest);
    }
    manifest_broken = manifest.failed || manifest.file == NULL;
    dump_done = TRUE;
    return 0;
}

/* ---- processor and memory, every LOAD_EVERY_MS ---- */

typedef struct {
    DWORD pid, delta;
    WCHAR exe[32];
} Usage;

typedef struct {
    DWORD id, units;
} Seen;

#define MAX_THREADS 1024
static Usage usage[MAX_PROCS];
static Seen threads_before[MAX_THREADS], threads_now[MAX_THREADS];
static int threads_before_count;
static BOOL times_work = TRUE;

static BOOL thread_time(DWORD id, DWORD *units)
{
    FILETIME created, exited, kernel, user;
    HANDLE thread;
    BOOL ok;
    thread = open_thread ? open_thread(QUERY_THREAD, FALSE, id) : (HANDLE)id;
    if (!thread)
        return FALSE;
    ok = thread_times(thread, &created, &exited, &kernel, &user);
    if (open_thread)
        CloseHandle(thread);
    if (ok)
        *units = kernel.dwLowDateTime + user.dwLowDateTime;  /* modulo 2^32; a delta stays right */
    return ok;
}

/* Each thread's time since the last sample is added to its program; a thread seen for the first
 * time counts from 0, one that ended is simply gone. */
static void sample_load(DWORD interval, DWORD idle_delta, BOOL idle_known)
{
    MEMORYSTATUS memory;
    ProcessEntry process;
    ThreadEntry thread;
    HANDLE list;
    int count = 0, now_count = 0, i, j, shown;
    DWORD measured = 0;
    BOOL first = threads_before_count == 0;

    if (snapshot && first_process && next_process && close_snapshot) {
        list = snapshot(TH32CS_SNAPPROCESS | TH32CS_SNAPTHREAD | TH32CS_SNAPNOHEAPS, 0);
        if (list != INVALID_HANDLE_VALUE) {
            process.dwSize = sizeof(process);
            if (first_process(list, &process)) {
                do {
                    if (count < MAX_PROCS) {
                        usage[count].pid = process.th32ProcessID;
                        usage[count].delta = 0;
                        wcsncpy(usage[count].exe, process.szExeFile, 31);
                        usage[count].exe[31] = L'\0';
                        count++;
                    }
                    process.dwSize = sizeof(process);
                } while (next_process(list, &process));
            }
            if (times_work && thread_times && first_thread && next_thread) {
                thread.dwSize = sizeof(thread);
                if (first_thread(list, &thread)) {
                    do {
                        DWORD units, delta;
                        if (now_count < MAX_THREADS && thread_time(thread.th32ThreadID, &units)) {
                            measured++;
                            delta = units;
                            for (j = 0; j < threads_before_count; j++)
                                if (threads_before[j].id == thread.th32ThreadID) {
                                    delta = units - threads_before[j].units;
                                    break;
                                }
                            threads_now[now_count].id = thread.th32ThreadID;
                            threads_now[now_count].units = units;
                            now_count++;
                            if (threads_before_count && delta <= interval * 10000UL)
                                for (j = 0; j < count; j++)
                                    if (usage[j].pid == thread.th32OwnerProcessID)
                                        usage[j].delta += delta;
                        }
                        thread.dwSize = sizeof(thread);
                    } while (next_thread(list, &thread));
                }
                if (!measured)
                    times_work = FALSE;  /* say so once, then stop trying */
            }
            close_snapshot(list);
        }
    }
    memcpy(threads_before, threads_now, sizeof(Seen) * now_count);
    threads_before_count = now_count;

    memset(&memory, 0, sizeof(memory));
    memory.dwLength = sizeof(memory);
    GlobalMemoryStatus(&memory);
    begin("load|cpu ");
    if (idle_known && interval) {
        DWORD idle = idle_delta > interval ? interval : idle_delta;
        put_uint(100 - idle * 100 / interval);
        put("%");
    } else {
        put("?");
    }
    put("|memory ");
    put_uint(memory.dwMemoryLoad);
    put("%, ");
    put_uint(memory.dwAvailPhys / 1024);
    put(" KB free|");
    if (!measured) {
        put("per program n/a");
    } else if (first) {
        put("per program from the next sample");
    } else {
        for (shown = 0; shown < TOP; shown++) {  /* the busiest first, 1% or more */
            int best = -1;
            for (i = 0; i < count; i++)
                if (interval && usage[i].delta / (interval * 100UL) >= 1 &&
                    (best < 0 || usage[i].delta > usage[best].delta))
                    best = i;
            if (best < 0)
                break;
            if (shown)
                put(" ");
            put_wide(usage[best].exe, 31);
            put(" ");
            put_uint(usage[best].delta / (interval * 100UL));
            put("%");
            usage[best].delta = 0;  /* taken */
        }
    }
    end_line();
}

/* ---- screenshots ---- */

static HDC memory_dc;
static HBITMAP picture;
static BYTE *pixels;
static int width, height, stride, shots;
static DWORD saved_hash, previous_hash, saved_at;
static BOOL any_saved, shots_stopped, black_noted;

static BOOL screen_setup(void)
{
    BITMAPINFO info;
    HDC screen;
    width = GetSystemMetrics(SM_CXSCREEN);
    height = GetSystemMetrics(SM_CYSCREEN);
    if (width <= 0 || height <= 0 || width > 2048 || height > 2048)
        return FALSE;
    stride = (width * 3 + 3) & ~3;
    screen = GetDC(NULL);
    if (!screen)
        return FALSE;
    memset(&info, 0, sizeof(info));
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = width;
    info.bmiHeader.biHeight = height;  /* bottom-up, the order a BMP file keeps */
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 24;
    info.bmiHeader.biCompression = BI_RGB;
    memory_dc = CreateCompatibleDC(screen);
    picture = CreateDIBSection(screen, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    ReleaseDC(NULL, screen);
    if (!memory_dc || !picture || !pixels)
        return FALSE;
    SelectObject(memory_dc, picture);
    return TRUE;
}

static WCHAR *put_number(WCHAR *at, unsigned value, int digits)
{
    int i;
    for (i = digits - 1; i >= 0; i--) {
        at[i] = (WCHAR)(L'0' + value % 10);
        value /= 10;
    }
    return at + digits;
}

static BOOL save_shot(const char *why)
{
    WCHAR path[MAX_PATH], *at;
    SYSTEMTIME now;
    BYTE header[54];
    DWORD written;
    HANDLE file;
    BOOL ok;
    if (!in_folder(path, L"\\screens\\") || wcslen(path) + 16 >= MAX_PATH)
        return FALSE;
    GetLocalTime(&now);
    at = put_number(path + wcslen(path), (unsigned)shots + 1, 4);
    *at++ = L'-';
    at = put_number(at, now.wHour, 2);
    at = put_number(at, now.wMinute, 2);
    at = put_number(at, now.wSecond, 2);
    wcscpy(at, L".bmp");
    file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return FALSE;
    bmp_header(header, width, height, stride);
    ok = WriteFile(file, header, sizeof(header), &written, NULL) && written == sizeof(header) &&
         WriteFile(file, pixels, (DWORD)stride * (DWORD)height, &written, NULL) &&
         written == (DWORD)stride * (DWORD)height;
    CloseHandle(file);
    if (!ok) {
        DeleteFileW(path);
        return FALSE;
    }
    shots++;
    begin("screen|");
    put_wide(path + wcslen(folder) + 1, 40);
    put("|");
    put(why);
    end_line();
    return TRUE;
}

static void look_at_screen(DWORD now)
{
    static DWORD checked_at, room = 0xFFFFFFFF;
    HDC screen;
    BOOL black, ok;
    DWORD hash;
    if (shots_stopped)
        return;
    if (room == 0xFFFFFFFF || now - checked_at >= 60000) {  /* free space is slow to ask for */
        room = free_mb(folder, NULL);
        checked_at = now;
    }
    if (shots >= MAX_SHOTS || room < SHOT_RESERVE_MB) {
        shots_stopped = TRUE;
        begin("screen|no more screenshots: ");
        put(shots >= MAX_SHOTS ? "limit reached" : "the stick is nearly full");
        end_line();
        return;
    }
    screen = GetDC(NULL);
    if (!screen)
        return;
    ok = BitBlt(memory_dc, 0, 0, width, height, screen, 0, 0, SRCCOPY);
    ReleaseDC(NULL, screen);
    if (!ok)
        return;
    hash = frame_hash(pixels, width, height, stride, &black);
    if (black && !black_noted) {
        black_noted = TRUE;
        begin("screen|the copy is black (screen off, or not readable this way)");
        end_line();
    }
    if (want_shot(hash, previous_hash, saved_hash, any_saved, now - saved_at)) {
        if (save_shot(!any_saved ? "first" : hash == previous_hash ? "held still" : "kept changing")) {
            saved_hash = hash;
            saved_at = now;
            any_saved = TRUE;
        }
    }
    previous_hash = hash;
}

/* ---- main ---- */

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    DWORD seconds = 0, started, last_load, last_heartbeat, idle_before = 0, reported_files = 0;
    BOOL idle_known, screen_ok, listing_reported = FALSE, dump_reported = FALSE;
    WCHAR *at = command, path[MAX_PATH];
    HANDLE worker;
    (void)instance;
    (void)previous;
    (void)show;

    while (*at == L' ')
        at++;
    while (*at >= L'0' && *at <= L'9')
        seconds = seconds * 10 + (DWORD)(*at++ - L'0');
    while (*at == L' ' || *at == L'"')
        at++;
    if (seconds < 10 || seconds > 14400 || !*at || wcslen(at) + 40 >= MAX_PATH)
        return 1;
    wcscpy(folder, at);
    while (wcslen(folder) && (folder[wcslen(folder) - 1] == L'"' || folder[wcslen(folder) - 1] == L' ' ||
                              folder[wcslen(folder) - 1] == L'\\'))
        folder[wcslen(folder) - 1] = L'\0';
    in_folder(log_path, L"\\drive.log");
    {  /* the stick's root folder, e.g. "USB Disk" of "\USB Disk\s2am\reports\..." */
        const WCHAR *name = folder[0] == L'\\' ? folder + 1 : folder;
        int i;
        for (i = 0; name[i] && name[i] != L'\\' && i < MAX_PATH - 1; i++)
            stick_root[i] = name[i];
        stick_root[i] = L'\0';
    }
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    load_functions();

    started = GetTickCount();
    begin("start|s2am drive|seconds ");
    put_uint(seconds);
    end_line();
    system_facts();
    flush();
    if (write_failures)
        return 1;

    if (in_folder(path, L"\\screens"))
        CreateDirectoryW(path, NULL);
    screen_ok = screen_setup();
    begin(screen_ok ? "screen|copying the screen every second" : "screen|cannot copy the screen");
    end_line();
    worker = CreateThread(NULL, 0, dump, NULL, 0, NULL);
    begin(worker ? "files|listing every file, then copying \\8inchSkins" : "files|could not start");
    end_line();
    idle_known = idle_time && idle_time() != 0xFFFFFFFF;
    if (idle_known)
        idle_before = idle_time();
    last_load = last_heartbeat = started;
    flush();

    for (;;) {
        DWORD now = GetTickCount();
        if (screen_ok)
            look_at_screen(now);
        if (now - last_load >= LOAD_EVERY_MS) {
            DWORD idle_now = idle_known ? idle_time() : 0;
            sample_load(now - last_load, idle_now - idle_before, idle_known);
            idle_before = idle_now;
            last_load = now;
        }
        if (listing_done && !listing_reported) {
            begin(listing_broken ? "files|files.txt could not be written in full, " : "files|files.txt done, ");
            put_uint(listed_lines);
            put(" entries");
            end_line();
            listing_reported = TRUE;
        }
        if (dump_files / 100 != reported_files / 100 && !dump_done) {
            begin("files|copied ");
            put_uint(dump_files);
            put(" files, ");
            put_uint(dump_bytes / 1024);
            put(" KB");
            end_line();
            reported_files = dump_files;
        }
        if (dump_done && !dump_reported) {
            begin(stop_dump ? "files|copy stopped: " : "files|copy complete: ");
            put_uint(dump_files);
            put(" files, ");
            put_uint(dump_bytes / 1024);
            put(" KB, ");
            put_uint(dump_errors);
            put(manifest_broken ? " errors (skins.txt could not be written in full)" : " errors (skins.txt)");
            end_line();
            dump_reported = TRUE;
        }
        if (now - last_heartbeat >= HEARTBEAT_MS) {
            begin("tick|");
            put_uint((now - started) / 1000);
            put(" s|");
            put_uint((unsigned long)shots);
            put(" screenshots");
            end_line();
            last_heartbeat = now;
        }
        flush();
        if (write_failures >= 3 || stick_gone)
            break;  /* the stick is gone */
        if (now - started >= seconds * 1000)
            break;
        Sleep(TICK_MS);
    }
    stop_dump = TRUE;
    if (worker) {
        WaitForSingleObject(worker, 5000);
        CloseHandle(worker);
    }
    begin("end");
    end_line();
    flush();
    return 0;
}
