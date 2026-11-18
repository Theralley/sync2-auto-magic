/*
 * akdec - run the real Windows CE FFmpeg DLLs (stock or rebuilt) on Linux/ARM under
 * qemu-arm, driving them with exactly the call sequence AutoKit.exe uses.
 *
 *   akdec <dll_dir> <in.h264> <out.yuv> [chunk|au] [drain]
 *
 * - A minimal PE loader maps avcodec-56.dll, avutil-54.dll and avformat-56.dll at their
 *   preferred image bases (it refuses to run otherwise, so profiler address ranges are exact),
 *   applies base relocations if ever needed, resolves the imports between the three DLLs from
 *   their export tables and resolves COREDLL.dll imports to the small shims below, then calls
 *   each DLL's entry point with DLL_PROCESS_ATTACH, in AutoKit's LoadLibrary order.
 * - The 16 functions are looked up by name (AutoKit uses GetProcAddressW), then the init,
 *   decode and teardown code is a line-by-line transcription of AutoKit 0x2D470 / 0x2D5A0 /
 *   0x2DC64 (see analysis/autokit-ffmpeg-*.asm): same struct offsets, same parser/decoder
 *   loop, same "chroma stride = linesize[0]/2" assumption when it copies a frame out.
 * - Input is fed either in fixed-size chunks (default 4096 bytes, like a network buffer;
 *   each chunk is copied into its own buffer) or one access unit per call ("au": the file
 *   is split before each access unit delimiter NAL, which the test streams contain).
 * - "drain" adds, after the AutoKit loop and only for verification, a parser flush plus
 *   decoder drain so the complete stream can be compared with a reference decode. AutoKit
 *   itself never does this.
 *
 * Calling convention: the DLLs are CeGCC (arm-mingw32ce, APCS-GNU, soft-float, little-endian
 * word order for doubles - probed) or the stock 2015 mingw32ce build. For all calls used here
 * (int/pointer arguments, int64 arguments already 8-byte aligned on the stack) APCS-GNU and
 * the Linux EABI place every argument identically. The printf-family shims deliberately do
 * not interpret varargs (EABI and APCS align 64-bit varargs differently).
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;

static int verbose;
#define LOG(...) fprintf(stderr, __VA_ARGS__)

/* ------------------------------------------------------------------ COREDLL shims */

static u32 last_error;
static int fake_std[3];

static void once(const char *name, int *flag)
{
    if (!*flag) {
        *flag = 1;
        if (verbose)
            LOG("akdec: first call coredll!%s\n", name);
    }
}
#define ONCE(n) do { static int f_; once(n, &f_); } while (0)

static int fd_of(void *f)
{
    if (f == &fake_std[1]) return 1;
    if (f == &fake_std[2]) return 2;
    return -1;
}

