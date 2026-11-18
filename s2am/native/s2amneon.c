/*
 * s2am NEON check: does this SYNC 2 run NEON code, and do the NEON registers of one thread
 * survive while other threads use them?
 *
 * A decoder built with NEON (FFmpeg's hand-written routines) is about twice as fast in the
 * emulator, but Windows CE 6 on this unit reports no NEON, AutoKit says IsHaveNeon() = 0, and
 * whether the kernel keeps D0-D31 per thread is known only from reading its code. A decoder job
 * planned with --neon-check runs this first and swaps nothing unless it passes.
 *
 * Usage: s2amneon.exe <report file>
 *   The program starts itself again as a child and waits for it, so a child that Windows CE
 *   ends (an undefined instruction) or that hangs still leaves a report and returns.
 *   The child:
 *     instr    NEON arithmetic on Q8-Q10, on the main thread (an undefined instruction ends
 *              the process there, not just a thread)
 *     memory   an unaligned NEON load and store, as the decoder's routines do
 *     threads  THREADS threads, each with its own pattern in all of D0-D31, ROUNDS rounds:
 *              fill, spin longer than a scheduler quantum (or sleep, every other round),
 *              compare. The others run meanwhile with their own patterns.
 *   Only when all of it holds does the child write "<report file>.pass"; the parent removes
 *   that file again unless the child also ended by itself with exit code 0.
 *
 * Report lines: S| start, B| a step begins, R|/W| numbers, E| what failed, K|pass (child),
 * C|exit|<code> and T|pass (parent). Only COREDLL is used.
 */

/* The routines, in ARM assembly so the compiler has no part in which registers are used.
 * s2am_neon_round(seed, spins, call): 0, or 1 + the number of the first D register that did
 * not hold its pattern. D8-D15 are put back as the calling convention wants. */
__asm__(
"   .text\n"
"   .arch armv7-a\n"
"   .fpu neon\n"
"   .arm\n"
"   .align 2\n"
"   .global s2am_neon_instr\n"
"s2am_neon_instr:\n"
"   ldr r0, =0x01020304\n"
"   ldr r1, =0x10203040\n"
"   vdup.32 q8, r0\n"
"   vdup.32 q9, r1\n"
"   vadd.i32 q10, q8, q9\n"
"   vmov.32 r2, d21[1]\n"
"   ldr r3, =0x11223344\n"
"   subs r0, r2, r3\n"
"   movne r0, #1\n"
"   bx lr\n"
"   .ltorg\n"
"   .global s2am_neon_copy\n"
"s2am_neon_copy:\n"            /* (source, target): 16 bytes, each inverted */
"   vld1.8 {d16, d17}, [r0]\n"
"   vmvn q8, q8\n"
"   vst1.8 {d16, d17}, [r1]\n"
"   bx lr\n"
"   .global s2am_neon_round\n"
"s2am_neon_round:\n"
"   push {r4-r8, lr}\n"
"   vpush {d8-d15}\n"
"   mov r7, r0\n"               /* seed */
"   mov r8, r2\n"               /* call, or 0 */
"   ldr r12, =0xa5a5a5a5\n"
"   .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31\n"
"   add r3, r7, #\\n\n"
"   eor r4, r3, r12\n"
"   vmov d\\n, r3, r4\n"
"   .endr\n"
"1: subs r1, r1, #1\n"
"   bne 1b\n"
"   cmp r8, #0\n"
"   blxne r8\n"
"   ldr r12, =0xa5a5a5a5\n"
"   .irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31\n"
"   vmov r5, r6, d\\n\n"
"   add r3, r7, #\\n\n"
"   eor r4, r3, r12\n"
"   cmp r5, r3\n"
"   cmpeq r6, r4\n"
"   movne r0, #(\\n + 1)\n"
"   bne 9f\n"
"   .endr\n"
"   mov r0, #0\n"
"9: vpop {d8-d15}\n"
"   pop {r4-r8, pc}\n"
"   .ltorg\n"
);

extern unsigned s2am_neon_instr(void) __asm__("s2am_neon_instr");
extern void s2am_neon_copy(const unsigned char *source, unsigned char *target) __asm__("s2am_neon_copy");
extern unsigned s2am_neon_round(unsigned seed, unsigned spins, void (*call)(void)) __asm__("s2am_neon_round");

#define THREADS 4
#define ROUNDS 8
#define ROUND_MS 130       /* one spin: longer than Windows CE's 100 ms quantum */

