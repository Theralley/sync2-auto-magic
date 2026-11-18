"""Scan the code sections of ARM PE DLLs for instruction-set features.

usage: isa_scan.py [--nm FILE.nm] [--show N] DLL...

Linear sweep over every executable section in ARM (A32) mode. Words that GCC or the
assembler use as data inside .text (literal pools reached by "ldr rX,[pc,#imm]",
"ldrd rX,[pc,#imm]" and "add rX,pc,#imm" + ldm) are excluded first.

Classification uses raw encodings (independent of capstone) for the hard checks:
  * coprocessor instructions (CDP, MCR/MRC, MCRR/MRRC, LDC/STC) by coprocessor number:
    cp10/cp11 = VFP and NEON register file; cp15 = system control; cp14 = debug
  * Advanced SIMD (NEON) data-processing and element load/store (unconditional space)
and capstone instruction groups for the inventory (ARMv5TE, ARMv6, ARMv6T2, ARMv7).
"""
import bisect
import collections
import struct
import sys

import capstone
from capstone import arm as A
import pefile

args = sys.argv[1:]
nmfiles, show = [], 5
while args and args[0].startswith("--"):
    if args[0] == "--nm":
        nmfiles.append(args[1]); args = args[2:]
    elif args[0] == "--show":
        show = int(args[1]); args = args[2:]

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
md.detail = True
GROUPS = {
    "v5te": getattr(A, "ARM_GRP_V5TE", None), "v6": getattr(A, "ARM_GRP_V6", None),
    "v6t2": getattr(A, "ARM_GRP_V6T2", None), "v7": getattr(A, "ARM_GRP_V7", None),
    "neon(cs)": getattr(A, "ARM_GRP_NEON", None), "vfp2(cs)": getattr(A, "ARM_GRP_VFP2", None),
    "vfp3(cs)": getattr(A, "ARM_GRP_VFP3", None), "barrier": getattr(A, "ARM_GRP_DATABARRIER", None),
}


def load_syms(path):
    syms = []
    for line in open(path):
        p = line.split()
        if len(p) == 3 and p[1] in "tT":
            syms.append((int(p[0], 16), p[2]))
    syms.sort()
    return syms


def raw_class(w):
    cond = w >> 28
    if cond == 0xF:
        if (w >> 25) == 0b1111001:
            return "NEON-dp"
        if (w >> 24) == 0xF4:
            if ((w >> 20) & 0x7) == 0b101:
                return None  # PLI (immediate)
            if ((w >> 21) & 1) == 0:
                return "NEON-ls"  # VLDn/VSTn element or structure
            return "uncond-F4-other"
        if ((w >> 25) & 0x7) == 0b110 or ((w >> 24) & 0xF) == 0xE:  # LDC2/STC2/MCRR2/CDP2/MCR2
            return f"cp{(w >> 8) & 0xF}"
        return None
    op = (w >> 24) & 0xF
    if op == 0xE:  # CDP / MCR / MRC
        return f"cp{(w >> 8) & 0xF}"
    if (w >> 25) & 0x7 == 0b110:  # LDC/STC/MCRR/MRRC
        return f"cp{(w >> 8) & 0xF}"
    return None


