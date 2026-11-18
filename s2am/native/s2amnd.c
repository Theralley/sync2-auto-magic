/* s2amnd: why does NEON code that passes s2amneon still end a program on this car?
 *
 *   s2amnd.exe <report file>
 *
 * It changes nothing on the car. Each question below is one stage, and each stage runs in its
 * own copy of this program so that a stage Windows CE ends does not take the others with it.
 * The first copy is the others' debugger (CreateProcess with DEBUG_PROCESS): when a stage
 * faults it writes down which exception, where, the instruction there and the registers, and
 * then ends that stage itself, so no error box has to be answered on the screen. If this
 * Windows CE does not let a program debug another, the stages still run and only their exit
 * codes are kept.
 *
 * What s2amneon could not tell (its first floating-point instruction in every thread, and
 * after every switch to another thread, was one that the old VFP unit shares with NEON):
 *   - cold-*      the first such instruction a process or a thread runs is a NEON-only one
 *   - xfer-*      another thread took the unit over, and the next instruction is NEON-only
 *   - dp-loop     a thread is switched away from in the middle of NEON-only instructions
 *   - ld32 .. st32-full   NEON loads and stores of 16- and 32-bit elements at addresses that
 *                 are not multiples of the element size (FFmpeg's NEON code does this)
 *   - word        an ordinary 32-bit load at an odd address, for comparison
 *   - q128        a load that promises 16-byte alignment and breaks the promise: this one is
 *                 expected to fault on real hardware, and shows what a fault looks like here
 *   - break       DebugBreak: shows that the debugger sees its stages at all
 *
 * Trial decodes follow the stages when sample.h264 lies next to this program: for AutoKit's
 * own folder ("installed") and for each folder set-<label> next to this program that holds the
 * three decoder files, one more process loads those files and decodes the sample with the
 * calls AutoKit makes, in a thread with AutoKit's 64 KB of stack. Nothing is written but the
 * report. Its lines: L|<file>|<address of one named function> (tells where the file is
 * loaded), P|<frames so far>, R|frames|n|width|w|height|h|sum|<hex>|decode_ms|n, E| an error.
 *
 * Report lines: S| start, D| debugging on or off, G|<stage>|<name> a stage begins,
 * M| a module of the stage and where it is loaded, X| an exception, Y| its registers,
 * Q|<stage>|<name>|<how it ended>|<exit code, hex>, T|complete. A stage's exit code is 0 when
 * what it checked held, 0x100 + n when a value was wrong. Only COREDLL is used.
 */
__asm__(
"   .text\n"
"   .arch armv7-a\n"
"   .fpu neon\n"
"   .arm\n"
"   .align 2\n"
"   .global nd_prime\n"            /* (value): a VFP-encoded instruction; q8 = value x 4 */
"nd_prime:\n"
"   vdup.32 q8, r0\n"
"   bx lr\n"
"   .global nd_dp_first\n"         /* NEON data processing first; returns 0 */
"nd_dp_first:\n"
"   veor q8, q8, q8\n"
"   vmov.32 r0, d16[0]\n"
"   bx lr\n"
"   .global nd_ls_first\n"         /* (source, target): NEON load first; copies 16 bytes */
"nd_ls_first:\n"
"   vld1.8 {d16, d17}, [r0]\n"
"   vst1.8 {d16, d17}, [r1]\n"
"   bx lr\n"
"   .global nd_dp_after\n"         /* after nd_prime(v): NEON data processing first; 2 x v */
"nd_dp_after:\n"
"   vadd.i32 q9, q8, q8\n"
"   vmov.32 r0, d18[0]\n"
"   bx lr\n"
"   .global nd_ls_after\n"         /* (target) after nd_prime(v): NEON store first */
"nd_ls_after:\n"
"   vst1.8 {d16, d17}, [r0]\n"
"   bx lr\n"
"   .global nd_dp_loop\n"          /* (count): only NEON data processing in the loop; count */
"nd_dp_loop:\n"
"   vmov.i32 q8, #0\n"
"   vmov.i32 q9, #1\n"
"1: vadd.i32 q8, q8, q9\n"
"   subs r0, r0, #1\n"
"   bne 1b\n"
"   vmov.32 r0, d16[0]\n"
"   bx lr\n"
"   .global nd_ld32\n"             /* (address): one 32-bit element */
"nd_ld32:\n"
"   vld1.32 {d16[0]}, [r0]\n"
"   vmov.32 r0, d16[0]\n"
"   bx lr\n"
"   .global nd_st32\n"             /* (address, value) */
"nd_st32:\n"
"   vmov.32 d16[0], r1\n"
"   vst1.32 {d16[0]}, [r0]\n"
"   bx lr\n"
"   .global nd_ld16\n"
"nd_ld16:\n"
"   vld1.16 {d16[0]}, [r0]\n"
"   vmov.u16 r0, d16[0]\n"
"   bx lr\n"
"   .global nd_ld32_full\n"        /* (address): 16 bytes as 32-bit elements; the first */
"nd_ld32_full:\n"
"   vld1.32 {d16, d17}, [r0]\n"
"   vmov.32 r0, d16[0]\n"
"   bx lr\n"
"   .global nd_st32_full\n"        /* (address, value): 16 bytes as 32-bit elements */
"nd_st32_full:\n"
"   vdup.32 q8, r1\n"
"   vst1.32 {d16, d17}, [r0]\n"
"   bx lr\n"
"   .global nd_word\n"
"nd_word:\n"
"   ldr r0, [r0]\n"
"   bx lr\n"
"   .global nd_q128\n"             /* (address): promises 16-byte alignment */
"nd_q128:\n"
"   vld1.64 {d16, d17}, [r0,:128]\n"
"   vmov.32 r0, d16[0]\n"
"   bx lr\n"
);