/* heap accounting for DLL allocations (usable sizes, so slightly above the requested bytes) */
#include <malloc.h>
static long heap_cur, heap_peak, heap_allocs;
static void heap_add(void *p) { if (p) { heap_cur += malloc_usable_size(p); heap_allocs++; if (heap_cur > heap_peak) heap_peak = heap_cur; } }
static void heap_sub(void *p) { if (p) heap_cur -= malloc_usable_size(p); }
static void *sh_malloc(size_t n) { ONCE("malloc"); void *p = malloc(n); heap_add(p); return p; }
static void sh_free(void *p) { ONCE("free"); heap_sub(p); free(p); }
static void *sh_realloc(void *p, size_t n)
{
    ONCE("realloc"); heap_sub(p); void *q = realloc(p, n);
    if (q) heap_add(q); else heap_add(p); /* on failure the old block stays */
    return q;
}
static void *sh_memcpy(void *d, const void *s, size_t n) { ONCE("memcpy"); return memcpy(d, s, n); }
static void *sh_memmove(void *d, const void *s, size_t n) { ONCE("memmove"); return memmove(d, s, n); }
static void *sh_memset(void *d, int c, size_t n) { ONCE("memset"); return memset(d, c, n); }
static int sh_memcmp(const void *a, const void *b, size_t n) { ONCE("memcmp"); return memcmp(a, b, n); }
static void *sh_memchr(const void *a, int c, size_t n) { ONCE("memchr"); return memchr(a, c, n); }
static size_t sh_strlen(const char *s) { ONCE("strlen"); return strlen(s); }
static int sh_strcmp(const char *a, const char *b) { ONCE("strcmp"); return strcmp(a, b); }
static int sh_strncmp(const char *a, const char *b, size_t n) { ONCE("strncmp"); return strncmp(a, b, n); }
static char *sh_strchr(const char *s, int c) { ONCE("strchr"); return strchr(s, c); }
static char *sh_strrchr(const char *s, int c) { ONCE("strrchr"); return strrchr(s, c); }
static char *sh_strstr(const char *a, const char *b) { ONCE("strstr"); return strstr(a, b); }
static size_t sh_strspn(const char *a, const char *b) { ONCE("strspn"); return strspn(a, b); }
static size_t sh_strcspn(const char *a, const char *b) { ONCE("strcspn"); return strcspn(a, b); }
static char *sh_strcpy(char *a, const char *b) { ONCE("strcpy"); return strcpy(a, b); }
static long sh_strtol(const char *a, char **e, int b) { ONCE("strtol"); return strtol(a, e, b); }
static unsigned long sh_strtoul(const char *a, char **e, int b) { ONCE("strtoul"); return strtoul(a, e, b); }
static int sh_atoi(const char *a) { ONCE("atoi"); return atoi(a); }
static int sh_stricmp(const char *a, const char *b) { ONCE("_stricmp"); return strcasecmp(a, b); }
static void sh_qsort(void *b, size_t n, size_t s, int (*c)(const void *, const void *)) { ONCE("qsort"); qsort(b, n, s, c); }
static int sh_sscanf(const char *s, const char *fmt, ...)
{   /* pointer-only varargs: identical in APCS and EABI */
    va_list ap; ONCE("sscanf"); va_start(ap, fmt); int r = vsscanf(s, fmt, ap); va_end(ap); return r;
}
static int sh_snprintf(char *b, size_t n, const char *fmt, ...)
{   /* do not interpret varargs (64-bit alignment differs); copy the format only */
    ONCE("_snprintf"); LOG("akdec: _snprintf(\"%s\") called - varargs not interpreted\n", fmt);
    if (n) { strncpy(b, fmt, n - 1); b[n - 1] = 0; }
    return (int)strlen(fmt);
}
static void *sh_getstdfilex(int i) { ONCE("_getstdfilex"); return (i >= 0 && i < 3) ? &fake_std[i] : NULL; }
static size_t sh_fwrite(const void *p, size_t s, size_t n, void *f)
{
    ONCE("fwrite"); int fd = fd_of(f); if (fd < 0) return 0;
    ssize_t r = write(2, p, s * n); (void)r; return n;
}
static int sh_fputs(const char *str, void *f) { ONCE("fputs"); if (fd_of(f) < 0) return -1; ssize_t r = write(2, str, strlen(str)); (void)r; return 0; }
static int sh_fputc(int c, void *f) { ONCE("fputc"); char ch = (char)c; if (fd_of(f) < 0) return -1; ssize_t r = write(2, &ch, 1); (void)r; return c; }
static int sh_fflush(void *f) { ONCE("fflush"); return 0; }
static int sh_vfprintf(void *f, const char *fmt, void *ap)
{
    ONCE("vfprintf"); if (fd_of(f) < 0) return -1;
    LOG("[vfprintf fmt] %s", fmt); return (int)strlen(fmt);
}
static int sh_fcloseall(void) { ONCE("_fcloseall"); return 0; }
static void *sh_wfdopen(void *h, const u16 *m) { ONCE("_wfdopen"); return NULL; }
static char *sh_ecvt(double v, int nd, int *dec, int *sign) { ONCE("_ecvt"); return ecvt(v, nd, dec, sign); }
static char *sh_fcvt(double v, int nd, int *dec, int *sign) { ONCE("_fcvt"); return fcvt(v, nd, dec, sign); }
static int sh_isctype(int c, int mask)
{
    ONCE("_isctype");
    if (c < -1 || c > 255) return 0;
    int r = 0;
    if ((mask & 0x01) && isupper(c)) r |= 0x01;
    if ((mask & 0x02) && islower(c)) r |= 0x02;
    if ((mask & 0x04) && isdigit(c)) r |= 0x04;
    if ((mask & 0x08) && isspace(c)) r |= 0x08;
    if ((mask & 0x10) && ispunct(c)) r |= 0x10;
    if ((mask & 0x20) && iscntrl(c)) r |= 0x20;
    if ((mask & 0x40) && c == ' ') r |= 0x40;
    if ((mask & 0x80) && isxdigit(c)) r |= 0x80;
    if ((mask & 0x100) && isalpha(c)) r |= 0x100;
    return r;
}
static int sh_isnan(double x) { ONCE("_isnan"); return isnan(x); }
#define M1(n, f) static double sh_##n(double x) { ONCE(#n); return f(x); }
M1(sqrt, sqrt) M1(exp, exp) M1(log, log) M1(sin, sin) M1(cos, cos) M1(tan, tan) M1(atan, atan)
M1(acos, acos) M1(asin, asin) M1(sinh, sinh) M1(cosh, cosh) M1(floor, floor) M1(ceil, ceil) M1(fabs, fabs)
static double sh_pow(double a, double b) { ONCE("pow"); return pow(a, b); }
static double sh_atan2(double a, double b) { ONCE("atan2"); return atan2(a, b); }
static double sh_hypot(double a, double b) { ONCE("_hypot"); return hypot(a, b); }
static size_t sh_wcslen(const u16 *s) { ONCE("wcslen"); size_t n = 0; while (s[n]) n++; return n; }
static u16 *sh_wcsdup(const u16 *s) { ONCE("_wcsdup"); size_t n = sh_wcslen(s) + 1; u16 *d = malloc(n * 2); if (d) memcpy(d, s, n * 2); return d; }
static size_t sh_mbstowcs(u16 *d, const char *s, size_t n)
{
    ONCE("mbstowcs"); size_t i = 0;
    for (; s[i] && (!d || i < n); i++) if (d) d[i] = (u8)s[i];
    if (d && i < n) d[i] = 0;
    return i;
}
static size_t sh_wcstombs(char *d, const u16 *s, size_t n)
{
    ONCE("wcstombs"); size_t i = 0;
    for (; s[i] && (!d || i < n); i++) if (d) d[i] = s[i] < 128 ? (char)s[i] : '?';
    if (d && i < n) d[i] = 0;
    return i;
}
static u32 sh_GetTickCount(void) { ONCE("GetTickCount"); struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (u32)(t.tv_sec * 1000 + t.tv_nsec / 1000000); }
static void sh_csnop(void *cs) { ONCE("*CriticalSection"); }
static long sh_InterlockedExchange(long *p, long v) { ONCE("InterlockedExchange"); long o = *p; *p = v; return o; }
static u32 sh_GetLastError(void) { ONCE("GetLastError"); return last_error; }
static void sh_SetLastError(u32 e) { ONCE("SetLastError"); last_error = e; }
static int sh_true1(void *a) { ONCE("DisableThreadLibraryCalls"); return 1; }
static void sh_Sleep(u32 ms) { ONCE("Sleep"); usleep(ms * 1000); }
static size_t sh_VirtualQuery(void *addr, u32 *mbi, size_t len)
{
    ONCE("VirtualQuery");
    if (len < 28) return 0;
    u32 page = (u32)(uintptr_t)addr & ~0xFFFu;
    mbi[0] = page; mbi[1] = page; mbi[2] = 0x40; mbi[3] = 0x1000; mbi[4] = 0x1000; mbi[5] = 0x40; mbi[6] = 0x20000;
    return 28;
}
static int sh_VirtualProtect(void *a, size_t n, u32 prot, u32 *old) { ONCE("VirtualProtect"); if (old) *old = 0x40; return 1; }
static void sh_GetTime(u16 *st) { ONCE("GetLocal/SystemTime"); memset(st, 0, 16); st[0] = 2026; st[1] = 1; st[3] = 1; }
static int sh_TimeConv(const void *a, void *b) { ONCE("FileTime<->SystemTime"); memset(b, 0, 8); return 1; }
static int sh_GetCPInfo(u32 cp, void *info) { ONCE("GetCPInfo"); return 0; }
static void *sh_failhandle(void) { ONCE("CreateFileW/FindFirstFileW"); last_error = 2; return (void *)-1; }
static int sh_fail0(void) { ONCE("file API (fail)"); last_error = 2; return 0; }
static u32 sh_failattr(const u16 *p) { ONCE("GetFileAttributesW"); last_error = 2; return 0xFFFFFFFFu; }
static u32 sh_failsetfp(void) { ONCE("SetFilePointer"); last_error = 6; return 0xFFFFFFFFu; }
static int sh_TerminateProcess(void *h, u32 code)
{
    LOG("akdec: TerminateProcess(%u) called by DLL code - abort\n", code);
    _exit(97);
}

