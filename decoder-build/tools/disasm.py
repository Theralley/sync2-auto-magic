"""Disassemble a VA range of an ARM PE, annotating PC-relative literal loads with strings.

usage: disasm.py PE start_va end_va
"""
import struct
import sys

import capstone
import pefile

pe = pefile.PE(sys.argv[1])
data = pe.__data__
base = pe.OPTIONAL_HEADER.ImageBase
start, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

imports = {}
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        for i in e.imports:
            imports[i.address] = f"{e.dll.decode()}!{i.name.decode() if i.name else 'ord%d' % i.ordinal}"


def va2off(v):
    return pe.get_offset_from_rva(v - base)


def describe(v):
    if v in imports:
        return imports[v]
    try:
        o = va2off(v)
    except Exception:
        return ""
    raw = data[o:o + 80]
    if len(raw) > 4 and raw[1] == 0 and 0x20 <= raw[0] < 0x7f:
        s = raw.decode("utf-16le", errors="replace").split("\0")[0]
        return f'L"{s}"'
    s = raw.split(b"\0")[0]
    if len(s) >= 3 and all(0x20 <= c < 0x7f for c in s):
        return f'"{s.decode()}"'
    return ""


code = data[va2off(start):va2off(end)]
for ins in md.disasm(code, start):
    note = ""
    if ins.mnemonic.startswith("ldr") and "[pc" in ins.op_str:
        w = struct.unpack_from("<I", code, ins.address - start)[0]
        imm = w & 0xFFF
        tgt = ins.address + 8 + (imm if (w >> 23) & 1 else -imm)
        val = struct.unpack_from("<I", data, va2off(tgt))[0]
        note = f"; ={val:#x} {describe(val)}"
    print(f"{ins.address:#x}: {ins.mnemonic:8s} {ins.op_str} {note}")