extern void nd_prime(unsigned value) __asm__("nd_prime");
extern unsigned nd_dp_first(void) __asm__("nd_dp_first");
extern void nd_ls_first(const unsigned char *source, unsigned char *target) __asm__("nd_ls_first");
extern unsigned nd_dp_after(void) __asm__("nd_dp_after");
extern void nd_ls_after(unsigned char *target) __asm__("nd_ls_after");
extern unsigned nd_dp_loop(unsigned count) __asm__("nd_dp_loop");
extern unsigned nd_ld32(const unsigned char *address) __asm__("nd_ld32");
extern void nd_st32(unsigned char *address, unsigned value) __asm__("nd_st32");
extern unsigned nd_ld16(const unsigned char *address) __asm__("nd_ld16");
extern unsigned nd_ld32_full(const unsigned char *address) __asm__("nd_ld32_full");
extern void nd_st32_full(unsigned char *address, unsigned value) __asm__("nd_st32_full");
extern unsigned nd_word(const unsigned char *address) __asm__("nd_word");
extern unsigned nd_q128(const unsigned char *address) __asm__("nd_q128");

#define WRONG 0x100  /* a stage's exit code when a value was wrong: WRONG + which */

/* Bytes 0x10, 0x11, ... so a value read at any offset is known. Aligned to 16 by hand. */
static unsigned char block_store[96];
static unsigned char *block(void)
{
    unsigned char *start = block_store;
    unsigned i;
    while ((unsigned long)start & 15)
        start++;
    for (i = 0; i < 64; i++)
        start[i] = (unsigned char)(0x10 + i);
    return start;
}

static unsigned word_at(unsigned offset)  /* what a little-endian 32-bit read there gives */
{
    unsigned first = 0x10 + offset;
    return first | (first + 1) << 8 | (first + 2) << 16 | (first + 3) << 24;
}

static int ls_copy_ok(void)
{
    unsigned char *source = block(), target[16];
    unsigned i;
    for (i = 0; i < 16; i++)
        target[i] = 0;
    nd_ls_first(source + 1, target);
    for (i = 0; i < 16; i++)
        if (target[i] != source[i + 1])
            return 0;
    return 1;
}

static int stage_ld32(unsigned offset)
{
    nd_prime(0);  /* the unit is on: what follows is about the address only */
    return nd_ld32(block() + offset) == word_at(offset) ? 0 : WRONG + offset;
}

static int stage_st32(unsigned offset)
{
    unsigned char *target = block();
    nd_prime(0);
    nd_st32(target + offset, 0xa1b2c3d4u);
    return target[offset] == 0xd4 && target[offset + 3] == 0xa1 ? 0 : WRONG + offset;
}

static int stage_ld16(void)
{
    nd_prime(0);
    return nd_ld16(block() + 1) == 0x1211u ? 0 : WRONG + 1;
}

static int stage_ld32_full(unsigned offset)
{
    nd_prime(0);
    return nd_ld32_full(block() + offset) == word_at(offset) ? 0 : WRONG + offset;
}

static int stage_st32_full(unsigned offset)
{
    unsigned char *target = block();
    nd_prime(0);
    nd_st32_full(target + offset, 0xa1b2c3d4u);
    return target[offset] == 0xd4 && target[offset + 15] == 0xa1 ? 0 : WRONG + offset;
}

#ifndef S2AM_ND_HOST_TEST
#include <windows.h>

#define STAGE L"--stage "
#define DECODE L"--decode "
#define WATCH L"--watch "
#define DECODE_COPY 32768  /* most of a trial decode's own lines that go into the report */
#define SILENT_MS 10000  /* a watched stage that reports nothing at all for this long is given up */
#define STAGE_WAIT_MS 25000
#define XFERS 200
#define LOOP_MS 400
#define LOOP_ROUNDS 3
#define BREAK_LIMIT 4

/* ---- the stages (each in its own process) ---- */

static DWORD WINAPI cold_thread_dp(LPVOID unused)
{
    (void)unused;
    return nd_dp_first() == 0 ? 0 : WRONG + 1;
}

static DWORD WINAPI cold_thread_ls(LPVOID unused)
{
    (void)unused;
    return ls_copy_ok() ? 0 : WRONG + 1;
}

static int in_thread(LPTHREAD_START_ROUTINE routine)
{
    DWORD id, code = WRONG + 2;
    HANDLE thread = CreateThread(NULL, 0, routine, NULL, 0, &id);
    if (!thread)
        return WRONG + 3;
    if (WaitForSingleObject(thread, 10000) == WAIT_OBJECT_0)
        GetExitCodeThread(thread, &code);
    CloseHandle(thread);
    return (int)code;
}

static HANDLE to_other, to_main;
static volatile LONG stop;

static DWORD WINAPI taker(LPVOID unused)  /* takes the unit over whenever it is asked to */
{
    unsigned turn = 0;
    (void)unused;
    for (;;) {
        WaitForSingleObject(to_other, INFINITE);
        if (stop)
            return 0;
        nd_prime(0x55550000u + turn++);
        SetEvent(to_main);
    }
}