struct shim { const char *name; void *fn; };
static const struct shim shims[] = {
#define S(n, f) { n, (void *)(f) }
    S("malloc", sh_malloc), S("free", sh_free), S("realloc", sh_realloc), S("memcpy", sh_memcpy),
    S("memmove", sh_memmove), S("memset", sh_memset), S("memcmp", sh_memcmp), S("memchr", sh_memchr),
    S("strlen", sh_strlen), S("strcmp", sh_strcmp), S("strncmp", sh_strncmp), S("strchr", sh_strchr),
    S("strrchr", sh_strrchr), S("strstr", sh_strstr), S("strspn", sh_strspn), S("strcspn", sh_strcspn),
    S("strcpy", sh_strcpy), S("strtol", sh_strtol), S("strtoul", sh_strtoul), S("atoi", sh_atoi),
    S("_stricmp", sh_stricmp), S("qsort", sh_qsort), S("sscanf", sh_sscanf), S("_snprintf", sh_snprintf),
    S("_getstdfilex", sh_getstdfilex), S("fwrite", sh_fwrite), S("fputs", sh_fputs), S("fputc", sh_fputc),
    S("fflush", sh_fflush), S("vfprintf", sh_vfprintf), S("_fcloseall", sh_fcloseall), S("_wfdopen", sh_wfdopen),
    S("_ecvt", sh_ecvt), S("_fcvt", sh_fcvt), S("_isctype", sh_isctype), S("_isnan", sh_isnan),
    S("sqrt", sh_sqrt), S("exp", sh_exp), S("log", sh_log), S("sin", sh_sin), S("cos", sh_cos), S("tan", sh_tan),
    S("atan", sh_atan), S("acos", sh_acos), S("asin", sh_asin), S("sinh", sh_sinh), S("cosh", sh_cosh),
    S("floor", sh_floor), S("ceil", sh_ceil), S("fabs", sh_fabs), S("pow", sh_pow), S("atan2", sh_atan2),
    S("_hypot", sh_hypot), S("wcslen", sh_wcslen), S("_wcsdup", sh_wcsdup), S("mbstowcs", sh_mbstowcs),
    S("wcstombs", sh_wcstombs), S("GetTickCount", sh_GetTickCount),
    S("InitializeCriticalSection", sh_csnop), S("DeleteCriticalSection", sh_csnop),
    S("EnterCriticalSection", sh_csnop), S("LeaveCriticalSection", sh_csnop),
    S("InterlockedExchange", sh_InterlockedExchange), S("GetLastError", sh_GetLastError),
    S("SetLastError", sh_SetLastError), S("DisableThreadLibraryCalls", sh_true1), S("Sleep", sh_Sleep),
    S("VirtualQuery", sh_VirtualQuery), S("VirtualProtect", sh_VirtualProtect),
    S("GetLocalTime", sh_GetTime), S("GetSystemTime", sh_GetTime),
    S("FileTimeToSystemTime", sh_TimeConv), S("SystemTimeToFileTime", sh_TimeConv),
    S("GetCPInfo", sh_GetCPInfo), S("CreateFileW", sh_failhandle), S("FindFirstFileW", sh_failhandle),
    S("FindClose", sh_fail0), S("CloseHandle", sh_fail0), S("ReadFile", sh_fail0), S("DeleteFileW", sh_fail0),
    S("GetFileInformationByHandle", sh_fail0), S("GetTempPathW", sh_fail0), S("GetTempFileNameW", sh_fail0),
    S("GetFileAttributesW", sh_failattr), S("SetFilePointer", sh_failsetfp),
    S("TerminateProcess", sh_TerminateProcess),
#undef S
};

