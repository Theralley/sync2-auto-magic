/*
 * akprof - qemu 7.2 TCG plugin used by the AutoKit FFmpeg DLL tests.
 *
 *   qemu-arm -cpu cortex-a8 -plugin ./akprof.so,range=0x6f680000:0x6f7f5000:avcodec,align=1 ...
 *
 * range=LO:HI:NAME  (repeatable, max 8) address ranges to account for (the loaded DLL images)
 * hist=PATH         write per-instruction execution counts for the FIRST range to PATH
 *                   ("hexaddr count" lines), for a per-function profile.
 * align=1           also check every load/store executed by code inside a range and report
 *                   accesses whose address is not a multiple of the access size. This is the
 *                   behaviour of an ARM core with SCTLR.A=1 (alignment faults on), which is what
 *                   a Windows CE "datatype misalignment" exception would correspond to.
 *
 * Output (qemu_plugin_outs -> stderr): executed guest instructions per range and in total, and
 * for align=1 the number of unaligned accesses plus up to 4096 distinct faulting PCs.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <glib.h>
#include "qemu-plugin.h"

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;

#define MAXR 8
static struct { uint64_t lo, hi; char name[32]; uint64_t count; } R[MAXR];
static int nr;
static uint64_t total_insns;
static int check_align;
static const char *hist_path;   /* hist=PATH: per-instruction execution counts for range 0 */
static uint64_t *hist;          /* one counter per 4-byte slot of range 0 */
static uint64_t unaligned_total;
static GHashTable *bad_pcs; /* pc -> count */
static GMutex lock;

static int range_of(uint64_t va)
{
    for (int i = 0; i < nr; i++)
        if (va >= R[i].lo && va < R[i].hi)
            return i;
    return -1;
}

static void mem_cb(unsigned int vcpu, qemu_plugin_meminfo_t info, uint64_t vaddr, void *udata)
{
    unsigned shift = qemu_plugin_mem_size_shift(info);
    if (vaddr & ((1u << shift) - 1)) {
        uint64_t pc = (uint64_t)(uintptr_t)udata;
        g_mutex_lock(&lock);
        unaligned_total++;
        gpointer k = (gpointer)(uintptr_t)pc;
        uintptr_t c = (uintptr_t)g_hash_table_lookup(bad_pcs, k);
        g_hash_table_insert(bad_pcs, k, (gpointer)(c + 1));
        g_mutex_unlock(&lock);
    }
}

static void tb_trans(qemu_plugin_id_t id, struct qemu_plugin_tb *tb)
{
    size_t n = qemu_plugin_tb_n_insns(tb);
    for (size_t i = 0; i < n; i++) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i);
        uint64_t va = qemu_plugin_insn_vaddr(insn);
        qemu_plugin_register_vcpu_insn_exec_inline(insn, QEMU_PLUGIN_INLINE_ADD_U64, &total_insns, 1);
        int r = range_of(va);
        if (r < 0)
            continue;
        qemu_plugin_register_vcpu_insn_exec_inline(insn, QEMU_PLUGIN_INLINE_ADD_U64, &R[r].count, 1);
        if (hist && r == 0)
            qemu_plugin_register_vcpu_insn_exec_inline(insn, QEMU_PLUGIN_INLINE_ADD_U64,
                                                       &hist[(va - R[0].lo) >> 2], 1);
        if (check_align)
            qemu_plugin_register_vcpu_mem_cb(insn, mem_cb, QEMU_PLUGIN_CB_NO_REGS, QEMU_PLUGIN_MEM_RW,
                                             (void *)(uintptr_t)va);
    }
}

static gint cmp_pc(gconstpointer a, gconstpointer b)
{
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x < y ? -1 : x > y;
}

static void at_exit(qemu_plugin_id_t id, void *p)
{
    GString *s = g_string_new("");
    g_string_append_printf(s, "akprof: total_insns %" PRIu64 "\n", total_insns);
    for (int i = 0; i < nr; i++)
        g_string_append_printf(s, "akprof: range %s 0x%" PRIx64 "-0x%" PRIx64 " insns %" PRIu64 "\n",
                               R[i].name, R[i].lo, R[i].hi, R[i].count);
    if (check_align) {
        g_string_append_printf(s, "akprof: unaligned_accesses %" PRIu64 " distinct_pcs %u\n",
                               unaligned_total, g_hash_table_size(bad_pcs));
        GList *keys = g_list_sort(g_hash_table_get_keys(bad_pcs), cmp_pc);
        int shown = 0;
        for (GList *l = keys; l && shown < 4096; l = l->next, shown++) {
            uintptr_t pc = (uintptr_t)l->data;
            int r = range_of(pc);
            g_string_append_printf(s, "akprof: unaligned pc 0x%" PRIxPTR " (%s+0x%" PRIx64 ") count %" PRIuPTR "\n",
                                   pc, r >= 0 ? R[r].name : "?", r >= 0 ? pc - R[r].lo : 0,
                                   (uintptr_t)g_hash_table_lookup(bad_pcs, l->data));
        }
        g_list_free(keys);
    }
    if (hist) {
        FILE *f = fopen(hist_path, "w");
        if (f) {
            for (uint64_t i = 0; i < (R[0].hi - R[0].lo) >> 2; i++)
                if (hist[i])
                    fprintf(f, "%" PRIx64 " %" PRIu64 "\n", R[0].lo + i * 4, hist[i]);
            fclose(f);
        }
    }
    qemu_plugin_outs(s->str);
    g_string_free(s, TRUE);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info,
                                           int argc, char **argv)
{
    bad_pcs = g_hash_table_new(NULL, NULL);
    for (int i = 0; i < argc; i++) {
        const char *a = argv[i];
        if (!strncmp(a, "range=", 6) && nr < MAXR) {
            char name[32] = "";
            unsigned long long lo, hi;
            if (sscanf(a + 6, "%llx:%llx:%31s", &lo, &hi, name) < 2) {
                fprintf(stderr, "akprof: bad %s\n", a);
                return -1;
            }
            R[nr].lo = lo; R[nr].hi = hi;
            snprintf(R[nr].name, sizeof R[nr].name, "%s", name[0] ? name : "r");
            nr++;
        } else if (!strncmp(a, "hist=", 5)) {
            hist_path = a + 5;
        } else if (!strcmp(a, "align=1")) {
            check_align = 1;
        } else {
            fprintf(stderr, "akprof: unknown arg %s\n", a);
            return -1;
        }
    }
    if (hist_path && nr)
        hist = g_new0(uint64_t, (R[0].hi - R[0].lo) >> 2);
    qemu_plugin_register_vcpu_tb_trans_cb(id, tb_trans);
    qemu_plugin_register_atexit_cb(id, at_exit, NULL);
    return 0;
}