static int transfer(int store)
{
    unsigned char target[16];
    unsigned i, wrong = 0;
    DWORD id;
    HANDLE thread;
    to_other = CreateEventW(NULL, FALSE, FALSE, NULL);
    to_main = CreateEventW(NULL, FALSE, FALSE, NULL);
    thread = to_other && to_main ? CreateThread(NULL, 0, taker, NULL, 0, &id) : NULL;
    if (!thread)
        return WRONG + 0xff;
    for (i = 0; i < XFERS; i++) {
        unsigned value = 0x01000000u + i;
        nd_prime(value);
        SetEvent(to_other);
        if (WaitForSingleObject(to_main, 5000) != WAIT_OBJECT_0)
            return WRONG + 0xfe;
        if (store) {
            nd_ls_after(target);
            if (target[0] != (unsigned char)value || target[3] != 0x01 || target[12] != (unsigned char)value)
                wrong++;
        } else if (nd_dp_after() != 2 * value) {
            wrong++;
        }
    }
    stop = 1;
    SetEvent(to_other);
    WaitForSingleObject(thread, 2000);
    return wrong ? WRONG + (wrong > 0xf0 ? 0xf0 : wrong) : 0;
}

static unsigned loop_count;

static DWORD WINAPI looper(LPVOID unused)
{
    unsigned round, wrong = 0;
    (void)unused;
    for (round = 0; round < LOOP_ROUNDS; round++)
        if (nd_dp_loop(loop_count) != loop_count)
            wrong++;
    return wrong;
}

static DWORD WINAPI spinner(LPVOID unused)  /* keeps taking the unit, with a VFP-encoded instruction */
{
    unsigned turn = 0;
    (void)unused;
    while (!stop)
        nd_prime(turn++);
    return 0;
}

static int dp_loop(void)
{
    HANDLE loopers[2], spin;
    DWORD id, before, took, code, wrong = 0;
    unsigned i;
    loop_count = 1u << 18;
    for (;;) {  /* how many turns make LOOP_MS on this processor */
        before = GetTickCount();
        if (nd_dp_loop(loop_count) != loop_count)
            return WRONG + 0xfd;
        took = GetTickCount() - before;
        if (took >= 40 || loop_count >= (1u << 28))
            break;
        loop_count *= 2;
    }
    if (took >= 40 && took < LOOP_MS)
        loop_count = loop_count / took * LOOP_MS;
    spin = CreateThread(NULL, 0, spinner, NULL, 0, &id);
    loopers[0] = CreateThread(NULL, 0, looper, NULL, 0, &id);
    loopers[1] = CreateThread(NULL, 0, looper, NULL, 0, &id);
    if (!spin || !loopers[0] || !loopers[1])
        return WRONG + 0xff;
    for (i = 0; i < 2; i++) {
        code = 0xee;
        if (WaitForSingleObject(loopers[i], 15000) == WAIT_OBJECT_0)
            GetExitCodeThread(loopers[i], &code);
        wrong += code;
    }
    stop = 1;
    WaitForSingleObject(spin, 2000);
    return wrong ? WRONG + (wrong > 0xf0 ? 0xf0 : (int)wrong) : 0;
}

typedef struct {
    const char *name;
    int expect_fault;  /* 1: a fault is the expected answer on real hardware */
} Stage;

static const Stage stages[] = {
    {"break", 1},          /* 0 */
    {"cold-dp", 0},        /* 1 */
    {"cold-ls", 0},        /* 2 */
    {"cold-thread-dp", 0}, /* 3 */
    {"cold-thread-ls", 0}, /* 4 */
    {"xfer-dp", 0},        /* 5 */
    {"xfer-ls", 0},        /* 6 */
    {"dp-loop", 0},        /* 7 */
    {"ld32-off2", 0},      /* 8 */
    {"ld32-off1", 0},      /* 9 */
    {"st32-off2", 0},      /* 10 */
    {"st32-off1", 0},      /* 11 */
    {"ld16-off1", 0},      /* 12 */
    {"ld32-full-off4", 0}, /* 13 */
    {"ld32-full-off1", 0}, /* 14 */
    {"st32-full-off1", 0}, /* 15 */
    {"word-off1", 0},      /* 16 */
    {"q128-off8", 1},      /* 17 */
};
#define STAGES (sizeof(stages) / sizeof(stages[0]))

static int run_stage(unsigned number)
{
    switch (number) {
    case 0: DebugBreak(); return 0;
    case 1: return nd_dp_first() == 0 ? 0 : WRONG + 1;
    case 2: return ls_copy_ok() ? 0 : WRONG + 1;
    case 3: return in_thread(cold_thread_dp);
    case 4: return in_thread(cold_thread_ls);
    case 5: return transfer(0);
    case 6: return transfer(1);
    case 7: return dp_loop();
    case 8: return stage_ld32(2);
    case 9: return stage_ld32(1);
    case 10: return stage_st32(2);
    case 11: return stage_st32(1);
    case 12: return stage_ld16();
    case 13: return stage_ld32_full(4);
    case 14: return stage_ld32_full(1);
    case 15: return stage_st32_full(1);
    case 16: return nd_word(block() + 1) == word_at(1) ? 0 : WRONG + 1;
    case 17: nd_prime(0); return nd_q128(block() + 8) == word_at(8) ? 0 : WRONG + 8;
    }
    return WRONG + 0xfc;
}

/* ---- the report ---- */

static HANDLE out = INVALID_HANDLE_VALUE;

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
    char digits[10];
    int i;
    digits[0] = '|';
    for (i = 8; i >= 1; i--, value >>= 4)
        digits[i] = "0123456789abcdef"[value & 15];
    digits[9] = '\0';
    put(digits);
}

