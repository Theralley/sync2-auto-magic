#!/usr/bin/env python3
"""Route a WinCE module's waveOut audio through SYNC 2's WaveOutHooks.dll.

SYNC 2 only plays an app's sound once the app asks Ford's audio router
(RAC.dll) for a route. The community's VideoPlayer and Navitel do this through
WaveOutHooks.dll, whose waveOutOpenCustom/waveOutCloseCustom request and
release the route and otherwise behave like COREDLL's waveOutOpen/waveOutClose.
They were patched with IIDKing: a new section holds an import directory that
also imports WaveOutHooks.dll, and the literal word of each ARM import thunk is
pointed at the new import slot instead of COREDLL's.

This tool reproduces that patch for any module (AutoKit.exe in particular).
It never edits the input file and refuses anything it does not recognise.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# COREDLL ordinals, from the Windows CE 6.0 ARM coredll.def. WaveOutHooks.dll
# itself imports exactly these ordinals, which confirms they hold on SYNC 2.
WAVEOUT_ORDINALS = {
    "waveOutOpen": 399,
    "waveOutClose": 384,
    "waveOutGetVolume": 381,
    "waveOutSetVolume": 382,
}
DEFAULT_FUNCTIONS = ("waveOutOpen", "waveOutClose")
HOOK_DLL_NAME = "WaveOutHooks.dll"

# ldr r12, [pc, #4] ; ldr r12, [r12] ; bx r12 ; .word <IAT slot VA>
ARM_IMPORT_THUNK = bytes.fromhex("04c09fe5" "00c09ce5" "1cff2fe1")

ARM_MACHINES = (0x01C0, 0x01C2)  # ARM, ARM Thumb (THUMB/ARMV4I on WinCE)
NEW_SECTION_NAME = b".wohook"
# Same flags as IIDKing's section in the patched VideoPlayer DLLs that run on
# SYNC 2: code | execute | read | write. The loader writes the new IAT here.
NEW_SECTION_FLAGS = 0xE0000020

DIR_IMPORT = 1
DIR_BOUND_IMPORT = 11


class PatchError(Exception):
    pass


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


@dataclass
class Section:
    header_offset: int
    name: bytes
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int
    characteristics: int


class PEImage:
    """The few PE32 fields this patch reads and writes."""

    def __init__(self, data: bytes):
        self.data = bytearray(data)
        if self.data[:2] != b"MZ":
            raise PatchError("not an MZ executable")
        self.pe = self.u32(0x3C)
        if self.data[self.pe:self.pe + 4] != b"PE\0\0":
            raise PatchError("no PE signature")
        self.machine = self.u16(self.pe + 4)
        if self.machine not in ARM_MACHINES:
            raise PatchError(f"machine {self.machine:#x} is not WinCE ARM")
        self.opt = self.pe + 24
        if self.u16(self.opt) != 0x10B:
            raise PatchError("not PE32")
        self.image_base = self.u32(self.opt + 28)
        self.section_alignment = self.u32(self.opt + 32)
        self.file_alignment = self.u32(self.opt + 36)
        self.size_of_headers = self.u32(self.opt + 60)
        self.directories = self.opt + 96
        optional_size = self.u16(self.pe + 20)
        # Every directory this tool reads or writes, up to bound imports (11),
        # must exist inside the optional header, or writes would hit the section table.
        if self.u32(self.opt + 92) < 16 or optional_size < 96 + 16 * 8:
            raise PatchError("optional header lacks the 16 standard data directories")
        self.section_table = self.opt + optional_size
        self.sections = [
            self._read_section(self.section_table + 40 * i)
            for i in range(self.u16(self.pe + 6))
        ]

    def u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def _read_section(self, offset: int) -> Section:
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
            "<IIII", self.data, offset + 8)
        return Section(offset, bytes(self.data[offset:offset + 8]).rstrip(b"\0"),
                       virtual_size, virtual_address, raw_size, raw_pointer,
                       self.u32(offset + 36))

    def directory(self, index: int) -> tuple[int, int]:
        return struct.unpack_from("<II", self.data, self.directories + 8 * index)

    def rva_to_offset(self, rva: int) -> int:
        for s in self.sections:
            if s.virtual_address <= rva < s.virtual_address + max(s.virtual_size, s.raw_size):
                offset = rva - s.virtual_address
                if offset >= s.raw_size:
                    raise PatchError(f"RVA {rva:#x} lies in uninitialised data")
                return s.raw_pointer + offset
        raise PatchError(f"RVA {rva:#x} is outside every section")

    def offset_to_rva(self, offset: int) -> int | None:
        for s in self.sections:
            if s.raw_pointer <= offset < s.raw_pointer + s.raw_size:
                return offset - s.raw_pointer + s.virtual_address
        return None

    def cstring(self, rva: int) -> str:
        start = self.rva_to_offset(rva)
        return bytes(self.data[start:self.data.index(b"\0", start)]).decode("latin-1")

    def import_descriptors(self) -> list[tuple[int, str, int, int]]:
        """(file offset, dll name, lookup table RVA, IAT RVA) per descriptor."""
        rva, _ = self.directory(DIR_IMPORT)
        if not rva:
            return []
        out = []
        offset = self.rva_to_offset(rva)
        while True:
            lookup, _, _, name, iat = struct.unpack_from("<IIIII", self.data, offset)
            if name == 0:
                return out
            out.append((offset, self.cstring(name), lookup, iat))
            offset += 20

    def thunks(self, lookup: int, iat: int) -> list[tuple[int, int]]:
        """(IAT slot RVA, raw lookup entry) for one descriptor."""
        table = self.rva_to_offset(lookup or iat)
        entries = []
        while True:
            value = self.u32(table + 4 * len(entries))
            if value == 0:
                return entries
            entries.append((iat + 4 * len(entries), value))

    def exports(self) -> set[str]:
        rva, _ = struct.unpack_from("<II", self.data, self.directories)
        if not rva:
            return set()
        offset = self.rva_to_offset(rva)
        count, names = self.u32(offset + 24), self.u32(offset + 32)
        names_offset = self.rva_to_offset(names)
        return {self.cstring(self.u32(names_offset + 4 * i)) for i in range(count)}

    def relocated_rvas(self) -> set[int]:
        rva, size = self.directory(5)
        found: set[int] = set()
        if not rva:
            return found
        offset = self.rva_to_offset(rva)
        end = offset + size
        while offset < end:
            page, block = struct.unpack_from("<II", self.data, offset)
            if block < 8:
                break
            for i in range((block - 8) // 2):
                entry = self.u16(offset + 8 + 2 * i)
                if entry >> 12 == 3:  # IMAGE_REL_BASED_HIGHLOW
                    found.add(page + (entry & 0xFFF))
            offset += block
        return found


def pe_checksum(data: bytes, checksum_offset: int) -> int:
    total = 0
    padded = data + b"\0" * (len(data) % 2)
    for i in range(0, len(padded), 2):
        if checksum_offset <= i < checksum_offset + 4:
            continue
        total += struct.unpack_from("<H", padded, i)[0]
        total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return (total + len(data)) & 0xFFFFFFFF


@dataclass
class Redirect:
    function: str
    coredll_slot_rva: int
    thunk_literal_offsets: list[int]
    hook_slot_rva: int = 0


def find_redirects(image: PEImage, functions: tuple[str, ...]) -> list[Redirect]:
    descriptors = image.import_descriptors()
    names = [name.lower() for _, name, _, _ in descriptors]
    if HOOK_DLL_NAME.lower() in names:
        raise PatchError(f"already imports {HOOK_DLL_NAME}; refusing to patch twice")
    coredll = [d for d in descriptors if d[1].lower() == "coredll.dll"]
    if len(coredll) != 1:
        raise PatchError("expected exactly one COREDLL.dll import descriptor")
    _, _, lookup, iat = coredll[0]
    slots_by_ordinal: dict[int, list[int]] = {}
    for slot, value in image.thunks(lookup, iat):
        if value & 0x80000000:
            slots_by_ordinal.setdefault(value & 0xFFFF, []).append(slot)
    executable = [s for s in image.sections if s.characteristics & 0x20000000]

    redirects = []
    for function in functions:
        slots = slots_by_ordinal.get(WAVEOUT_ORDINALS[function], [])
        if not slots:
            continue  # the module does not import it; nothing to redirect
        if len(slots) > 1:
            raise PatchError(f"{function} is imported more than once")
        slot = slots[0]
        needle = struct.pack("<I", image.image_base + slot)
        literals, start = [], 0
        while (hit := image.data.find(needle, start)) != -1:
            literals.append(hit)
            start = hit + 1
        if not literals:
            raise PatchError(f"no reference to the {function} import slot")
        for literal in literals:
            in_code = any(s.raw_pointer <= literal < s.raw_pointer + s.raw_size
                          for s in executable)
            if (not in_code or literal % 4
                    or image.data[literal - len(ARM_IMPORT_THUNK):literal] != ARM_IMPORT_THUNK):
                raise PatchError(
                    f"{function}: reference at {literal:#x} is not an ARM import thunk")
        redirects.append(Redirect(function, slot, literals))
    if not any(r.function == "waveOutOpen" for r in redirects):
        raise PatchError("module does not import waveOutOpen; nothing to route")
    return redirects


def patch(module: bytes, hook: bytes, functions: tuple[str, ...] = DEFAULT_FUNCTIONS) -> bytes:
    image = PEImage(module)
    missing = {f + "Custom" for f in functions} - PEImage(hook).exports()
    if missing:
        raise PatchError(f"{HOOK_DLL_NAME} does not export {sorted(missing)}")

    last = max(image.sections, key=lambda s: s.raw_pointer + s.raw_size)
    if len(image.data) != last.raw_pointer + last.raw_size:
        raise PatchError("file has overlay data after its last section")
    if image.directory(4)[0]:
        raise PatchError("module carries a certificate table")
    header_end = image.section_table + 40 * (len(image.sections) + 1)
    first_raw = min(s.raw_pointer for s in image.sections if s.raw_size)
    if header_end > min(first_raw, image.size_of_headers) or any(
            image.data[header_end - 40:header_end]):
        raise PatchError("no free room for another section header")

    redirects = find_redirects(image, functions)
    descriptors = image.import_descriptors()
    section_rva = _align(max(s.virtual_address + max(s.virtual_size, s.raw_size)
                             for s in image.sections), image.section_alignment)

    # Layout: import directory | hook lookup table | hook IAT | hint/names | dll name
    directory_size = 20 * (len(descriptors) + 2)
    lookup_rva = section_rva + directory_size
    iat_rva = lookup_rva + 4 * (len(redirects) + 1)
    blob = bytearray(directory_size + 8 * (len(redirects) + 1))
    names_rva = section_rva + len(blob)
    hint_names = bytearray()
    for i, redirect in enumerate(redirects):
        entry_rva = names_rva + len(hint_names)
        hint_names += b"\0\0" + (redirect.function + "Custom").encode() + b"\0"
        if len(hint_names) % 2:
            hint_names += b"\0"
        struct.pack_into("<I", blob, lookup_rva - section_rva + 4 * i, entry_rva)
        struct.pack_into("<I", blob, iat_rva - section_rva + 4 * i, entry_rva)
        redirect.hook_slot_rva = iat_rva + 4 * i
    dll_name_rva = names_rva + len(hint_names)
    blob += hint_names + HOOK_DLL_NAME.encode() + b"\0"

    for i, (offset, _, _, _) in enumerate(descriptors):
        blob[20 * i:20 * i + 20] = image.data[offset:offset + 20]
    struct.pack_into("<IIIII", blob, 20 * len(descriptors),
                     lookup_rva, 0, 0, dll_name_rva, iat_rva)

    raw_pointer = _align(len(image.data), image.file_alignment)
    raw_size = _align(len(blob), image.file_alignment)
    out = image.data + b"\0" * (raw_pointer - len(image.data))
    out += blob + b"\0" * (raw_size - len(blob))

    struct.pack_into("<8sIIIIIIHHI", out, image.section_table + 40 * len(image.sections),
                     NEW_SECTION_NAME, len(blob), section_rva, raw_size, raw_pointer,
                     0, 0, 0, 0, NEW_SECTION_FLAGS)
    struct.pack_into("<H", out, image.pe + 6, len(image.sections) + 1)
    struct.pack_into("<I", out, image.opt + 56,
                     _align(section_rva + len(blob), image.section_alignment))
    struct.pack_into("<I", out, image.opt + 8,
                     image.u32(image.opt + 8) + raw_size)  # SizeOfInitializedData
    # Size includes the null terminator, as in IIDKing's output.
    struct.pack_into("<II", out, image.directories + 8 * DIR_IMPORT,
                     section_rva, directory_size)
    # Bound imports would describe the old import table; the loader rebinds.
    struct.pack_into("<II", out, image.directories + 8 * DIR_BOUND_IMPORT, 0, 0)

    for redirect in redirects:
        for literal in redirect.thunk_literal_offsets:
            struct.pack_into("<I", out, literal, image.image_base + redirect.hook_slot_rva)

    checksum_offset = image.opt + 64
    if image.u32(checksum_offset):
        struct.pack_into("<I", out, checksum_offset, pe_checksum(bytes(out), checksum_offset))
    return bytes(out)


def write_atomically(path: Path, data: bytes) -> None:
    """Write a new file and swap it in, so an existing link target is never truncated."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def describe(module: bytes, patched: bytes, functions: tuple[str, ...]) -> str:
    before, after = PEImage(module), PEImage(patched)
    lines = []
    for redirect in find_redirects(before, functions):
        for literal in redirect.thunk_literal_offsets:
            lines.append(
                f"  {redirect.function}: thunk @{literal:#x} "
                f"{before.u32(literal):#010x} -> {after.u32(literal):#010x}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("module", type=Path, help="WinCE ARM .exe/.dll to patch")
    parser.add_argument("output", type=Path, help="where to write the patched copy")
    parser.add_argument("--hook", type=Path, required=True,
                        help=f"the {HOOK_DLL_NAME} that will ship next to the module")
    parser.add_argument("--volume", action="store_true",
                        help="also route waveOutGetVolume/waveOutSetVolume")
    args = parser.parse_args(argv)

    if args.output.exists() and args.output.samefile(args.module):
        parser.error("output must differ from the input; originals stay untouched")
    functions = DEFAULT_FUNCTIONS + (("waveOutGetVolume", "waveOutSetVolume")
                                     if args.volume else ())
    module = args.module.read_bytes()
    try:
        patched = patch(module, args.hook.read_bytes(), functions)
    except PatchError as error:
        print(f"{args.module.name}: {error}", file=sys.stderr)
        return 1
    write_atomically(args.output, patched)
    print(f"{args.module.name} -> {args.output}")
    print(describe(module, patched, functions))
    print(f"  sha256 in  {hashlib.sha256(module).hexdigest()}")
    print(f"  sha256 out {hashlib.sha256(patched).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