/* Unshimmed imports get a per-slot trap that names the function and aborts. */
#define NTRAP 64
static const char *trap_names[NTRAP];
static int ntrap;
static void trap(int i) { LOG("akdec: unshimmed coredll!%s called - abort\n", trap_names[i]); _exit(98); }
#define T(i) static void trap##i(void) { trap(i); }
#define T8(a) T(a##0) T(a##1) T(a##2) T(a##3) T(a##4) T(a##5) T(a##6) T(a##7)
T8(0) T8(1) T8(2) T8(3) T8(4) T8(5) T8(6) T8(7)
#define P8(a) trap##a##0, trap##a##1, trap##a##2, trap##a##3, trap##a##4, trap##a##5, trap##a##6, trap##a##7
static void (*const traps[NTRAP])(void) = { P8(0), P8(1), P8(2), P8(3), P8(4), P8(5), P8(6), P8(7) };

static void *resolve_coredll(const char *name)
{
    for (size_t i = 0; i < sizeof shims / sizeof shims[0]; i++)
        if (!strcmp(shims[i].name, name))
            return shims[i].fn;
    for (int i = 0; i < ntrap; i++)
        if (!strcmp(trap_names[i], name))
            return (void *)traps[i];
    if (ntrap == NTRAP) { LOG("akdec: too many unshimmed imports\n"); exit(2); }
    if (verbose) LOG("akdec: note: coredll!%s not shimmed (trap if called)\n", name);
    trap_names[ntrap] = strdup(name);
    return (void *)traps[ntrap++];
}