static void end_line(void)  /* on the disk before the next step: that step may end everything */
{
    put("\r\n");
    FlushFileBuffers(out);
}

/* ---- a trial decode (in its own process) ---- */

#define AUTOKIT L"\\SyncExtendedPack\\Apps\\Media\\AutoKit"
#define SAMPLE L"sample.h264"
#define DECODE_STACK 0x10000  /* what AutoKit.exe gives each of its threads */
#define DECODE_WAIT_MS 180000
#define CHUNK 4096
#ifndef STACK_SIZE_PARAM_IS_A_RESERVATION
#define STACK_SIZE_PARAM_IS_A_RESERVATION 0x00010000
#endif
#define I32(p, offset) (*(int *)((unsigned char *)(p) + (offset)))
#define PTR(p, offset) (*(unsigned char **)((unsigned char *)(p) + (offset)))

static struct {  /* the functions AutoKit looks up, in FFmpeg 2.6's layout */
    void (*av_register_all)(void);
    void (*avcodec_register_all)(void);
    void *(*av_malloc)(unsigned);
    void (*av_init_packet)(void *);
    void *(*av_frame_alloc)(void);
    void *(*avcodec_find_decoder)(int);
    void *(*av_parser_init)(int);
    void *(*avcodec_alloc_context3)(void *);
    int (*avcodec_open2)(void *, void *, void *);
    int (*av_parser_parse2)(void *, void *, unsigned char **, int *, const unsigned char *, int,
                            long long, long long, long long);
    int (*avcodec_decode_video2)(void *, void *, int *, void *);
} ff;

static WCHAR folder[MAX_PATH];   /* the decoder files */
static WCHAR beside[MAX_PATH];   /* this program's folder */
static unsigned long frames, sum = 2166136261ul, deliver_ms;
static int width, height;

static void sum_rows(const unsigned char *row, int stride, int count, int rows)
{
    int x;
    for (; rows > 0; rows--, row += stride)
        for (x = 0; x < count; x++)
            sum = (sum ^ row[x]) * 16777619ul;
}

/* What AutoKit takes from a frame: its chroma stride is half the luma stride, or half the
 * width when the luma stride is the width. */
static void deliver(void *context, void *frame)
{
    DWORD before = GetTickCount();
    int stride = I32(frame, 0x20);
    width = I32(context, 0x78);
    height = I32(context, 0x7c);
    if (stride <= width)
        stride = width;
    sum_rows(PTR(frame, 0), stride, width, height);
    sum_rows(PTR(frame, 4), stride / 2, width / 2, height / 2);
    sum_rows(PTR(frame, 8), stride / 2, width / 2, height / 2);
    frames++;
    if (frames % 10 == 0) {
        put("P|");
        put_uint(frames);
        end_line();
    }
    deliver_ms += GetTickCount() - before;
}

static FARPROC named(HMODULE module, const WCHAR *name, const char *file, int tell)
{
    FARPROC address = GetProcAddressW(module, name);
    if (tell) {
        put("L|");
        put(file);
        put_hex((unsigned long)address);
        end_line();
    }
    return address;
}

static HMODULE load(const WCHAR *name)
{
    WCHAR path[MAX_PATH];
    if (wcslen(folder) + wcslen(name) + 2 > MAX_PATH)
        return NULL;
    wcscpy(path, folder);
    wcscat(path, L"\\");
    wcscat(path, name);
    return LoadLibraryW(path);
}

static DWORD fail(const char *what)
{
    put("E|");
    put(what);
    put("|");
    put_uint(GetLastError());
    end_line();
    return 2;
}

