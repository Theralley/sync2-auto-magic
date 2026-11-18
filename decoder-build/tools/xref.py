"""Find literal-pool references to file offsets (strings) in an ARM PE and disassemble the users.

usage: xref.py PE fileoff[,fileoff...] [--ctx N]
"""
import struct
import sys

import capstone
import pefile

pe = pefile.PE(sys.argv[1])
data = pe.__data__
base = pe.OPTIONAL_HEADER.ImageBase
ctx = int(sys.argv[sys.argv.index("--ctx") + 1]) if "--ctx" in sys.argv else 6
text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
tstart, tend = text.PointerToRawData, text.PointerToRawData + text.SizeOfRawData
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)


def off2va(o):
    return base + pe.get_rva_from_offset(o)


def va2off(v):
    return pe.get_offset_from_rva(v - base)


for o in sys.argv[2].split(","):
    o = int(o, 16)
    va = off2va(o)
    print(f"### string @file {o:#x} VA {va:#x}")
    needle = struct.pack("<I", va)
    pos = data.find(needle, tstart, tend)
    while pos != -1:
        lit_va = off2va(pos)
        # find ldr rX, [pc, #imm] within 4KB before the literal that loads it
        for back in range(4, 4096, 4):
            ins_off = pos - back
            if ins_off < tstart:
                break
            w = struct.unpack_from("<I", data, ins_off)[0]
            # LDR (immediate, literal): cond 01 0 1 U 0 0 1 1111 Rt imm12
            if (w & 0x0F7F0000) == 0x051F0000:
                imm = w & 0xFFF
                u = (w >> 23) & 1
                ins_va = off2va(ins_off)
                tgt = ins_va + 8 + (imm if u else -imm)
                if tgt == lit_va:
                    print(f"  literal @VA {lit_va:#x}, loaded at VA {ins_va:#x}")
                    s = ins_off - ctx * 4
                    for ins in md.disasm(data[s:ins_off + ctx * 4 + 4], off2va(s)):
                        mark = "=>" if ins.address == ins_va else "  "
                        print(f"   {mark} {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
        pos = data.find(needle, pos + 4, tend)