/* ------------------------------------------------------------------ PE loader */

struct dll { char name[64]; u8 *base; u32 size; u32 pref; int attached; };
static struct dll dlls[8];
static int ndll;
static const char *dll_dir;

static u32 rd32(const u8 *p) { return p[0] | p[1] << 8 | p[2] << 16 | (u32)p[3] << 24; }
static u16 rd16(const u8 *p) { return p[0] | p[1] << 8; }

static struct dll *load_dll(const char *name);

static void *find_export(struct dll *d, const char *name)
{
    u8 *b = d->base;
    u32 nt = rd32(b + 0x3c), opt = nt + 24;
    u32 erva = rd32(b + opt + 96), esz = rd32(b + opt + 100);
    if (!erva) return NULL;
    u8 *e = b + erva;
    u32 nnames = rd32(e + 24), funcs = rd32(e + 28), names = rd32(e + 32), ords = rd32(e + 36);
    for (u32 i = 0; i < nnames; i++) {
        if (!strcmp((char *)b + rd32(b + names + 4 * i), name)) {
            u32 rva = rd32(b + funcs + 4 * rd16(b + ords + 2 * i));
            if (rva >= erva && rva < erva + esz) { LOG("akdec: forwarded export %s unsupported\n", name); exit(2); }
            return b + rva;
        }
    }
    return NULL;
}