static DWORD WINAPI decode_thread(LPVOID unused)
{
    WCHAR path[MAX_PATH];
    HMODULE util, codec, format;
    HANDLE file;
    unsigned char *data, *piece;
    void *packet, *frame, *decoder, *parser, *context;
    DWORD size, got, started, offset;
    (void)unused;

    /* avutil first and by its full path, so the other two find this one and no other */
    util = load(L"avutil-54.dll");
    codec = util ? load(L"avcodec-56.dll") : NULL;
    format = codec ? load(L"avformat-56.dll") : NULL;
    if (!format)
        return fail(!util ? "load-avutil" : !codec ? "load-avcodec" : "load-avformat");
    ff.av_malloc = (void *)named(util, L"av_malloc", "avutil", 1);
    ff.av_frame_alloc = (void *)named(util, L"av_frame_alloc", "avutil", 0);
    ff.avcodec_register_all = (void *)named(codec, L"avcodec_register_all", "avcodec", 1);
    ff.av_init_packet = (void *)named(codec, L"av_init_packet", "avcodec", 0);
    ff.avcodec_find_decoder = (void *)named(codec, L"avcodec_find_decoder", "avcodec", 0);
    ff.av_parser_init = (void *)named(codec, L"av_parser_init", "avcodec", 0);
    ff.avcodec_alloc_context3 = (void *)named(codec, L"avcodec_alloc_context3", "avcodec", 0);
    ff.avcodec_open2 = (void *)named(codec, L"avcodec_open2", "avcodec", 0);
    ff.av_parser_parse2 = (void *)named(codec, L"av_parser_parse2", "avcodec", 0);
    ff.avcodec_decode_video2 = (void *)named(codec, L"avcodec_decode_video2", "avcodec", 0);
    ff.av_register_all = (void *)named(format, L"av_register_all", "avformat", 1);
    if (!ff.av_malloc || !ff.av_frame_alloc || !ff.avcodec_register_all || !ff.av_init_packet
            || !ff.avcodec_find_decoder || !ff.av_parser_init || !ff.avcodec_alloc_context3
            || !ff.avcodec_open2 || !ff.av_parser_parse2 || !ff.avcodec_decode_video2 || !ff.av_register_all)
        return fail("functions");

    wcscpy(path, beside);
    wcscat(path, L"\\" SAMPLE);
    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return fail("sample");
    size = GetFileSize(file, NULL);
    data = size && size < 16ul * 1024 * 1024 ? malloc(size) : NULL;
    piece = malloc(CHUNK + 64);
    if (!data || !piece || !ReadFile(file, data, size, &got, NULL) || got != size)
        return fail("sample-read");
    CloseHandle(file);

    put("B|open");
    end_line();
    ff.av_register_all();
    ff.avcodec_register_all();
    packet = ff.av_malloc(0x50);
    if (!packet)
        return fail("packet");
    ff.av_init_packet(packet);
    frame = ff.av_frame_alloc();
    decoder = ff.avcodec_find_decoder(28);  /* H.264 */
    parser = decoder ? ff.av_parser_init(28) : NULL;
    context = parser ? ff.avcodec_alloc_context3(decoder) : NULL;
    if (!frame || !context)
        return fail("decoder");
    if (I32(decoder, 0x10) & 8)
        I32(context, 0x58) |= 0x10000;
    if (ff.avcodec_open2(context, decoder, NULL) < 0)
        return fail("open");

    put("B|decode");
    end_line();
    started = GetTickCount();
    for (offset = 0; offset < size; offset += CHUNK) {
        int left = (int)(size - offset < CHUNK ? size - offset : CHUNK), used = 0;
        memcpy(piece, data + offset, (unsigned)left);  /* each buffer in memory of its own, as AutoKit gets them */
        memset(piece + left, 0, 64);
        while (left > 0) {
            int found = 0, count;
            count = ff.av_parser_parse2(parser, context, (unsigned char **)((unsigned char *)packet + 0x18),
                                        &found, piece + used, left, 0, 0, 0);
            used += count;
            left -= count;
            if (found <= 0)
                continue;
            I32(packet, 0x1c) = found;
            while (I32(packet, 0x1c) > 0) {
                int have = 0, taken = ff.avcodec_decode_video2(context, frame, &have, packet);
                if (taken < 0)
                    break;
                if (have)
                    deliver(context, frame);
                I32(packet, 0x1c) -= taken;
                PTR(packet, 0x18) += taken;
            }
        }
    }
    got = GetTickCount() - started;
    put("R|frames|");
    put_uint(frames);
    put("|width|");
    put_uint((unsigned long)width);
    put("|height|");
    put_uint((unsigned long)height);
    put("|sum");
    put_hex(sum);
    put("|decode_ms|");
    put_uint(got - deliver_ms);
    end_line();
    return frames ? 0 : WRONG + 1;
}

/* This program's folder; FALSE when it cannot be told, or is too long to add a file name to. */
static BOOL beside_self(void)
{
    WCHAR *slash;
    DWORD length = GetModuleFileNameW(NULL, beside, MAX_PATH);
    beside[MAX_PATH - 1] = L'\0';
    slash = length && length < MAX_PATH ? wcsrchr(beside, L'\\') : NULL;
    if (!slash)
        return FALSE;
    *slash = L'\0';
    return wcslen(beside) + 24 <= MAX_PATH;  /* room for \decode-<12>.txt and \sample.h264 */
}

/* label: "installed", or the <label> of a folder set-<label> next to this program. */
static BOOL set_folder(const WCHAR *label)
{
    if (!wcscmp(label, L"installed")) {
        wcscpy(folder, AUTOKIT);
        return TRUE;
    }
    if (wcslen(beside) + wcslen(label) + 6 > MAX_PATH)
        return FALSE;
    wcscpy(folder, beside);
    wcscat(folder, L"\\set-");
    wcscat(folder, label);
    return TRUE;
}

static BOOL result_path(const WCHAR *label, WCHAR *path)
{
    if (wcslen(beside) + wcslen(label) + 16 > MAX_PATH)
        return FALSE;
    wcscpy(path, beside);
    wcscat(path, L"\\decode-");
    wcscat(path, label);
    wcscat(path, L".txt");
    return TRUE;
}

static int decode(const WCHAR *label)
{
    WCHAR path[MAX_PATH];
    HANDLE thread;
    DWORD id, code = WRONG + 2;
    if (!beside_self() || !set_folder(label) || !result_path(label, path))
        return WRONG + 3;
    out = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE)
        return WRONG + 4;
    thread = CreateThread(NULL, DECODE_STACK, decode_thread, NULL, STACK_SIZE_PARAM_IS_A_RESERVATION, &id);
    if (!thread)
        return (int)fail("thread");
    if (WaitForSingleObject(thread, INFINITE) == WAIT_OBJECT_0)
        GetExitCodeThread(thread, &code);
    CloseHandle(out);
    return (int)code;  /* the process ends here, without unloading the files first */
}

/* ---- the debugger ---- */

#define THREAD_SLOTS 16
static BOOL unconfirmed;  /* a stage did not end when told to: no further stage is started */
static DWORD thread_ids[THREAD_SLOTS];
static HANDLE thread_handles[THREAD_SLOTS];