/* 0, or the first of the 16 bytes that did not come back inverted, plus 1. */
static unsigned memory_check(void)
{
    unsigned char source[24], target[24];
    unsigned i;
    for (i = 0; i < sizeof(source); i++) {
        source[i] = (unsigned char)(i * 37 + 11);
        target[i] = 0;
    }
    s2am_neon_copy(source + 1, target + 3);  /* neither is aligned */
    for (i = 0; i < 16; i++)
        if (target[i + 3] != (unsigned char)~source[i + 1])
            return i + 1;
    return 0;
}

#ifndef S2AM_NEON_HOST_TEST
#include <windows.h>

#define CHILD L"--child "
#define CHILD_WAIT_MS 60000
#define THREADS_WAIT_MS 40000

static HANDLE out = INVALID_HANDLE_VALUE;

static BOOL open_report(const WCHAR *path, BOOL fresh)
{
    out = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, fresh ? CREATE_ALWAYS : OPEN_ALWAYS,
                      FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE)
        return FALSE;
    SetFilePointer(out, 0, NULL, FILE_END);
    return TRUE;
}

static void put(const char *text)
{
    DWORD written;
    WriteFile(out, text, (DWORD)strlen(text), &written, NULL);
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
    char digits[9];
    int i;
    for (i = 7; i >= 0; i--, value >>= 4)
        digits[i] = "0123456789abcdef"[value & 15];
    digits[8] = '\0';
    put(digits);
}

/* One whole line, on the disk before the next step runs: that step may end the process. */
static void line(const char *text, const char *name, unsigned long value, BOOL number)
{
    put(text);
    if (name) {
        put("|");
        put(name);
    }
    if (number) {
        put("|");
        put_uint(value);
    }
    put("\r\n");
    FlushFileBuffers(out);
}

/* MortScript passes the parameter string as it is; tolerate surrounding quotes and spaces. */
static WCHAR *argument(WCHAR *text)
{
    WCHAR *end;
    while (*text == L' ' || *text == L'"')
        text++;
    end = text + wcslen(text);
    while (end > text && (end[-1] == L' ' || end[-1] == L'"'))
        *--end = L'\0';
    return text;
}

static BOOL pass_path(const WCHAR *report, WCHAR *path)
{
    if (wcslen(report) + 6 > MAX_PATH)
        return FALSE;
    wcscpy(path, report);
    wcscat(path, L".pass");
    return TRUE;
}

typedef struct {
    unsigned index, spins;
    HANDLE start;
    volatile LONG finished;  /* rounds done */
    unsigned bad;            /* rounds whose registers did not hold */
    unsigned first_bad;      /* 1 + the D register, of the first such round */
    DWORD longest_ms;        /* its longest spinning round, by the clock */
} Worker;

static void nap(void)
{
    Sleep(1);
}

static DWORD WINAPI work(LPVOID parameter)
{
    Worker *worker = (Worker *)parameter;
    unsigned round, result;
    DWORD before, took;
    WaitForSingleObject(worker->start, INFINITE);
    for (round = 0; round < ROUNDS; round++) {
        /* every thread and round its own pattern, 32 apart so no two registers share one */
        unsigned seed = 0x10000000u * (worker->index + 1) + 0x100u * round;
        before = GetTickCount();
        result = s2am_neon_round(seed, worker->spins, round & 1 ? nap : NULL);
        took = GetTickCount() - before;
        if (!(round & 1) && took > worker->longest_ms)
            worker->longest_ms = took;
        if (result) {
            if (!worker->bad)
                worker->first_bad = result;
            worker->bad++;
        }
        worker->finished = (LONG)(round + 1);
    }
    return 0;
}