static struct dll *load_dll(const char *name)
{
    for (int i = 0; i < ndll; i++)
        if (!strcasecmp(dlls[i].name, name))
            return &dlls[i];
    char path[512];
    snprintf(path, sizeof path, "%s/%s", dll_dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) { LOG("akdec: cannot open %s\n", path); exit(1); }
    fseek(f, 0, SEEK_END); long fsz = ftell(f); fseek(f, 0, SEEK_SET);
    u8 *file = malloc(fsz);
    if (fread(file, 1, fsz, f) != (size_t)fsz) { LOG("akdec: read error\n"); exit(1); }
    fclose(f);
    u32 nt = rd32(file + 0x3c);
    if (rd32(file + nt) != 0x4550) { LOG("akdec: %s not PE\n", name); exit(1); }
    u16 machine = rd16(file + nt + 4), nsec = rd16(file + nt + 6), optsz = rd16(file + nt + 20);
    u32 opt = nt + 24;
    if (rd16(file + opt) != 0x10b || (machine != 0x1c0 && machine != 0x1c2)) { LOG("akdec: %s: not PE32 ARM\n", name); exit(1); }
    u32 entry = rd32(file + opt + 16), pref = rd32(file + opt + 28), size = rd32(file + opt + 56), hdrs = rd32(file + opt + 60);
    u8 *base = mmap((void *)(uintptr_t)pref, size, PROT_READ | PROT_WRITE | PROT_EXEC,
                    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) { LOG("akdec: mmap failed\n"); exit(1); }
    if ((u32)(uintptr_t)base != pref) {
        LOG("akdec: %s could not be placed at its preferred base 0x%08x (got %p); refusing\n", name, pref, base);
        exit(3);
    }
    memcpy(base, file, hdrs);
    u8 *sec = file + opt + optsz;
    for (int i = 0; i < nsec; i++, sec += 40) {
        u32 va = rd32(sec + 12), raw = rd32(sec + 16), ptr = rd32(sec + 20), vsz = rd32(sec + 8);
        u32 n = raw < vsz || !vsz ? raw : vsz;
        if (n) memcpy(base + va, file + ptr, n);
    }
    free(file);
    struct dll *d = &dlls[ndll++];
    snprintf(d->name, sizeof d->name, "%s", name);
    d->base = base; d->size = size; d->pref = pref;
    if (verbose) LOG("akdec: mapped %s at %p size 0x%x\n", name, base, size);
    /* base relocations (only needed if not at pref; kept for completeness) */
    u32 delta = (u32)(uintptr_t)base - pref;
    u32 rrva = rd32(base + opt + 96 + 5 * 8), rsz = rd32(base + opt + 96 + 5 * 8 + 4);
    if (delta && rrva) {
        for (u8 *p = base + rrva; p < base + rrva + rsz;) {
            u32 page = rd32(p), bsz = rd32(p + 4);
            if (!bsz) break;
            for (u32 k = 8; k < bsz; k += 2) {
                u16 e = rd16(p + k);
                if ((e >> 12) == 3) { u32 *t = (u32 *)(base + page + (e & 0xfff)); *t += delta; }
                else if ((e >> 12) != 0) { LOG("akdec: reloc type %d unsupported\n", e >> 12); exit(2); }
            }
            p += bsz;
        }
    }
    /* imports */
    u32 irva = rd32(base + opt + 96 + 8);
    for (u8 *id = base + irva; irva && rd32(id + 12); id += 20) {
        const char *dn = (char *)base + rd32(id + 12);
        u32 oft = rd32(id), ft = rd32(id + 16);
        u32 *names = (u32 *)(base + (oft ? oft : ft)), *iat = (u32 *)(base + ft);
        int core = !strcasecmp(dn, "coredll.dll") || !strcasecmp(dn, "coredll"); /* stock: "COREDLL" */
        struct dll *dep = core ? NULL : load_dll(dn);
        for (int k = 0; names[k]; k++) {
            if (names[k] & 0x80000000u) { LOG("akdec: import by ordinal from %s unsupported\n", dn); exit(2); }
            const char *fn = (char *)base + names[k] + 2;
            void *addr = core ? resolve_coredll(fn) : find_export(dep, fn);
            if (!addr) { LOG("akdec: %s imports %s!%s which is not exported\n", name, dn, fn); exit(4); }
            iat[k] = (u32)(uintptr_t)addr;
        }
    }
    /* DllMain(hinst, DLL_PROCESS_ATTACH, NULL), after its dependencies (done above) */
    if (entry) {
        int (*dllmain)(void *, u32, void *) = (void *)(base + entry);
        int ok = dllmain(base, 1, NULL);
        if (verbose) LOG("akdec: %s DllMain -> %d\n", name, ok);
        if (!ok) { LOG("akdec: %s DllMain failed\n", name); exit(1); }
    }
    return d;
}

/* ------------------------------------------------------------------ AutoKit transcription */

typedef void (*fn_v)(void);
static struct {
    fn_v avcodec_register_all;
    void *(*av_parser_init)(int);
    int (*avcodec_open2)(void *, void *, void *);
    void *(*avcodec_find_decoder)(int);
    void (*av_free_packet)(void *);
    void (*av_init_packet)(void *);
    void *(*avcodec_alloc_context3)(void *);
    int (*avcodec_close)(void *);
    int (*avcodec_decode_video2)(void *, void *, int *, void *);
    int (*av_parser_parse2)(void *, void *, u8 **, int *, const u8 *, int, int64_t, int64_t, int64_t);
    void (*av_parser_close)(void *);
    void *(*av_frame_alloc)(void);
    void (*av_frame_free)(void **);
    void (*av_free)(void *);
    void *(*av_malloc)(size_t);
    fn_v av_register_all;
} F;

#define I32(p, off) (*(int *)((u8 *)(p) + (off)))
#define PTR(p, off) (*(u8 **)((u8 *)(p) + (off)))