static void remember(DWORD id, HANDLE handle)
{
    unsigned i;
    for (i = 0; i < THREAD_SLOTS; i++)
        if (!thread_ids[i]) {
            thread_ids[i] = id;
            thread_handles[i] = handle;
            return;
        }
}

static HANDLE thread_of(DWORD id)
{
    unsigned i;
    for (i = 0; i < THREAD_SLOTS; i++)
        if (thread_ids[i] == id)
            return thread_handles[i];
    return NULL;
}

/* X|code|address|first chance|parameters...   Y|pc|opcode|psr|sp|lr|r0..r12
 * Returns the thread's context in *context when it could be read. */
static BOOL describe(HANDLE process, const DEBUG_EVENT *event, CONTEXT *context)
{
    const EXCEPTION_RECORD *record = &event->u.Exception.ExceptionRecord;
    HANDLE thread = thread_of(event->dwThreadId);
    DWORD opcode = 0, got = 0, i;
    BOOL have;
    put("X");
    put_hex(record->ExceptionCode);
    put_hex((unsigned long)record->ExceptionAddress);
    put_hex(event->u.Exception.dwFirstChance);
    for (i = 0; i < record->NumberParameters && i < 4; i++)
        put_hex(record->ExceptionInformation[i]);
    end_line();
    memset(context, 0, sizeof(*context));
    context->ContextFlags = CONTEXT_FULL;
    have = thread && GetThreadContext(thread, context);
    if (!have) {
        put("Y|none");
        put_hex(GetLastError());
        end_line();
        return FALSE;
    }
    if (!ReadProcessMemory(process, (LPCVOID)context->Pc, &opcode, 4, &got) || got != 4)
        opcode = 0xffffffffu;
    put("Y");
    put_hex(context->Pc);
    put_hex(opcode);
    put_hex(context->Psr);
    put_hex(context->Sp);
    put_hex(context->Lr);
    put_hex(context->R0); put_hex(context->R1); put_hex(context->R2); put_hex(context->R3);
    put_hex(context->R4); put_hex(context->R5); put_hex(context->R6); put_hex(context->R7);
    put_hex(context->R8); put_hex(context->R9); put_hex(context->R10); put_hex(context->R11);
    put_hex(context->R12);
    end_line();
    return TRUE;
}

/* Runs one stage. how: "exit" it ended by itself, "fault" it faulted and was ended here,
 * "break" (stage 0 only) the breakpoint was seen, "timeout", "start" it did not start,
 * "silent" not one debug event came from it, "stuck" it did not end when told to. */
static const char *debug_stage(const WCHAR *self, WCHAR *command, unsigned number, DWORD flags, DWORD wait,
                               DWORD *code)
{
    PROCESS_INFORMATION process;
    DEBUG_EVENT event;
    CONTEXT context;
    const char *how = "timeout";
    DWORD started = GetTickCount(), breaks = 0, asked = 0;
    BOOL ending = FALSE, gone = FALSE, seen = FALSE;
    unsigned i, quiet = 0;

    *code = 0xffffffffu;
    memset(thread_ids, 0, sizeof(thread_ids));
    if (!CreateProcessW(self, command, NULL, NULL, FALSE, flags, NULL, NULL, NULL, &process)) {
        *code = GetLastError();
        return "start";
    }
    if (!flags) {  /* no debugging on this Windows CE: the exit code is all there is */
        if (WaitForSingleObject(process.hProcess, wait) == WAIT_OBJECT_0) {
            how = "exit";
        } else {
            TerminateProcess(process.hProcess, 0xdead0000u + number);
            if (WaitForSingleObject(process.hProcess, 5000) != WAIT_OBJECT_0) {
                unconfirmed = TRUE;
                how = "stuck";
            }
        }
        GetExitCodeProcess(process.hProcess, code);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        return how;
    }
    remember(process.dwThreadId, process.hThread);
    while (!gone) {
        DWORD waited = GetTickCount() - started;
        if (!seen && wait > SILENT_MS && waited >= SILENT_MS)
            wait = SILENT_MS;
        if (!ending && waited >= wait) {
            TerminateProcess(process.hProcess, 0xdead0000u + number);
            ending = TRUE;
        }
        if (ending && !asked)
            asked = GetTickCount();  /* also when a fault below asked for the end */
        if (ending && GetTickCount() - asked >= 5000)
            break;  /* it does not even end when told to */
        if (!WaitForDebugEvent(&event, 500)) {
            /* ended, and no event says so: take the exit code from the process itself */
            if (WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0 && ++quiet >= 2) {
                GetExitCodeProcess(process.hProcess, code);
                put("N|unseen");
                end_line();
                if (!ending)
                    how = "exit";
                gone = TRUE;
            }
            continue;
        }
        quiet = 0;
        if (event.dwProcessId != process.dwProcessId) {  /* not this stage's: let it go on, act on nothing */
            ContinueDebugEvent(event.dwProcessId, event.dwThreadId, DBG_CONTINUE);
            continue;
        }
        seen = TRUE;
        switch (event.dwDebugEventCode) {
        case CREATE_PROCESS_DEBUG_EVENT:
            put("M|exe");
            put_hex((unsigned long)event.u.CreateProcessInfo.lpBaseOfImage);
            end_line();
            break;
        case CREATE_THREAD_DEBUG_EVENT:
            remember(event.dwThreadId, event.u.CreateThread.hThread);
            break;
        case LOAD_DLL_DEBUG_EVENT:
            put("M|dll");
            put_hex((unsigned long)event.u.LoadDll.lpBaseOfDll);
            end_line();
            break;
        case EXCEPTION_DEBUG_EVENT:
            if (ending)
                break;
            if (describe(process.hProcess, &event, &context)
                    && event.u.Exception.ExceptionRecord.ExceptionCode == EXCEPTION_BREAKPOINT
                    && number != 0 && ++breaks <= BREAK_LIMIT) {
                HANDLE thread = thread_of(event.dwThreadId);
                context.Pc += 4;  /* a breakpoint that is not ours: step over it and go on */
                context.ContextFlags = CONTEXT_CONTROL;
                if (SetThreadContext(thread, &context))
                    break;
            }
            how = number == 0 && event.u.Exception.ExceptionRecord.ExceptionCode == EXCEPTION_BREAKPOINT
                ? "break" : "fault";
            TerminateProcess(process.hProcess, 0xdead0000u + number);
            ending = TRUE;
            break;
        case EXIT_PROCESS_DEBUG_EVENT:
            *code = event.u.ExitProcess.dwExitCode;
            if (!ending)
                how = "exit";
            gone = TRUE;
            break;
        default:
            break;
        }
        if (!ContinueDebugEvent(event.dwProcessId, event.dwThreadId, DBG_CONTINUE)) {
            put("N|continue");
            put_hex(GetLastError());
            end_line();
        }
    }
    for (i = 0; i < THREAD_SLOTS; i++)
        if (thread_ids[i] && thread_handles[i] != process.hThread)
            CloseHandle(thread_handles[i]);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    if (!gone) {  /* it never ended: its late events must not be taken for a later stage's */
        unconfirmed = TRUE;
        return seen ? "stuck" : "silent";
    }
    if (!seen && !strcmp(how, "timeout"))
        return "silent";  /* ended only because it was told to, and never reported a thing */
    return how;
}