def scan(path):
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    syms = []
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    for nm in nmfiles:
        if nm.rsplit("/", 1)[-1].startswith(stem):
            syms = load_syms(nm)
    addrs = [a for a, _ in syms]

    def where(va):
        i = bisect.bisect_right(addrs, va) - 1
        return f"{syms[i][1]}+{va - syms[i][0]:#x}" if i >= 0 else "?"

    print(f"== {path}")
    total = collections.Counter()
    examples = collections.defaultdict(list)
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:  # MEM_EXECUTE
            continue
        data = s.get_data()[:s.Misc_VirtualSize]
        va0 = base + s.VirtualAddress
        n = len(data) // 4
        words = struct.unpack_from(f"<{n}I", data)
        is_data = bytearray(n)
        # pass 1: mark literal-pool words
        for i, w in enumerate(words):
            if w >> 28 == 0xF:
                continue
            # LDR/LDRB (literal): cond 01 0 1 U 0 0 1 1111
            if (w & 0x0F7F0000) == 0x051F0000 or (w & 0x0F7F0000) == 0x055F0000:
                imm = w & 0xFFF
                t = i * 4 + 8 + (imm if (w >> 23) & 1 else -imm)
                if 0 <= t < len(data) and t % 4 == 0:
                    is_data[t // 4] = 1
            # LDRD/LDRH (literal): cond 000 1 U 1 0 0 1111 Rt imm4H 1 1 S H 1 imm4L
            elif (w & 0x0E5F0090) == 0x014F0090 and (w & 0x60) != 0:
                imm = ((w >> 4) & 0xF0) | (w & 0xF)
                t = i * 4 + 8 + (imm if (w >> 23) & 1 else -imm)
                if 0 <= t < len(data) - 4 and t % 4 == 0:
                    is_data[t // 4] = 1
                    if (w & 0xF0) == 0xD0:
                        is_data[t // 4 + 1] = 1
            # VLDR (literal) - cp10/11 with Rn = pc
            elif (w & 0x0F3F0E00) == 0x0D1F0A00:
                imm = (w & 0xFF) * 4
                t = i * 4 + 8 + (imm if (w >> 23) & 1 else -imm)
                if 0 <= t < len(data) - 4 and t % 4 == 0:
                    is_data[t // 4] = 1
                    is_data[t // 4 + 1] = 1
            # ADD rd, pc, #imm  (adr) followed by LDM/LDRD from rd
            elif (w & 0x0FFF0000) == 0x028F0000:
                rot = ((w >> 8) & 0xF) * 2
                imm = ((w & 0xFF) >> rot | (w & 0xFF) << (32 - rot)) & 0xFFFFFFFF
                t = i * 4 + 8 + imm
                if 0 <= t < len(data) and t % 4 == 0:
                    cnt = 2
                    rd = (w >> 12) & 0xF
                    for j in range(i + 1, min(i + 8, n)):
                        u = words[j]
                        if (u & 0x0E100000) == 0x08100000 and ((u >> 16) & 0xF) == rd:  # LDM rd
                            cnt = bin(u & 0xFFFF).count("1")
                            break
                    for k in range(cnt):
                        if t // 4 + k < n:
                            is_data[t // 4 + k] = 1
        # pass 2: classify
        for i, w in enumerate(words):
            if is_data[i]:
                total["(literal words skipped)"] += 1
                continue
            va = va0 + i * 4
            rc = raw_class(w)
            if rc:
                total[rc] += 1
                examples[rc].append(va)
            ins = next(md.disasm(data[i * 4:i * 4 + 4], va), None)
            if ins is None:
                total["(undecodable)"] += 1
                continue
            total["(instructions)"] += 1
            for name, g in GROUPS.items():
                if g is not None and g in ins.groups:
                    total[name] += 1
                    if len(examples[name]) < 400:
                        examples[name].append(va)
            m = ins.mnemonic.split(".")[0]
            for key in ("setend", "ldrex", "strex", "dmb", "dsb", "isb", "clz", "pld", "usat", "ssat",
                        "rev", "smulbb", "qadd", "usada8", "uxtb", "smmul", "ubfx", "movw", "movt", "ldrd", "strd", "blx", "bx", "swp", "svc", "udf", "bkpt", "wfi", "mrs", "msr", "cps", "srs", "rfe"):
                if m == key or (key in ("usat", "ssat", "rev", "uxtb", "qadd", "smulbb") and m.startswith(key)):
                    total["op:" + key] += 1
                    if key in ("setend", "ldrex", "strex", "dmb", "swp", "svc", "udf", "bkpt", "wfi", "mrs", "msr", "cps", "srs", "rfe") and len(examples["op:" + key]) < 50:
                        examples["op:" + key].append(va)
    for k in sorted(total):
        line = f"   {k:28s} {total[k]}"
        if k in examples and (k.startswith("cp") or k.startswith("NEON") or k.startswith("op:") or "(cs)" in k):
            ex = ", ".join(f"{va:#x}<{where(va)}>" for va in examples[k][:show])
            line += f"   e.g. {ex}"
        print(line)
    return total


for p in args:
    scan(p)