/* The child's work: 0 only when every check held. */
static int check(const WCHAR *report)
{
    Worker workers[THREADS];
    HANDLE threads[THREADS], start, marker;
    WCHAR pass[MAX_PATH];
    unsigned spins = 1u << 18, i, result;
    DWORD before, took = 0, id, waited;
    BOOL ok = TRUE;

    line("B|instr", NULL, 0, FALSE);
    result = s2am_neon_instr();
    if (result) {
        line("E|instr", NULL, result, TRUE);
        return 2;
    }
    line("B|memory", NULL, 0, FALSE);
    result = memory_check();
    if (result) {
        line("E|memory", NULL, result, TRUE);
        return 3;
    }
    line("B|calibrate", NULL, 0, FALSE);
    for (;;) {  /* how many spins make a round of ROUND_MS on this processor */
        before = GetTickCount();
        result = s2am_neon_round(0x0badc000u, spins, NULL);
        took = GetTickCount() - before;
        if (result) {
            line("E|calibrate", NULL, result, TRUE);
            return 4;
        }
        if (took >= 40 || spins >= (1u << 29))
            break;
        spins *= 2;
    }
    if (took >= 40 && took < ROUND_MS)  /* at most 2^29 / 40 * 130: fits */
        spins = spins / took * ROUND_MS;
    put("R|calibrate|spins|");
    put_uint(spins);
    line("", "measured_ms", took, TRUE);

    line("B|threads", NULL, THREADS, TRUE);
    start = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!start) {
        line("E|event", NULL, GetLastError(), TRUE);
        return 5;
    }
    for (i = 0; i < THREADS; i++) {
        memset(&workers[i], 0, sizeof(workers[i]));
        workers[i].index = i;
        workers[i].spins = spins;
        workers[i].start = start;
        threads[i] = CreateThread(NULL, 0, work, &workers[i], 0, &id);
        if (!threads[i]) {
            line("E|thread", NULL, GetLastError(), TRUE);
            return 6;  /* the process ends here, and its waiting threads with it */
        }
    }
    SetEvent(start);
    before = GetTickCount();
    for (i = 0; i < THREADS; i++) {
        waited = GetTickCount() - before;
        if (WaitForSingleObject(threads[i], waited < THREADS_WAIT_MS ? THREADS_WAIT_MS - waited : 0)
                != WAIT_OBJECT_0)
            ok = FALSE;  /* still running, or ended by Windows CE: its rounds say which */
    }
    for (i = 0; i < THREADS; i++) {
        put("W|");
        put_uint(i);
        put("|rounds|");
        put_uint((unsigned long)workers[i].finished);
        put("|bad|");
        put_uint(workers[i].bad);
        put("|first_bad|");
        put_uint(workers[i].first_bad);
        line("", "longest_ms", workers[i].longest_ms, TRUE);
        if (workers[i].finished != ROUNDS || workers[i].bad)
            ok = FALSE;
    }
    if (!ok) {
        line("E|threads", NULL, 0, FALSE);
        return 7;
    }
    if (!pass_path(report, pass))
        return 8;
    marker = CreateFileW(pass, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (marker == INVALID_HANDLE_VALUE) {
        line("E|pass-file", NULL, GetLastError(), TRUE);
        return 8;
    }
    WriteFile(marker, "pass", 4, &id, NULL);
    CloseHandle(marker);
    line("K|pass", NULL, 0, FALSE);
    return 0;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR self[MAX_PATH], pass[MAX_PATH], child[MAX_PATH + 16], *report;
    PROCESS_INFORMATION process;
    DWORD code = 0xffffffffu;
    BOOL ended;
    int result;
    (void)instance;
    (void)previous;
    (void)show;

    if (!wcsncmp(command, CHILD, wcslen(CHILD))) {
        report = argument(command + wcslen(CHILD));
        if (!open_report(report, FALSE))
            return 1;
        line("B|child", NULL, 0, FALSE);
        result = check(report);
        CloseHandle(out);
        return result;
    }
    report = argument(command);
    if (!*report || !pass_path(report, pass) || wcslen(report) + wcslen(CHILD) >= MAX_PATH + 16)
        return 1;
    DeleteFileW(pass);  /* an earlier run's verdict is not this one's */
    if (!open_report(report, TRUE))
        return 1;
    line("S|s2am-neon-v1", NULL, 0, FALSE);
    if (GetFileAttributesW(pass) != 0xffffffffu) {  /* it would outlive a child that fails */
        line("E|stale-pass", NULL, GetLastError(), TRUE);
        CloseHandle(out);
        return 1;
    }
    CloseHandle(out);  /* the child writes next */
    wcscpy(child, CHILD);
    wcscat(child, report);
    if (!GetModuleFileNameW(NULL, self, MAX_PATH) ||
            !CreateProcessW(self, child, NULL, NULL, FALSE, 0, NULL, NULL, NULL, &process)) {
        code = GetLastError();
        if (open_report(report, FALSE)) {
            line("E|start", NULL, code, TRUE);
            CloseHandle(out);
        }
        return 1;
    }
    ended = WaitForSingleObject(process.hProcess, CHILD_WAIT_MS) == WAIT_OBJECT_0;
    if (!ended) {
        TerminateProcess(process.hProcess, 99);
        WaitForSingleObject(process.hProcess, 5000);
    }
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    if (!ended || code != 0)
        DeleteFileW(pass);
    if (!open_report(report, FALSE))
        return 1;
    if (!ended)
        line("E|timeout", NULL, CHILD_WAIT_MS, TRUE);
    if ((!ended || code != 0) && GetFileAttributesW(pass) != 0xffffffffu)
        line("E|pass-file-stuck", NULL, 0, FALSE);  /* the report, not the file, is the verdict then */
    put("C|exit|");
    put_hex(code);
    put("\r\n");
    result = ended && code == 0 && GetFileAttributesW(pass) != 0xffffffffu ? 0 : 1;
    if (!result)
        line("T|pass", NULL, 0, FALSE);
    CloseHandle(out);
    return result;
}
#endif