static void *get(struct dll *d, const char *n)
{
    void *p = find_export(d, n);
    if (!p) { LOG("akdec: GetProcAddress(%s, %s) failed (AutoKit would exit(1))\n", d->name, n); exit(1); }
    return p;
}

static struct { void *pkt, *frame, *codec, *parser, *ctx; } K;
static FILE *out;
static long frames_out, chroma_stride_mismatch, frames_repacked;
static int out_w, out_h;
static double t_decode;

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

/* AutoKit's frame hand-off: when linesize[0] > width it repacks with chroma stride
 * linesize[0]/2; otherwise it passes data[0..2] straight through (stride == width). */
static void deliver(void)
{
    int w = I32(K.ctx, 0x78), h = I32(K.ctx, 0x7c), ls = I32(K.frame, 0x20);
    u8 *y = PTR(K.frame, 0), *u = PTR(K.frame, 4), *v = PTR(K.frame, 8);
    if (I32(K.frame, 0x24) != ls / 2 || I32(K.frame, 0x28) != ls / 2) chroma_stride_mismatch++;
    if (ls > w) frames_repacked++;
    out_w = w; out_h = h;
    int cs = ls > w ? ls / 2 : w / 2; /* the stride AutoKit uses for chroma in each path */
    int ys = ls > w ? ls : w;
    double t0 = now();
    if (out) {
        for (int r = 0; r < h; r++) fwrite(y + r * ys, 1, w, out);
        for (int r = 0; r < h / 2; r++) fwrite(u + r * cs, 1, w / 2, out);
        for (int r = 0; r < h / 2; r++) fwrite(v + r * cs, 1, w / 2, out);
    }
    t_decode -= now() - t0; /* exclude our file output from the decode time */
    frames_out++;
}

/* 0x2D5A0 */
static void autokit_decode(const u8 *buf, int size)
{
    int consumed = 0, remaining = size;
    while (remaining > 0) {
        int outsize = 0;
        int n = F.av_parser_parse2(K.parser, K.ctx, (u8 **)((u8 *)K.pkt + 0x18), &outsize,
                                   buf + consumed, remaining, 0, 0, 0);
        consumed += n; remaining -= n;
        if (outsize <= 0) continue;
        I32(K.pkt, 0x1c) = outsize;
        while (I32(K.pkt, 0x1c) > 0) {
            int got = 0;
            int ret = F.avcodec_decode_video2(K.ctx, K.frame, &got, K.pkt);
            if (ret < 0) break;
            if (got) deliver();
            I32(K.pkt, 0x1c) -= ret;
            PTR(K.pkt, 0x18) += ret;
        }
    }
}

