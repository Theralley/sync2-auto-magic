"""A faster video decoder for AutoKit: its three FFmpeg files swapped for a build made on this Mac.

AutoKit decodes the phone's picture with FFmpeg 2.6, three DLLs in its folder (DECODER_FILES).
It loads them by name each time it opens (LoadLibrary and GetProcAddress) and calls the functions
in CALLS; their names are UTF-16 strings in AutoKit.exe, next to each DLL's name. The three call
each other, so a decoder job replaces all three or none, through the same steps as a theme job
(job.swap_lines): it stops while AutoKit runs, checks the car's files by size against
SyncExtPack's own (the ones s2am installs with AutoKit), backs them up on the car and onto the
stick, copies the new ones in and checks their sizes, and copies the backup back if one did not
copy whole. ``--restore`` carries SyncExtPack's files itself. SYNC does not restart: AutoKit loads
the files when it next opens.

The new files are checked on the Mac first. Windows CE refuses to load a DLL built for another
processor, or one that needs a DLL or a function that is not there, and then AutoKit cannot
start. So each new file must be an ARM DLL that exports every function AutoKit calls in it, and
may need only coredll.dll (Windows CE's own) and the other two, which must export everything it
takes from them. The new files stay on the Mac and on the job's stick, never in this repository.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from .job import DECODER_FILES as FILES
from .state import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import patch_waveout  # noqa: E402  (its ARM_MACHINES: the processors Windows CE on SYNC runs)

# SyncExtPack's AutoKit, in the upstream checkout. Its three are 1825811 (avcodec), 238099 (avutil)
# and 151040 (avformat) bytes.
STOCK = Path("FullPack/SyncExtendedPack/Apps/Media/AutoKit")
CALLS = {  # what AutoKit.exe looks up in each file by name
    "avcodec-56.dll": ("avcodec_register_all", "av_parser_init", "avcodec_open2", "avcodec_find_decoder",
                       "av_free_packet", "av_init_packet", "avcodec_alloc_context3", "avcodec_close",
                       "avcodec_decode_video2", "av_parser_parse2", "av_parser_close"),
    "avutil-54.dll": ("av_frame_alloc", "av_frame_free", "av_free", "av_malloc"),
    "avformat-56.dll": ("av_register_all",),
}
ARM = 0x01C0  # IMAGE_FILE_MACHINE_ARM, what SyncExtPack's own three are built for (ARM Thumb is 0x01C2)
DLL = 0x2000  # IMAGE_FILE_DLL
# outcomes of a decoder job after which the car may no longer hold what an earlier one put there
# ("failed" is not one: such a run stopped before any change, or its rollback was checked at import)
CHANGED_CAR = ("applied", "already-applied", "interrupted", "not-verified", "rollback-failed",
               "processed-no-report", "unknown")
CORE = "coredll.dll"  # Windows CE's C library and system calls, on every car


class DecoderError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Pe:
    machine: int
    dll: bool
    exports: frozenset[str]  # names another file can call: each leads to a function in this one
    filled: frozenset[str]  # of those, the ones that lead to bytes the file holds (code), not zeroed memory
    ordinals: frozenset[int]  # the same, by number (an import may name a function by its number)
    unusable: dict[str, str]  # names listed that lead nowhere -> why
    imports: dict[str, tuple[str | int, ...]]  # lower-case DLL name -> functions (int: by number)


class _Image:
    """A PE file's sections as the loader maps them. Every table and name is read only where a
    section holds it in the file, whole, so a damaged file is refused instead of read past."""

    def __init__(self, data: bytes, sections: list[tuple[int, int, int, int]]):
        self.data = data
        self.spans = []  # (address, bytes the loader maps from the file, where in the file)
        self.memory = []  # (address, bytes in memory): past the file's bytes, zeros (.bss)
        for address, virtual, raw_size, raw in sections:
            if raw_size and raw + raw_size > len(data):
                raise DecoderError("is cut short (a section runs past the end of the file)")
            self.spans.append((address, min(raw_size, virtual) if virtual else raw_size, raw))
            self.memory.append((address, max(raw_size, virtual)))

    def _find(self, rva: int) -> tuple[int, int] | None:
        """(where ``rva`` is in the file, where its section's data ends there), or None."""
        for address, size, raw in self.spans:
            if address <= rva < address + size:
                return raw + rva - address, raw + size
        return None

    def filled(self, rva: int) -> bool:
        """``rva`` is in bytes the file holds (code is), not in the zeroed memory past them."""
        return self._find(rva) is not None

    def loaded(self, rva: int, length: int = 1) -> bool:
        """``length`` bytes from ``rva`` are inside one section once the DLL is loaded (a variable
        may be in zeroed memory, and the loader writes each import's address into it)."""
        return any(address <= rva and rva + length <= address + size for address, size in self.memory)

    def at(self, rva: int, length: int) -> int:
        """Where ``length`` bytes from ``rva`` are in the file, all inside one section."""
        found = self._find(rva)
        if found is None or found[0] + length > found[1]:
            raise DecoderError(f"has a table that does not fit in its section (0x{rva:x})")
        return found[0]

    def table(self, rva: int, count: int, kind: str) -> tuple[int, ...]:
        if not count:
            return ()
        return struct.unpack_from(f"<{count}{kind}", self.data, self.at(rva, count * struct.calcsize(kind)))

    def name(self, rva: int) -> str:
        found = self._find(rva)
        if found is None:
            raise DecoderError(f"has a name outside its sections (0x{rva:x})")
        end = self.data.find(b"\0", found[0], found[1])
        if end < 0:
            raise DecoderError("has a name that runs past the end of its section")
        return self.data[found[0]:end].decode("ascii", "replace")


def parse(data: bytes) -> Pe:
    """Read just what the checks need from a PE file: its processor, whether it is a DLL, the
    functions it exports (by name and by number) and the ones it takes from each DLL it needs.
    An export counts only if it leads to a function inside the file, as the loader follows it:
    name, then its number, then the function's address. Anything that does not read as a PE
    file raises DecoderError, never an IndexError or struct.error."""
    if data[:2] != b"MZ":
        raise DecoderError("does not start with MZ")
    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise DecoderError("has no PE header")
        machine, count, _, _, _, size, flags = struct.unpack_from("<HHIIIHH", data, pe + 4)
        optional = pe + 24
        if struct.unpack_from("<H", data, optional)[0] != 0x10B or size < 96:
            raise DecoderError("is not a 32-bit PE file")
        entries = min(struct.unpack_from("<I", data, optional + 92)[0], (size - 96) // 8)
        (export_rva, export_size), (import_rva, _) = (
            struct.unpack_from("<II", data, optional + 96 + 8 * i) if i < entries else (0, 0) for i in (0, 1))
        sections = []
        for i in range(count):  # (address, size loaded, size in the file, where in the file)
            virtual, address, raw_size, raw = struct.unpack_from("<IIII", data, optional + size + 40 * i + 8)
            sections.append((address, virtual, raw_size, raw))
        image = _Image(data, sections)

        exports, filled, ordinals, unusable = set(), set(), set(), {}
        if export_rva:
            base, functions, names, function_table, name_table, number_table = struct.unpack_from(
                "<6I", data, image.at(export_rva, 40) + 16)
            if functions > 65536 or names > 65536:
                raise DecoderError("has an export table too long to be real")
            addresses = image.table(function_table, functions, "I")

            def why(index: int) -> str | None:
                """Why the loader could not call the function at ``index``, or None if it can."""
                if index >= functions:
                    return "listed, but its number is past the end of the table"
                if not addresses[index]:
                    return "listed, but without a function"
                if export_rva <= addresses[index] < export_rva + export_size:
                    return "listed, but forwarded to another DLL"
                if not image.loaded(addresses[index]):
                    return "listed, but it leads outside the DLL"
                return None

            ordinals = {base + index for index in range(functions) if why(index) is None}
            for rva, index in zip(image.table(name_table, names, "I"), image.table(number_table, names, "H")):
                name, reason = image.name(rva), why(index)
                if reason is None:
                    exports.add(name)
                    if image.filled(addresses[index]):
                        filled.add(name)
                else:
                    unusable.setdefault(name, reason)

        imports: dict[str, tuple[str | int, ...]] = {}
        if import_rva:
            entry = import_rva
            for _ in range(256):  # one entry per DLL it needs, then an empty one
                lookup, _, _, name, thunks = struct.unpack_from("<5I", data, image.at(entry, 20))
                if not name:
                    break
                dll = image.name(name).lower()
                dll += "" if "." in dll else ".dll"  # SyncExtPack's own three name it "COREDLL"
                needed: list[str | int] = []
                table = lookup or thunks  # the names, read from the file; the loader writes to thunks
                for i in range(65536):
                    value = struct.unpack_from("<I", data, image.at(table + 4 * i, 4))[0]
                    if not value:
                        break
                    if not thunks or not image.loaded(thunks + 4 * i, 4):
                        raise DecoderError(f"has an import address table outside its sections "
                                           f"(0x{thunks + 4 * i:x})")
                    needed.append(value & 0xFFFF if value & 0x80000000
                                  else image.name(value + 2))  # past the two-byte hint
                else:
                    raise DecoderError("has an import list without an end")
                imports[dll] = imports.get(dll, ()) + tuple(needed)
                entry += 20
            else:
                raise DecoderError("has an import table without an end")
    except struct.error as error:
        raise DecoderError(f"is cut short ({error})") from error
    return Pe(machine, bool(flags & DLL), frozenset(exports), frozenset(filled), frozenset(ordinals), unusable,
              imports)


def _missing(pe: Pe, functions: tuple[str | int, ...], code: bool = False) -> list[str]:
    """The functions ``pe`` cannot give, in words: a number as #n, a name with why if it is listed.
    With ``code``, a name must also lead to bytes the file holds: a function AutoKit calls is code,
    and zeroed memory (.bss, where a library keeps variables, which another one may import) is not."""
    missing = []
    for function in functions:
        if isinstance(function, int):
            if function not in pe.ordinals:
                missing.append(f"#{function}")
        elif function not in pe.exports:
            reason = pe.unusable.get(function)
            missing.append(f"{function} ({reason})" if reason else function)
        elif code and function not in pe.filled:
            missing.append(f"{function} (listed, but it leads into zeroed memory, not to code)")
    return missing


def check(name: str, data: bytes) -> Pe:
    """Refuse a file that cannot stand in for SyncExtPack's ``name``: it must be an ARM DLL that
    exports every function AutoKit calls in it."""
    try:
        pe = parse(data)
    except DecoderError as error:
        raise DecoderError(f"{name} {error}") from error
    if pe.machine not in patch_waveout.ARM_MACHINES:
        raise DecoderError(f"{name} is built for another processor (machine 0x{pe.machine:04x}; "
                           f"AutoKit runs on ARM, {' or '.join(f'0x{m:04x}' for m in patch_waveout.ARM_MACHINES)})")
    if not pe.dll:
        raise DecoderError(f"{name} is not a DLL")
    missing = _missing(pe, CALLS[name], code=True)
    if missing:
        raise DecoderError(f"{name} does not export {', '.join(missing)}, which AutoKit calls")
    return pe


def check_set(new: dict[str, bytes]) -> None:
    """All three, each one fit (``check``), and they load together: each needs only coredll.dll
    and the other two, and finds in them every function it takes from them."""
    absent = [name for name in FILES if name not in new]
    if absent:
        raise DecoderError(f"a decoder job replaces all three files together; missing {', '.join(absent)}")
    built = {name: check(name, new[name]) for name in FILES}
    for name, pe in built.items():
        for dll, functions in pe.imports.items():
            if dll == CORE:
                continue
            if dll not in built:
                raise DecoderError(f"{name} needs {dll}, which is not one of the three, and the car may "
                                   "not have it: AutoKit would not start")
            missing = _missing(built[dll], functions)
            if missing:
                raise DecoderError(f"{name} takes {', '.join(missing[:5])} from {dll}, which does not "
                                   "export it: the three are not from one build")


def originals(upstream: Path) -> dict[str, bytes]:
    """SyncExtPack's own three, the ones s2am installs with AutoKit."""
    folder = upstream / STOCK
    absent = [name for name in FILES if not (folder / name).is_file()]
    if absent:
        raise DecoderError(f"SyncExtPack's AutoKit folder ({folder}) has no {', '.join(absent)}")
    return {name: (folder / name).read_bytes() for name in FILES}


def from_folder(source: Path) -> dict[str, bytes]:
    if not source.is_dir():
        raise DecoderError(f"{source} is not a folder")
    absent = [name for name in FILES if not (source / name).is_file()]
    if absent:
        raise DecoderError(f"{source} has no {', '.join(absent)}: a decoder job replaces all three "
                           "files together")
    return {name: (source / name).read_bytes() for name in FILES}


def _applied(store: Store, serial: str, job_id: str) -> dict:
    """The record of decoder apply job ``job_id``; DecoderError if it is not one."""
    try:
        target = store.job(serial, job_id)
    except (OSError, ValueError) as error:
        raise DecoderError(f"{job_id} is not a job of this car") from error
    if target.get("kind") != "dec" or (target.get("params") or {}).get("restore"):
        raise DecoderError(f"{job_id} is not a decoder job")
    return target


def plan(store: Store, serial: str, upstream: Path, source: Path | None, restore: str | None,
         over: str | None = None, neon_check: bool = False) -> tuple[dict, dict[str, bytes]]:
    """(job params, files for the job folder) for a decoder job or its restore.

    ``over``: the car holds the files decoder job ``over`` put there, not SyncExtPack's own, so
    the new job plans against those: their sizes are what it finds, and what it backs up. Only a
    job the Mac checked byte for byte on the car counts. Its restore still carries SyncExtPack's
    own files: the undo of any decoder job is AutoKit as it was installed.

    ``neon_check``: the job runs s2amneon.exe first and changes nothing unless it passes
    (job._decoder_apply_lines); for a build that uses NEON.
    """
    if (source is None) == (restore is None):
        raise DecoderError("give either --from FOLDER or --restore JOB")
    if restore and (over or neon_check):
        raise DecoderError("--over and --neon-check go with --from, not with --restore")
    old = originals(upstream)
    if restore:
        target = base = _applied(store, serial, restore)
        for _ in range(16):  # a job planned over another: the first of them replaced SyncExtPack's own
            if not base["params"].get("over"):
                break
            base = _applied(store, serial, base["params"]["over"])
        else:
            raise DecoderError(f"{restore} is planned over too many other jobs")
        files = base["params"].get("files") or {}
        wrong = [name for name in FILES if sha256(old[name]) != (files.get(name) or {}).get("old_sha256")]
        if wrong:
            raise DecoderError(f"SyncExtPack's {', '.join(wrong)} is not what {restore} replaced; "
                               "not restoring it")
        return ({"restore": restore, "files": {name: len(old[name]) for name in FILES},
                 "sha256": {name: sha256(old[name]) for name in FILES}},
                {f"orig-{name}": old[name] for name in FILES})
    new = from_folder(source)
    check_set(new)
    if over:
        target = _applied(store, serial, over)
        if target.get("status") not in ("applied", "already-applied") or "verified" not in target \
                or "not_verified" in target or target.get("undone_by"):
            raise DecoderError(f"{over} is not known to be on the car: only a decoder job that ran and "
                               "that the Mac checked byte for byte at import can be planned over")
        later = [job["id"] for job in store.jobs(serial)
                 if job.get("kind") == "dec" and job.get("created_utc", "") > target.get("created_utc", "")
                 and (job.get("outcome") or job.get("status")) in CHANGED_CAR]
        if later:
            raise DecoderError(f"{later[-1]} ran after {over} and may have changed the decoder again: plan "
                               "over the job that ran last, or run its restore and plan without --over")
        files = target["params"].get("files") or {}
        if sorted(files) != sorted(FILES):
            raise DecoderError(f"{over} does not record all three decoder files")
        before = {name: (files[name]["new"], files[name]["new_sha256"]) for name in FILES}
        if all(sha256(new[name]) == before[name][1] for name in FILES):
            raise DecoderError(f"the new files are the ones {over} put on the car; nothing to do")
    else:
        before = {name: (len(old[name]), sha256(old[name])) for name in FILES}
        for name in FILES:
            if new[name] == old[name]:
                raise DecoderError(f"the new {name} is the same as AutoKit's own; nothing to do")
            if len(new[name]) == len(old[name]):
                # the car tells a copy that failed (a file AutoKit holds) only by its size
                raise DecoderError(f"the new {name} is exactly as long as AutoKit's own, so the car could not "
                                   "tell a failed copy from a good one: rebuild it")
    params = {"files": {name: {"old": before[name][0], "new": len(new[name]), "old_sha256": before[name][1],
                               "new_sha256": sha256(new[name])} for name in FILES}}
    if over:
        params["over"] = over
    if neon_check:
        params["neon_check"] = True
    return params, {f"new-{name}": new[name] for name in FILES}


def same_length(params: dict) -> list[str]:
    """The files of a job planned over another that are as long as the ones on the car but not
    the same: the car cannot tell whether such a file copied, only the Mac's byte check can."""
    return [name for name, f in (params.get("files") or {}).items()
            if f["old"] == f["new"] and f["old_sha256"] != f["new_sha256"]]