static WCHAR *argument(WCHAR *text)  /* MortScript passes the string as it is */
{
    WCHAR *end;
    while (*text == L' ' || *text == L'"')
        text++;
    end = text + wcslen(text);
    while (end > text && (end[-1] == L' ' || end[-1] == L'"'))
        *--end = L'\0';
    return text;
}

static BOOL exists(const WCHAR *path)
{
    return GetFileAttributesW(path) != 0xffffffffu;
}

/* Copies what a trial decode wrote into the report, and removes its file. */
static void take_over(const WCHAR *path, DWORD left)
{
    char text[512];
    DWORD got, wrote;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return;
    while (left && ReadFile(file, text, left < sizeof(text) ? left : sizeof(text), &got, NULL) && got) {
        WriteFile(out, text, got, &wrote, NULL);
        left -= got;
    }
    CloseHandle(file);
    FlushFileBuffers(out);
    DeleteFileW(path);
}

static BOOL watch_path(WCHAR *path)
{
    if (wcslen(beside) + 12 > MAX_PATH)
        return FALSE;
    wcscpy(path, beside);
    wcscat(path, L"\\watch.txt");
    return TRUE;
}

static void put_wide(const WCHAR *text)
{
    char one[2] = {0, 0};
    for (; *text; text++) {
        one[0] = (char)*text;
        put(one);
    }
}

static void result_line(const char *letter, unsigned number, const char *name, const WCHAR *label,
                        const char *how, DWORD code)
{
    put(letter);
    put("|");
    put_uint(number);
    put("|");
    if (label) {
        put("decode-");
        put_wide(label);
    } else {
        put(name);
    }
    put("|");
    put(how);
    put_hex(code);
    end_line();
}

static void child_command(WCHAR *child, unsigned number, const WCHAR *label)
{
    if (label) {
        wcscpy(child, DECODE);
        wcscat(child, label);
        return;
    }
    wcscpy(child, STAGE);
    child[wcslen(STAGE)] = (WCHAR)(L'0' + number / 10);
    child[wcslen(STAGE) + 1] = (WCHAR)(L'0' + number % 10);
    child[wcslen(STAGE) + 2] = L'\0';
}

/* "--watch NN" or "--watch NN label": a process of its own that debugs one stage or one trial
 * decode and writes what it saw to watch.txt. On the car a second stage debugged by the same
 * process gave no events at all, so every stage gets a fresh debugger.
 * Ends with 1 exit, 2 fault, 3 break, 4 anything else, 5 the stage did not end when told to;
 * 0 means it never got to its result line. */
static int watch(WCHAR *text)
{
    WCHAR self[MAX_PATH], path[MAX_PATH], result[MAX_PATH], child[64], *label;
    const char *how;
    DWORD code;
    unsigned number;
    for (number = 0; *text >= L'0' && *text <= L'9'; text++)
        number = number * 10 + (unsigned)(*text - L'0');
    label = argument(text);
    if (!*label)
        label = NULL;
    if (!beside_self() || !watch_path(path) || !GetModuleFileNameW(NULL, self, MAX_PATH))
        return 0;
    if (label ? wcslen(label) > 12 || !result_path(label, result) : number >= STAGES)
        return 0;
    out = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE)
        return 0;
    child_command(child, number, label);
    how = debug_stage(self, child, number, DEBUG_PROCESS | DEBUG_ONLY_THIS_PROCESS,
                      label ? DECODE_WAIT_MS : STAGE_WAIT_MS, &code);
    if (label)
        take_over(result, DECODE_COPY);
    result_line("Q", number, label ? NULL : stages[number].name, label, how, code);
    CloseHandle(out);
    if (unconfirmed)
        return 5;  /* the stage may still be there; it goes when this debugger process ends */
    return !strcmp(how, "exit") ? 1 : !strcmp(how, "fault") ? 2 : !strcmp(how, "break") ? 3 : 4;
}