int main(int argc, char **argv)
{
    if (argc < 4) { LOG("usage: akdec <dll_dir> <in.h264> <out.yuv|-> [chunk|au] [drain]\n"); return 2; }
    verbose = getenv("AKDEC_VERBOSE") != NULL;
    dll_dir = argv[1];
    int chunk = 4096, au = 0, drain = 0;
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "au")) au = 1;
        else if (!strcmp(argv[i], "drain")) drain = 1;
        else chunk = atoi(argv[i]);
    }

    /* AutoKit load order: avcodec, avutil, avformat (0x2DD60, 0x2DF54, 0x2E08C) */
    struct dll *dc = load_dll("avcodec-56.dll");
    struct dll *du = load_dll("avutil-54.dll");
    struct dll *df = load_dll("avformat-56.dll");
    F.avcodec_register_all = get(dc, "avcodec_register_all");
    F.av_parser_init = get(dc, "av_parser_init");
    F.avcodec_open2 = get(dc, "avcodec_open2");
    F.avcodec_find_decoder = get(dc, "avcodec_find_decoder");
    F.av_free_packet = get(dc, "av_free_packet");
    F.av_init_packet = get(dc, "av_init_packet");
    F.avcodec_alloc_context3 = get(dc, "avcodec_alloc_context3");
    F.avcodec_close = get(dc, "avcodec_close");
    F.avcodec_decode_video2 = get(dc, "avcodec_decode_video2");
    F.av_parser_parse2 = get(dc, "av_parser_parse2");
    F.av_parser_close = get(dc, "av_parser_close");
    F.av_frame_alloc = get(du, "av_frame_alloc");
    F.av_frame_free = get(du, "av_frame_free");
    F.av_free = get(du, "av_free");
    F.av_malloc = get(du, "av_malloc");
    F.av_register_all = get(df, "av_register_all");
    for (int i = 0; i < ndll; i++)
        LOG("akdec: image %s 0x%08x-0x%08x\n", dlls[i].name, (u32)(uintptr_t)dlls[i].base,
            (u32)(uintptr_t)dlls[i].base + dlls[i].size);

    /* 0x2D470 */
    F.av_register_all();
    F.avcodec_register_all();
    K.pkt = F.av_malloc(0x50);
    F.av_init_packet(K.pkt);
    K.frame = F.av_frame_alloc();
    K.codec = F.avcodec_find_decoder(28);
    if (!K.codec) { LOG("akdec: avcodec_find_decoder(H264) NULL -> AutoKit exit(1)\n"); return 1; }
    K.parser = F.av_parser_init(28);
    if (!K.parser) { LOG("akdec: av_parser_init(H264) NULL -> AutoKit exit(1)\n"); return 1; }
    K.ctx = F.avcodec_alloc_context3(K.codec);
    if (I32(K.codec, 0x10) & 8) I32(K.ctx, 0x58) |= 0x10000;
    if (F.avcodec_open2(K.ctx, K.codec, NULL) < 0) { LOG("akdec: avcodec_open2 < 0 -> AutoKit exit(1)\n"); return 1; }

    FILE *in = fopen(argv[2], "rb");
    if (!in) { LOG("akdec: cannot open %s\n", argv[2]); return 2; }
    fseek(in, 0, SEEK_END); long isz = ftell(in); fseek(in, 0, SEEK_SET);
    u8 *data = malloc(isz + 64);
    if (fread(data, 1, isz, in) != (size_t)isz) return 2;
    fclose(in);
    out = strcmp(argv[3], "-") ? fopen(argv[3], "wb") : NULL;

    long calls = 0;
    double t0 = now();
    if (au) {
        /* one call per access unit: split before every access unit delimiter (00 00 00 01 09) */
        long start = 0;
        for (long i = 4; i + 4 < isz; i++) {
            if (data[i] == 0 && data[i + 1] == 0 && data[i + 2] == 0 && data[i + 3] == 1 && (data[i + 4] & 0x1f) == 9) {
                autokit_decode(data + start, (int)(i - start)); calls++; start = i;
            }
        }
        autokit_decode(data + start, (int)(isz - start)); calls++;
    } else {
        for (long off = 0; off < isz; off += chunk) {
            int n = isz - off < chunk ? (int)(isz - off) : chunk;
            /* AutoKit receives each buffer in its own memory; copy so the parser never sees
             * bytes beyond this buffer */
            u8 *b = malloc(n + 64);
            memcpy(b, data + off, n);
            autokit_decode(b, n); calls++;
            free(b);
        }
    }
    long ak_frames = frames_out;
    if (drain) {
        int outsize = 0;
        F.av_parser_parse2(K.parser, K.ctx, (u8 **)((u8 *)K.pkt + 0x18), &outsize, NULL, 0, 0, 0, 0);
        if (outsize > 0) {
            I32(K.pkt, 0x1c) = outsize;
            int got = 0;
            if (F.avcodec_decode_video2(K.ctx, K.frame, &got, K.pkt) >= 0 && got) deliver();
        }
        for (;;) {
            int got = 0;
            PTR(K.pkt, 0x18) = NULL; I32(K.pkt, 0x1c) = 0;
            if (F.avcodec_decode_video2(K.ctx, K.frame, &got, K.pkt) < 0 || !got) break;
            deliver();
        }
    }
    t_decode += now() - t0;

    /* 0x2DC64 */
    F.av_free(K.pkt);
    F.av_frame_free(&K.frame);
    F.av_parser_close(K.parser);
    F.avcodec_close(K.ctx);
    F.av_free(K.ctx);
    if (out) fclose(out);

    LOG("akdec: result calls=%ld frames_autokit_loop=%ld frames_total=%ld size=%dx%d "
        "chroma_stride_mismatch=%ld repacked=%ld decode_seconds=%.3f heap_peak=%ld heap_after_teardown=%ld\n",
        calls, ak_frames, frames_out, out_w, out_h, chroma_stride_mismatch, frames_repacked, t_decode,
        heap_peak, heap_cur);
    return 0;
}