/* Starts the watcher for one stage and copies what it wrote into the report. */
static DWORD watched(const WCHAR *self, unsigned number, const WCHAR *label, DWORD wait)
{
    WCHAR command[64], path[MAX_PATH];
    PROCESS_INFORMATION process;
    DWORD code = 0;
    if (!watch_path(path))
        return 0;
    DeleteFileW(path);
    wcscpy(command, WATCH);
    command[wcslen(WATCH)] = (WCHAR)(L'0' + number / 10);
    command[wcslen(WATCH) + 1] = (WCHAR)(L'0' + number % 10);
    command[wcslen(WATCH) + 2] = L'\0';
    if (label) {
        wcscat(command, L" ");
        wcscat(command, label);
    }
    if (!CreateProcessW(self, command, NULL, NULL, FALSE, 0, NULL, NULL, NULL, &process))
        return 0;
    if (WaitForSingleObject(process.hProcess, wait + 20000) == WAIT_OBJECT_0) {
        GetExitCodeProcess(process.hProcess, &code);
        if (code > 5)
            code = 0;
    } else {
        TerminateProcess(process.hProcess, 0);
        if (WaitForSingleObject(process.hProcess, 5000) != WAIT_OBJECT_0)
            unconfirmed = TRUE;  /* a watcher that stays: nothing more is started */
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    take_over(path, DECODE_COPY + 4096);
    if (code == 5) {
        put("N|survivor");
        end_line();
        Sleep(1000);  /* its debugger is gone now, and the system ends the stage with it */
    }
    return code;
}

/* One stage or trial decode: watched when debugging works here; when the watcher did not get
 * an answer, once more without it (line Z), which still tells whether it runs to the end. */
static void one(const WCHAR *self, unsigned number, const WCHAR *label, BOOL *debug)
{
    WCHAR child[64], path[MAX_PATH];
    const char *name = label ? NULL : stages[number].name, *how;
    DWORD wait = label ? DECODE_WAIT_MS : STAGE_WAIT_MS, code, result = 0;
    if (unconfirmed || (label && (wcslen(label) > 12 || !result_path(label, path))))
        return;
    put("G|");
    put_uint(number);
    put("|");
    if (label) {
        put("decode-");
        put_wide(label);
    } else {
        put(name);
    }
    end_line();
    if (label)
        DeleteFileW(path);
    if (*debug) {
        result = watched(self, number, label, wait);
        if (!result)
            result_line("Q", number, name, label, "lost", 0xffffffffu);
    }
    if (number == 0 && !label) {  /* the first stage also tells whether debugging works here */
        if (result != 3)
            *debug = FALSE;  /* DebugBreak is not run again without a debugger */
        put(*debug ? "D|debug|1" : "D|debug|0");
        end_line();
        return;
    }
    if (result == 1 || result == 2 || unconfirmed)
        return;
    child_command(child, number, label);
    if (label)
        DeleteFileW(path);
    how = debug_stage(self, child, number, 0, wait, &code);
    if (label)
        take_over(path, DECODE_COPY);
    result_line(*debug || result ? "Z" : "Q", number, name, label, how, code);
}

/* The files AutoKit has now, then every set-<label> folder next to this program. */
static void decodes(const WCHAR *self, BOOL *debug, unsigned number)
{
    WCHAR pattern[MAX_PATH], path[MAX_PATH];
    WIN32_FIND_DATAW found;
    HANDLE search;
    wcscpy(path, beside);
    wcscat(path, L"\\" SAMPLE);
    if (!exists(path))
        return;  /* a job without trial decodes */
    if (exists(AUTOKIT L"\\avcodec-56.dll"))
        one(self, number++, L"installed", debug);
    wcscpy(pattern, beside);
    wcscat(pattern, L"\\set-*");
    search = FindFirstFileW(pattern, &found);
    if (search == INVALID_HANDLE_VALUE)
        return;
    do {
        if ((found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && wcslen(found.cFileName) > 4
                && wcscmp(found.cFileName + 4, L"installed"))  /* that name means AutoKit's own folder */
            one(self, number++, found.cFileName + 4, debug);
    } while (FindNextFileW(search, &found));
    FindClose(search);
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR self[MAX_PATH], *report;
    BOOL debug = TRUE;
    unsigned number;
    (void)instance;
    (void)previous;
    (void)show;

    if (!wcsncmp(command, STAGE, wcslen(STAGE))) {
        WCHAR *digits = command + wcslen(STAGE);
        for (number = 0; *digits >= L'0' && *digits <= L'9'; digits++)
            number = number * 10 + (unsigned)(*digits - L'0');
        return run_stage(number);
    }
    if (!wcsncmp(command, DECODE, wcslen(DECODE)))
        return decode(argument(command + wcslen(DECODE)));
    if (!wcsncmp(command, WATCH, wcslen(WATCH)))
        return watch(command + wcslen(WATCH));
    report = argument(command);
    if (!*report || !GetModuleFileNameW(NULL, self, MAX_PATH) || !beside_self())
        return 1;
    out = CreateFileW(report, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE)
        return 1;
    put("S|s2am-nd-v1");
    end_line();
    for (number = 0; number < STAGES; number++)
        one(self, number, NULL, &debug);
    decodes(self, &debug, number);
    put(unconfirmed ? "T|stopped" : "T|complete");
    end_line();
    CloseHandle(out);
    return 0;
}
#endif
