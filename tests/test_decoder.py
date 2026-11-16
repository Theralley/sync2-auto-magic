"""Tests for the decoder job: AutoKit's three FFmpeg files swapped, all or none, and put back.

The DLLs here are synthetic: small PE files made by ``pe`` with just the headers, exports and
imports the checks read. The real builds never enter the repository.
"""
import contextlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, decoder, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import (AUTOKIT_BUSY, AUTOKIT_BUSY_RESTORE, AUTOKIT_CE, BUNDLE_PARTS, CHANGING,  # noqa: E402
                      DECODER_FILES, OLD_REPORT, OLD_REPORT_MARKER, READBACK, RESTARTING, SCREENS, STICK_MOUNTS,
                      SWAP_KINDS, Job, bundle_parts, ce_path, meta, swap_lines, swap_script, swap_target)
from s2am.state import Store  # noqa: E402

SERIAL = "XV31M13H"
CODEC, UTIL, FORMAT = DECODER_FILES
# A swap script deletes only what runs write to the stick: stop markers, and an earlier run's
# copies in the report folder (job.READBACK). It writes no registry and starts no program.
NO_DELETES = (r'\b(Delete(?!\(out & ")|(DelTree|RmDir)(?!\(out & "\\(applied|rolledback|backup)"\))'
              r'|RegWrite\w*|Run|RunWait)\(')


def pe(exports=(), imports=None, machine=0x01C0, dll=True, size=None, filler=b"", forwarded=(), empty=(),
       stray=(), outside=(), variables=(), unnamed=0, cut=0, first=1, iat=None) -> bytes:
    """A small PE file, as far as the decoder checks read one: the headers and one section that
    holds the export table, ``filler``, then the import table, with the DLLs' names last.

    Every name in ``exports`` leads to a function. The other lists are names a damaged or odd build
    may list: ``forwarded`` to another DLL, ``empty`` without a function, ``stray`` with a number
    past the end of the table, ``outside`` leading outside the DLL, ``variables`` in the zeroed
    memory after the section's bytes (.bss, as SyncExtPack's own avcodec has). ``unnamed`` more
    functions are exported by number only; the numbers start at ``first`` (the table's base). An
    int in ``imports`` takes a function by its number. ``iat`` puts each import's address table
    (where the loader writes) at that address instead of on its name list. ``cut`` declares the
    section that many bytes shorter than it is (negative: longer than the file); ``size`` pads the
    file with zeros."""
    base, section = 0x1000, bytearray()

    def put(data: bytes) -> int:
        section.extend(data)
        return base + len(section) - len(data)

    def text(name: str) -> int:
        return put(name.encode() + b"\0")

    listed = sorted({*exports, *forwarded, *empty, *stray, *outside, *variables})
    slots = [name for name in listed if name not in stray]  # each one's function, by number
    count = len(slots) + unnamed
    names = [text(name) for name in listed]
    name_table = put(b"".join(struct.pack("<I", rva) for rva in names))
    numbers = put(b"".join(struct.pack("<H", slots.index(name) if name in slots else count + 5) for name in listed))
    function_table = put(bytes(4 * count))
    dll_name = text("x.dll")
    export_dir = put(bytes(40))
    forward = put(b"OTHER.elsewhere\0")  # inside the export directory's span: a forwarder
    put(filler)
    entries = []
    for library, wanted in (imports or {}).items():
        refs = [0x80000000 | function if isinstance(function, int) else put(b"\0\0" + function.encode() + b"\0")
                for function in wanted]
        entries.append((put(b"".join(struct.pack("<I", ref) for ref in refs) + bytes(4)), library))
    import_dir = put(bytes(20 * (len(entries) + 1)))
    for i, (table, library) in enumerate(entries):
        struct.pack_into("<IIIII", section, import_dir - base + 20 * i, table, 0, 0, text(library),
                         table if iat is None else iat)

    def address(name: str) -> int:
        return {**{n: forward for n in forwarded}, **{n: 0 for n in empty}, **{n: 0x900000 for n in outside},
                **{n: base + len(section) + 8 for n in variables}}.get(name, base)

    struct.pack_into(f"<{count}I", section, function_table - base, *map(address, slots), *[base] * unnamed)
    struct.pack_into("<IIHHIIIIIII", section, export_dir - base, 0, 0, 0, 0, dll_name, first, count, len(listed),
                     function_table, name_table, numbers)
    header = bytearray(0x200)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    header[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", header, 0x44, machine, 1, 0, 0, 0, 224, 0x0102 | (0x2000 if dll else 0))
    struct.pack_into("<H", header, 0x58, 0x10B)
    struct.pack_into("<H", header, 0x58 + 68, 9)  # Windows CE
    struct.pack_into("<I", header, 0x58 + 92, 16)
    struct.pack_into("<IIII", header, 0x58 + 96, export_dir, forward + 16 - export_dir, import_dir,
                     20 * (len(entries) + 1))
    raw = len(section) - cut
    struct.pack_into("<8sIIII", header, 0x58 + 224, b".rdata", raw + (64 if variables else 0), base, raw, 0x200)
    data = bytes(header) + bytes(section)
    return data if size is None else data + bytes(size - len(data))


UTIL_EXPORTS = (*decoder.CALLS[UTIL], "av_log", "av_mallocz")
CODEC_EXPORTS = (*decoder.CALLS[CODEC], "avcodec_decode_audio4", "av_packet_unref")


def decoder_set(filler: bytes = b"") -> dict[str, bytes]:
    """Three files that fit together, as a build of FFmpeg 2.6 for the car would; another
    ``filler`` makes another build of them."""
    return {
        CODEC: pe(CODEC_EXPORTS, {"COREDLL": ["malloc"], UTIL: ["av_log", "av_malloc"]}, filler=filler),
        UTIL: pe(UTIL_EXPORTS, {"coredll.dll": ["malloc", "free"]}, filler=filler),
        FORMAT: pe((*decoder.CALLS[FORMAT], "avformat_open_input"),
                   {"COREDLL.dll": ["free"], CODEC: ["av_packet_unref"], UTIL: ["av_mallocz"]}, filler=filler),
    }


ORIGINALS = decoder_set(b"SyncExtPack's own build" * 40)  # stands in for AutoKit's own three
NEW = decoder_set(b"faster")  # the faster build: shorter than the stock one, as the real one is


class Checks(unittest.TestCase):
    def test_a_set_from_one_build_passes(self):
        decoder.check_set(NEW)
        decoder.check_set(ORIGINALS)
        parsed = decoder.parse(NEW[CODEC])
        self.assertEqual(parsed.machine, 0x01C0)
        self.assertTrue(parsed.dll)
        self.assertEqual(set(parsed.imports), {"coredll.dll", UTIL})  # "COREDLL", as SyncExtPack's own
        self.assertIn("av_parser_close", parsed.exports)

    def test_a_file_that_is_not_a_pe_file_is_refused_with_a_reason(self):
        good = NEW[CODEC]
        for data, why in ((b"", "MZ"), (b"PK\x03\x04" + good[4:], "MZ"),
                          (good[:0x3C] + struct.pack("<I", 0x80) + good[0x40:], "no PE header"),
                          (good[:0x40], "no PE header"), (good[:0x100], "cut short"),
                          (good[:0x58] + b"\x0b\x02" + good[0x5A:], "32-bit"),
                          (good[:0x200 + 8], "cut short")):
            with self.subTest(why), self.assertRaisesRegex(decoder.DecoderError, why):
                decoder.check(CODEC, data)

    def test_a_dll_for_another_processor_is_refused(self):
        self.assertEqual(decoder.check(CODEC, pe(CODEC_EXPORTS, machine=0x01C2)).machine, 0x01C2)  # ARM Thumb
        for machine in (0x01C4, 0x8664, 0x014C):  # ARMv7 (ARMNT), x64, x86
            data = pe(CODEC_EXPORTS, machine=machine)
            with self.subTest(hex(machine)), \
                    self.assertRaisesRegex(decoder.DecoderError, "another processor.*0x01c0 or 0x01c2"):
                decoder.check(CODEC, data)

    def test_a_program_is_not_a_dll(self):
        with self.assertRaisesRegex(decoder.DecoderError, "is not a DLL"):
            decoder.check(UTIL, pe(UTIL_EXPORTS, dll=False))

    def test_every_function_autokit_calls_must_be_exported(self):
        for name, calls in decoder.CALLS.items():
            for missing in (calls[0], calls[-1]):
                data = pe([c for c in calls if c != missing])
                with self.subTest(name=name, missing=missing), \
                        self.assertRaisesRegex(decoder.DecoderError, f"does not export {missing}, which AutoKit"):
                    decoder.check(name, data)

    def test_a_name_counts_only_if_it_leads_to_a_function_in_the_file(self):
        calls = decoder.CALLS[CODEC]
        for kind, why in (("forwarded", "forwarded to another DLL"), ("empty", "without a function"),
                          ("stray", "number is past the end of the table"), ("outside", "leads outside the DLL")):
            data = pe(calls[1:], **{kind: [calls[0]]})
            self.assertIn(calls[0], decoder.parse(data).unusable)
            with self.subTest(kind), self.assertRaisesRegex(
                    decoder.DecoderError, rf"does not export {calls[0]} \(listed, but .*{why}\), which AutoKit"):
                decoder.check(CODEC, data)
        # a variable may sit in the zeroed memory after the section's bytes (SyncExtPack's avcodec
        # has 45), and another of the three may import it; a function AutoKit calls may not
        parsed = decoder.check(CODEC, pe(calls, variables=["ff_h264_cabac_tables"]))
        self.assertIn("ff_h264_cabac_tables", parsed.exports)
        self.assertNotIn("ff_h264_cabac_tables", parsed.filled)
        decoder.check_set({**NEW, FORMAT: pe(decoder.CALLS[FORMAT], {CODEC: ["ff_h264_cabac_tables"]}),
                           CODEC: pe(CODEC_EXPORTS, {UTIL: ["av_malloc"]}, variables=["ff_h264_cabac_tables"])})
        for call in (calls[0], calls[-1]):
            with self.subTest(call), self.assertRaisesRegex(
                    decoder.DecoderError, rf"does not export {call} \(listed, but it leads into zeroed memory, "
                                          r"not to code\), which AutoKit calls"):
                decoder.check(CODEC, pe([c for c in calls if c != call], variables=[call]))

    def test_what_one_takes_from_another_must_lead_to_a_function_there(self):
        for kind in ("forwarded", "empty", "stray", "outside"):
            util = pe([c for c in UTIL_EXPORTS if c != "av_log"], {"coredll.dll": ["free"]}, **{kind: ["av_log"]})
            with self.subTest(kind), self.assertRaisesRegex(
                    decoder.DecoderError, r"takes av_log \(listed, but .*\) from avutil-54.dll, which does not"):
                decoder.check_set({**NEW, UTIL: util})

    def test_a_function_taken_by_number_must_be_there_by_that_number(self):
        for first in (1, 0, 7, 300):  # the table's base: the first function's number
            codec = pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"], UTIL: ["av_malloc"]}, unnamed=2, first=first)
            last = first + len(CODEC_EXPORTS) + 1  # the two unnamed ones are the last two
            parsed = decoder.check(CODEC, codec)  # names lead to their functions whatever the base
            self.assertEqual(parsed.ordinals, frozenset(range(first, last + 1)))
            self.assertLessEqual(set(CODEC_EXPORTS), parsed.exports)
            by_number = pe(decoder.CALLS[FORMAT], {"coredll.dll": ["free"], CODEC: [last, first, "av_packet_unref"]})
            self.assertEqual(decoder.parse(by_number).imports[CODEC], (last, first, "av_packet_unref"))
            decoder.check_set({**NEW, CODEC: codec, FORMAT: by_number})
            for number in {last + 1, max(first - 1, 0), len(CODEC_EXPORTS) + 2} - set(range(first, last + 1)):
                past = pe(decoder.CALLS[FORMAT], {"coredll.dll": ["free"], CODEC: [number]})
                with self.subTest(first=first, number=number), self.assertRaisesRegex(
                        decoder.DecoderError, rf"takes #{number} from avcodec-56.dll, which does not"):
                    decoder.check_set({**NEW, CODEC: codec, FORMAT: past})
        # a number with no function behind it does not count, and a function there only by
        # number cannot be taken by a name
        codec = pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"], UTIL: ["av_malloc"]}, unnamed=2)
        empty =pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"], UTIL: ["av_malloc"]}, empty=["av_zzz"])
        number = decoder.parse(empty).ordinals
        hole = next(n for n in range(1, len(CODEC_EXPORTS) + 2) if n not in number)
        with self.assertRaisesRegex(decoder.DecoderError, rf"takes #{hole} from"):
            decoder.check_set({**NEW, CODEC: empty, FORMAT: pe(decoder.CALLS[FORMAT], {CODEC: [hole]})})
        with self.assertRaisesRegex(decoder.DecoderError, r"takes avcodec_unnamed from"):
            decoder.check_set({**NEW, CODEC: codec, FORMAT: pe(decoder.CALLS[FORMAT], {CODEC: ["avcodec_unnamed"]})})

    def test_every_table_and_name_is_read_only_inside_its_section(self):
        for data, why in ((pe(CODEC_EXPORTS, cut=4), "table that does not fit in its section"),  # the import end
                          (pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"]}, cut=1),
                           "name that runs past the end of its section"),
                          (pe(CODEC_EXPORTS, cut=-16), "cut short"),  # a section past the end of the file
                          (pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"]}, cut=-1), "cut short")):
            with self.subTest(why), self.assertRaisesRegex(decoder.DecoderError, why):
                decoder.check(CODEC, data)
        # the bytes past the section's end are in the file all along: only the section's size changed
        self.assertTrue(pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"]}, cut=1).endswith(b"coredll.dll\0"))
        decoder.check(CODEC, pe(CODEC_EXPORTS, {"coredll.dll": ["malloc"]}))

    def test_the_loader_must_have_somewhere_to_write_each_import(self):
        # the names are read from the lookup list; the addresses go into the address table, which
        # must lie inside the DLL's memory too, every slot whole
        for wanted in ({"coredll.dll": ["malloc"]}, {"coredll.dll": ["malloc", "free", "memcpy"]}):
            good = pe(CODEC_EXPORTS, wanted)
            decoder.check(CODEC, good)
            end = 0x1000 + struct.unpack_from("<I", good, 0x58 + 224 + 8)[0]  # the section's end in memory
            slots = 4 * len(wanted["coredll.dll"])
            decoder.check(CODEC, pe(CODEC_EXPORTS, wanted, iat=end - slots))  # the last slot ends there
            for iat, at in ((0, 0), (0x900000, 0x900000), (end - slots + 2, end - 2)):  # the last slot is cut
                with self.subTest(wanted=len(wanted["coredll.dll"]), iat=hex(iat)), self.assertRaisesRegex(
                        decoder.DecoderError, re.escape(f"import address table outside its sections (0x{at:x})")):
                    decoder.check(CODEC, pe(CODEC_EXPORTS, wanted, iat=iat))

    def test_the_three_must_load_together(self):
        decoder.check_set({**NEW, FORMAT: ORIGINALS[FORMAT]})  # what one takes, the others export
        foreign =pe((*decoder.CALLS[FORMAT],), {"coredll.dll": ["free"], "libgcc_s_sjlj-1.dll": ["__divdi3"]})
        with self.assertRaisesRegex(decoder.DecoderError, "libgcc_s_sjlj-1.dll, which is not one of the three"):
            decoder.check_set({**NEW, FORMAT: foreign})
        wants_more = pe((*decoder.CALLS[FORMAT],), {"coredll.dll": ["free"], CODEC: ["avcodec_send_packet"]})
        with self.assertRaisesRegex(decoder.DecoderError, "avcodec_send_packet from avcodec-56.dll.*one build"):
            decoder.check_set({**NEW, FORMAT: wants_more})
        with self.assertRaisesRegex(decoder.DecoderError, "missing avformat-56.dll"):
            decoder.check_set({CODEC: NEW[CODEC], UTIL: NEW[UTIL]})


class Scripts(unittest.TestCase):
    files = {name: {"old": 100 + i, "new": 200 + i, "old_sha256": "a", "new_sha256": "b"}
             for i, name in enumerate(DECODER_FILES)}

    def test_autokit_is_checked_before_anything_is_touched(self):
        for params, text in (({"files": self.files}, AUTOKIT_BUSY),
                             ({"files": {n: 100 for n in DECODER_FILES}, "restore": "20261115-120000-dec-abcd"},
                              AUTOKIT_BUSY_RESTORE)):
            script = swap_script(Job(SERIAL, "dec", params=params))
            busy = script.index('If (ProcExists("AutoKit.exe"))')
            self.assertLess(busy, min(m.start() for m in re.finditer(r"\bCopy\(", script)))
            # every folder made before it is the report's, on the stick (the script's header)
            self.assertLess(busy, min(m.start() for m in re.finditer(r"\bMkDir\((?!stick|out\))", script)))
            self.assertRegex(script, re.escape(f'WriteFile(out & "\\busy.txt", "{text}")') + r"\r\n +Exit\(\)")
            self.assertIn("Exit button", text)
            self.assertIn("Prepare this", text)  # UpdateService used the stick up: inserting it again does nothing
            self.assertNotRegex(text, r"(?i)insert (it|the stick) again")
            if params.get("restore"):  # it has no backup folder of its own: busy comes first
                self.assertNotIn("If (DirExists(bk))", script)
                self.assertIn("this run changed nothing", text)
                self.assertNotIn("; nothing changed", text)  # the car may hold the decoder job's mix
            else:  # a job cut short says so even while AutoKit runs on its half-changed files
                self.assertLess(script.index("If (DirExists(bk))"), busy)

    def test_the_job_writes_only_autokits_folder_the_backup_and_the_stick(self):
        script = swap_script(Job(SERIAL, "dec", params={"files": self.files}))
        for name in DECODER_FILES:
            self.assertIn(f'Copy(jd & "\\new-{name}", th & "\\{name}", TRUE)', script)
            self.assertIn(f'Copy(bk & "\\{name}", th & "\\{name}", TRUE)', script)  # the rollback
            self.assertIn(f'Copy(th & "\\{name}", out & "\\applied\\{name}", TRUE)', script)
        for target in re.findall(r"Copy\([^,]+, ([^,]+), TRUE\)", script):
            self.assertRegex(target, r'^(th|bk|out|"\\SyncExtendedPack\\_s2am)')
        self.assertNotRegex(script, NO_DELETES)
        self.assertIn('WriteFile(out & "\\dec-applied.txt"', script)
        self.assertIn("AutoKit is not installed; nothing changed", script)

    def swap_jobs(self):
        """Every kind of swap job, and its restore."""
        for kind in SWAP_KINDS:
            screen = {"screen": SCREENS[0]} if kind == "screen" else {}
            allowed = swap_target(kind, screen)[1]
            names = allowed if kind == "dec" else allowed[:1]
            yield Job(SERIAL, kind, params={**screen, "files": {n: {"old": 100, "new": 200} for n in names}})
            yield Job(SERIAL, kind, params={**screen, "files": {n: 100 for n in names},
                                            "restore": "20261115-120000-dec-abcd"})

    def test_a_run_first_clears_the_stop_markers_an_earlier_run_left(self):
        # a stick prepared again for the same job keeps its report folder, and the first marker
        # found there decides the job's status: an earlier run's busy.txt would hide this run's
        # rollback-failed.txt
        stop = r'WriteFile\(out & "\\([\w.-]+)", "[^"]*"\)\n\s*Exit\b'
        for job in self.swap_jobs():
            steps, script = "\n".join(swap_lines(job)) + "\n", swap_script(job)  # the job's own steps
            with self.subTest(job.kind, restore=bool(job.params.get("restore"))):
                cleared = re.findall(r'^Delete\(out & "\\([\w.-]+)"\)$', steps, re.M)
                self.assertEqual(set(cleared), {*re.findall(stop, steps), CHANGING})
                self.assertLessEqual({"missing.txt", "copy-failed.txt", "payload-bad.txt"}, set(cleared))
                self.assertEqual(len(re.findall(r"\bDelete\(", script)), len(cleared))  # nothing else
                last_delete = max(m.start() for m in re.finditer(r"\bDelete\(", steps))
                self.assertLess(last_delete, min(m.start() for m in re.finditer(stop, steps)))
                self.assertLess(last_delete, steps.index("th = "))
                if job.kind == "dec":
                    self.assertIn("busy.txt", cleared)
                    self.assertLess(last_delete, steps.index('If (ProcExists("AutoKit.exe"))'))
                self.assertLess(script.index(f'If (FileExists("\\SyncExtendedPack\\_s2am\\done\\{job.id}.txt"))'),
                                script.index("Delete("))  # a replay changes nothing, the report included

    def test_a_marker_an_earlier_run_left_that_will_not_go_stops_the_run_first(self):
        # it would otherwise speak for this run: an earlier busy.txt beside this run's
        # rollback-failed.txt says nothing changed
        for job in self.swap_jobs():
            lines = swap_lines(job)
            with self.subTest(job.kind, restore=bool(job.params.get("restore"))):
                cleared = re.findall(r'^Delete\(out & "\\([\w.-]+)"\)$', "\n".join(lines), re.M)
                self.assertIn(OLD_REPORT_MARKER, cleared)
                n = len(cleared)
                stop = f'  WriteFile(out & "\\{OLD_REPORT_MARKER}", "{OLD_REPORT}")'
                self.assertEqual(lines[n:5 * n], [line for marker in cleared for line in (
                    f'If (FileExists(out & "\\{marker}"))', stop, "  Exit", "EndIf")])  # right after the deletes
                self.assertFalse([line for line in lines[5 * n:] if line.startswith(("Delete(", "If (FileExists(out"))])

    def test_a_run_deletes_the_copies_an_earlier_run_left_before_it_copies_anything(self):
        # the Mac checks what a run copied onto the stick; a copy there can fail and leave the
        # earlier run's file in place, which would then speak for this run
        for job in self.swap_jobs():
            steps = "\n".join(swap_lines(job))
            with self.subTest(job.kind, restore=bool(job.params.get("restore"))):
                first = min(m.start() for m in re.finditer(r'^\s*(Copy|MkDir\((?!stick|out\))|WriteFile\(out & "\\changing)', steps,
                                                           re.M))
                deleted = re.findall(r'^  DelTree\(out & "\\(\w+)"\)$', steps, re.M)
                written = set(re.findall(r'out & "\\(\w+)\\', steps))  # every folder it copies into on the stick
                self.assertLessEqual({"applied"} if job.params.get("restore") else {"applied", "rolledback", "backup"},
                                     written)
                self.assertLessEqual(written, set(deleted))
                self.assertEqual(deleted, list(READBACK))
                for name in deleted:
                    gone, removed = steps.index(f'DelTree(out & "\\{name}")'), steps.index(f'RmDir(out & "\\{name}")')
                    check = steps.index(f'If (DirExists(out & "\\{name}"))\n  WriteFile(out & "\\{OLD_REPORT_MARKER}", '
                                        f'"{OLD_REPORT}")\n  Exit')
                    self.assertLess(gone, removed)
                    self.assertLess(removed, check)
                    # both decoder jobs run in the car lost their report folder, and they were the
                    # first to call DelTree on a folder that was not there: only on one that exists,
                    # and the report folder is made again before anything is written to it
                    self.assertIn(f'If (DirExists(out & "\\{name}"))\n  DelTree(out & "\\{name}")\n'
                                  f'  RmDir(out & "\\{name}")\nEndIf', steps)
                    self.assertLess(removed, steps.index("MkDir(out)"))
                    self.assertLess(check, first)  # before anything is copied, onto the stick or the car
                    self.assertLess(steps.index("If (NOT DirExists(th))"), gone)
                    if not job.params.get("restore"):  # a job cut short keeps the backup its restore may need
                        self.assertLess(steps.index("If (DirExists(bk))"), gone)
                self.assertLess(steps.index("MkDir(out)"), min(
                    m.start() for m in re.finditer(r'^\s*(Copy\(|WriteFile\(out & "\\changing)', steps, re.M)))
        self.assertIn("nothing changed", OLD_REPORT)
        self.assertEqual(stick.STOPPED[OLD_REPORT_MARKER], "failed")

    def test_the_report_says_when_the_car_starts_to_change(self):
        # an import straight after a power cut must not read as "pending": CHANGING is written
        # once, after every check and the whole backup, before the first file on the car changes
        for job in self.swap_jobs():
            steps = "\n".join(swap_lines(job))
            with self.subTest(job.kind, restore=bool(job.params.get("restore"))):
                writes = [m.start() for m in re.finditer(rf'^\s*WriteFile\(out & "\\{CHANGING}"', steps, re.M)]
                self.assertEqual(len(writes), 1)
                checks = [m.start() for m in re.finditer(r"^\s*If \((?!ok = 0)", steps, re.M)]
                changes = [m.start() for m in re.finditer(r'^\s*(Copy\([^,]+, th|MkDir\(th)', steps, re.M)]
                last_check = max(c for c in checks if c < min(changes))
                self.assertLess(last_check, writes[0])
                self.assertLess(writes[0], min(changes))
                self.assertLess(writes[0], steps.index("ok = 1"))
                if not job.params.get("restore") and job.kind != "dec":
                    self.assertLess(steps.index('If (FileSize(out & "\\backup\\'), writes[0])
                if not job.params.get("restore") and job.kind == "dec":  # the car's own backup is the gate
                    self.assertLess(steps.index('If (FileSize(bk & "\\'), writes[0])
                    self.assertNotIn('If (FileSize(out & "\\backup\\', steps)

    def test_a_job_that_started_before_stops_before_the_cars_files_are_compared(self):
        # a run cut short leaves new files on the car: the size checks would call that a changed car
        for job in self.swap_jobs():
            if job.params.get("restore"):
                continue
            script = swap_script(job)
            with self.subTest(job.kind):
                started = script.index("If (DirExists(bk))")
                self.assertIn('WriteFile(out & "\\started-before.txt"', script[started:])
                compare = [m.start() for m in re.finditer(r'If \((FileSize\(th|ReadFile\(th)', script)]
                self.assertLess(started, min(compare))
                self.assertLess(started, script.index("MkDir(bk)"))
                self.assertIn("run its undo (restore) stick", script)

    @staticmethod
    def block(lines: list[str]) -> str:
        """A regular expression for these script lines exactly, a stop's message ("MSG") aside."""
        return r"\r\n".join(re.escape(line).replace('"MSG"', '"[^"\r\n]+"') for line in lines) + r"\r\n"

    def test_a_failed_copy_puts_all_three_back_before_it_says_so(self):
        job = Job(SERIAL, "dec", params={"files": self.files})
        script = swap_script(job)
        sizes = [(n, f["old"], f["new"]) for n, f in self.files.items()]
        backup = [line for n, old, _ in sizes
                  for line in (f'  If (FileSize(bk & "\\{n}") <> {old})',
                               '    WriteFile(out & "\\backup-failed.txt", "MSG")', "    Exit()", "  EndIf()")]
        self.assertRegex(script, self.block([
            *backup,
            '  WriteFile(jd & "\\phase.txt", "backup-ok" & "^NL^", TRUE)',
            "  If (DirExists(out))",
            f'    WriteFile(out & "\\changing.txt", "{job.id}")',
            "  EndIf()",
            *[f'  Copy(jd & "\\new-{n}", th & "\\{n}", TRUE)' for n, _, _ in sizes],
            "  ok = 1",
            *[line for n, _, new in sizes
              for line in (f'  If (FileSize(th & "\\{n}") <> {new})', "    ok = 0", "  EndIf()")],
            "  If (ok = 0)",
            *[f'    Copy(bk & "\\{n}", th & "\\{n}", TRUE)' for n, _, _ in sizes],
            "    ok = 1",
            *[line for n, old, _ in sizes
              for line in (f'    If (FileSize(th & "\\{n}") <> {old})', "      ok = 0", "    EndIf()")],
            "    If (ok = 0)",
            '      WriteFile(jd & "\\phase.txt", "rollback-failed" & "^NL^", TRUE)',
            '      WriteFile(out & "\\rollback-failed.txt", "MSG")',
            "      Exit()",
            "    EndIf()",
            '    WriteFile(jd & "\\phase.txt", "rolled-back" & "^NL^", TRUE)',
            '    MkDir(out & "\\rolledback")',
            *[f'    Copy(th & "\\{n}", out & "\\rolledback\\{n}", TRUE)' for n, _, _ in sizes],
            '    WriteFile(out & "\\copy-failed.txt", "MSG")',
            "    Exit()",
            "  EndIf()",
            '  WriteFile(jd & "\\phase.txt", "swapped" & "^NL^", TRUE)',
            "EndIf()",
            'MkDir(out & "\\backup")',
            *[f'Copy(bk & "\\{n}", out & "\\backup\\{n}", TRUE)' for n, _, _ in sizes],
            'MkDir(out & "\\applied")']))

    def test_a_dead_stick_cannot_stop_the_swap_and_a_second_visit_writes_the_report(self):
        # the first decoder job in the car backed up, then stopped silently: no write reached the stick
        script = swap_script(Job(SERIAL, "dec", params={"files": self.files}))
        swap = script[script.index("If (swapped = 0)\r\n  If (ProcExists"):script.index('MkDir(out & "\\backup")')]
        self.assertNotIn("FileSize(out", swap)  # no stop inside the swap depends on what the stick holds
        self.assertNotIn("FileExists(out", swap)
        again = script[script.index("If (DirExists(bk))"):script.index("DelTree(out")]
        for n, f in self.files.items():  # all three new files in place: only the report is left to write
            self.assertIn(f'If (FileSize(th & "\\{n}") <> {f["new"]})\r\n    swapped = 0', again)
        self.assertIn('WriteFile(out & "\\started-before.txt"', again)

    def test_a_restore_that_did_not_copy_whole_says_so(self):
        job = Job(SERIAL, "dec", params={"files": {n: 100 + i for i, n in enumerate(DECODER_FILES)},
                                         "restore": "20261115-120000-dec-abcd"})
        script = swap_script(job)
        self.assertRegex(script, self.block([
            f'WriteFile(out & "\\changing.txt", "{job.id}")',
            *[f'Copy(jd & "\\orig-{n}", th & "\\{n}", TRUE)' for n in DECODER_FILES],
            "ok = 1",
            *[line for i, n in enumerate(DECODER_FILES)
              for line in (f'If (FileSize(th & "\\{n}") <> {100 + i})', "  ok = 0", "EndIf()")],
            "If (ok = 0)",
            '  WriteFile(out & "\\copy-failed.txt", "MSG")',
            "  Exit()",
            "EndIf()",
            'MkDir(out & "\\applied")']))
        # UpdateService has used the stick up: the restore runs again only from a stick prepared again
        self.assertIn("Prepare this restore stick again on the Mac (s2am stick prepare", script)
        self.assertNotIn("run the restore stick again", script)

    def test_all_three_or_none(self):
        for files in ({n: f for n, f in self.files.items() if n != FORMAT}, {CODEC: self.files[CODEC]},
                      {**self.files, "swscale-3.dll": self.files[CODEC]}, {}):
            with self.subTest(sorted(files)), self.assertRaises(ValueError):
                swap_script(Job(SERIAL, "dec", params={"files": files}))
        restore = {n: 100 for n in DECODER_FILES}
        script = swap_script(Job(SERIAL, "dec", params={"files": restore, "restore": "20261115-120000-dec-abcd"}))
        for name in DECODER_FILES:
            self.assertIn(f'Copy(jd & "\\orig-{name}", th & "\\{name}", TRUE)', script)
        self.assertIn('WriteFile(out & "\\dec-restored.txt"', script)
        with self.assertRaises(ValueError):
            swap_script(Job(SERIAL, "dec", params={"files": {CODEC: 100, UTIL: 100},
                                                    "restore": "20261115-120000-dec-abcd"}))
        with self.assertRaises(ValueError):  # a decoder job cannot touch a theme file, nor add pictures
            swap_script(Job(SERIAL, "dec", params={"files": {**self.files, "Theme.XML": self.files[CODEC]}}))
        with self.assertRaises(ValueError):
            swap_script(Job(SERIAL, "dec", params={"files": self.files, "added": {"Tiles\\a.png": {"new": 5}}}))

    def test_no_restart_and_no_bundle(self):
        self.assertEqual(swap_target("dec", {}), (AUTOKIT_CE, DECODER_FILES, "decoder"))
        self.assertNotIn("NEED_REBOOT", meta(Job(SERIAL, "dec")).decode("utf-16-le"))
        self.assertNotIn("dec", RESTARTING)
        self.assertNotIn("dec", BUNDLE_PARTS)
        part = Job(SERIAL, "dec", params={"files": self.files})
        with self.assertRaisesRegex(ValueError, "a bundle runs only"):
            bundle_parts(Job(SERIAL, "bundle", params={"parts": [
                {"kind": "dec", "id": part.id, "created_utc": part.created_utc, "params": part.params}]}))


class Status(unittest.TestCase):
    @staticmethod
    def status(*markers: str) -> str:
        """The import's status for a report holding ``markers``, from a stick still in use."""
        with tempfile.TemporaryDirectory() as temp:
            report, updater = Path(temp) / "report", Path(temp) / "SyncExtPack"
            report.mkdir()
            updater.mkdir()
            (updater / "install.bin").write_bytes(b"pack")
            for marker in markers:
                (report / marker).write_text("x")
            return stick._status(report, updater)[0]

    def test_conflicting_markers_read_as_the_worst(self):
        for markers, status in ((("busy.txt", "rollback-failed.txt"), "rollback-failed"),  # an old busy.txt stayed
                                (("busy.txt", CHANGING, "copy-failed.txt"), "failed"),
                                (("stale.txt", "started-before.txt"), "interrupted"),
                                (("busy.txt", CHANGING), "interrupted"),
                                (("started-before.txt", "rollback-failed.txt"), "rollback-failed"),
                                (("busy.txt", OLD_REPORT_MARKER), "failed"),  # this run's stop, not the old one
                                (("stale.txt", OLD_REPORT_MARKER), "failed"),
                                ((CHANGING, OLD_REPORT_MARKER), "interrupted"),  # an earlier run may have cut
                                (("rollback-failed.txt", OLD_REPORT_MARKER), "rollback-failed"),
                                (("queued.txt", "started.txt", "busy.txt"), "busy")):  # a bundle part's own stop
            with self.subTest(markers):
                self.assertEqual(self.status(*markers), status)
                self.assertEqual(self.status(*reversed(markers)), status)

    def test_a_report_that_began_changing_the_car_without_an_outcome_is_interrupted(self):
        for markers, status in (((CHANGING,), "interrupted"), ((CHANGING, "copy-failed.txt"), "failed"),
                                ((CHANGING, "rollback-failed.txt"), "rollback-failed"),
                                ((CHANGING, "started-before.txt"), "interrupted"),
                                ((CHANGING, "dec-applied.txt", "done.txt"), "applied"),  # a finished run
                                ((CHANGING, "dec-applied.txt"), "interrupted"),  # cut before its last lines
                                (("backup",), "pending")):  # cut while backing up: nothing changed yet
            with self.subTest(markers), tempfile.TemporaryDirectory() as temp:
                report, updater = Path(temp) / "report", Path(temp) / "SyncExtPack"
                report.mkdir()
                updater.mkdir()
                (updater / "install.bin").write_bytes(b"pack")  # a power cut: UpdateService never finished
                for marker in markers:
                    (report / marker).write_text("x")
                self.assertEqual(stick._status(report, updater)[0], status)


class Loop(unittest.TestCase):
    """The decoder job through the command line, on a fake car, against a stand-in SyncExtPack."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.upstream = self.tmp / "syncextpack"
        runner = self.upstream / "FullPack" / "RemoveExtPack"
        runner.mkdir(parents=True)
        (runner / "MortScript.exe").write_bytes(b"MZ MortScript stand-in")
        (runner / "RemoveExtPack.exe").write_bytes(b"MZ MortRunner stand-in")
        self.write(self.upstream / decoder.STOCK, ORIGINALS)
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put(f"{AUTOKIT_CE}\\AutoKit.exe", b"MZ AutoKit")
        for name, data in ORIGINALS.items():
            self.car.put(f"{AUTOKIT_CE}\\{name}", data)
        self.build_folder = self.write(self.tmp / "ffmpeg", NEW)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    @staticmethod
    def write(folder: Path, files: dict[str, bytes]) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (folder / name).write_bytes(data)
        return folder

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def build(self, *args):
        """Build a decoder job (not packed); returns the job, its folder and what the CLI said."""
        work = self.tmp / f"job{len(list(self.tmp.glob('job*')))}"
        code, out = self.cli("job", "decoder", *args, "--serial", SERIAL, "--upstream", str(self.upstream),
                             "--no-pack", "--work", str(work))
        self.assertEqual(code, 0, out)
        return Job.from_json((work / "job.json").read_text()), work, out

    def prepared(self, work: Path) -> str:
        (work / "install.bin").write_bytes(b"pack")
        code, out = self.cli("stick", "prepare", str(self.stick), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        return out

    def imported(self) -> str:
        """What `s2am stick import` said; its exit code is left in self.code."""
        self.code, out = self.cli("stick", "import", str(self.stick), "--any-path")
        return out

    def run_built(self, job: Job, work: Path) -> str:
        out = self.prepared(work)
        self.car.insert(self.stick, work, job)
        return out + self.imported()

    def run_job(self, *args):
        job, work, built = self.build(*args)
        return job, work, built, self.run_built(job, work)

    def car_files(self) -> dict[str, bytes]:
        return {name: self.car._resolve(f"{AUTOKIT_CE}\\{name}").read_bytes() for name in DECODER_FILES}

    def refused(self, *args) -> str:
        work = self.tmp / f"refused{len(list(self.tmp.glob('refused*')))}"
        code, out = self.cli("job", "decoder", *args, "--serial", SERIAL, "--upstream", str(self.upstream),
                             "--no-pack", "--work", str(work))
        self.assertNotEqual(code, 0, out)
        self.assertFalse(work.exists())  # refused before anything is staged
        work.mkdir()  # the next refusal gets a folder of its own
        return out

    def test_new_decoder_then_restore(self):
        job, work, built, imported = self.run_job("--from", str(self.build_folder))
        for said in ("replaces AutoKit's three decoder files", "backing them up first", "SYNC does not restart",
                     "s2am job decoder --restore <this job>", "cut short", "AutoKit may not start until the undo "
                     "stick has run", "Exit button", "before opening AutoKit"):
            self.assertIn(said, built)
        self.assertIn("restart SYNC and do not open AutoKit", imported)  # the stick prepare step
        self.assertNotIn("SYNC restarts", imported)
        self.assertIn(f"{job.id}: applied", imported)
        self.assertIn("verified: the new decoder is on the car (3 files match byte for byte)", imported)
        self.assertEqual(self.code, 0)
        self.assertEqual(self.car_files(), NEW)
        self.assertNotIn("NEED_REBOOT", (work / "meta.txt").read_bytes().decode("utf-16-le"))
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / CHANGING).is_file())  # a finished run has it too: done.txt comes first
        for name in DECODER_FILES:
            self.assertEqual((report / "backup" / name).read_bytes(), ORIGINALS[name])
            self.assertEqual(self.car._resolve(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}\\{name}").read_bytes(),
                             ORIGINALS[name])
        self.assertEqual(job.id.split("-")[2], "dec")

        undo, undo_work, built, imported = self.run_job("--restore", job.id)
        self.assertIn("puts AutoKit's own three decoder files back", built)
        self.assertIn("verified: the original decoder is back (3 files match byte for byte)", imported)
        self.assertEqual(self.car_files(), ORIGINALS)
        folder = undo_work / "payload" / undo.job_dir.lstrip("/")
        for name in DECODER_FILES:
            self.assertEqual((folder / f"orig-{name}").read_bytes(), ORIGINALS[name])
        self.assertFalse(list(folder.glob("new-*")))

    def test_a_running_autokit_stops_it_and_the_same_job_runs_after_a_restart(self):
        self.car.autokit_running = True  # opened, then Exit: still running, hidden
        job, work, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertIn(f"{job.id}: busy", imported)
        self.assertIn("restart SYNC, run `s2am stick prepare` with the same job again", imported)
        self.assertEqual(self.car_files(), ORIGINALS)
        self.assertFalse(self.car.exists(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}"))
        self.assertFalse(self.car.exists(job.done_marker))
        self.car.autokit_running = False  # SYNC restarted, AutoKit not opened yet
        imported = self.run_built(job, work)
        self.assertIn("verified: the new decoder is on the car", imported)
        self.assertEqual(self.car_files(), NEW)

    def test_a_later_run_of_the_same_job_reports_its_own_outcome(self):
        # the stick keeps the job's report folder: the busy.txt of the first run must not speak
        # for the second, which stopped because the originals did not go back whole
        self.car.autokit_running = True
        job, work, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertIn(f"{job.id}: busy", imported)
        self.car.autokit_running = False
        self.car.broken_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        imported = self.run_built(job, work)
        self.assertIn(f"{job.id}: rollback-failed", imported)
        self.assertNotIn(f"{job.id}: busy", imported)
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / "rollback-failed.txt").is_file())
        self.assertFalse((report / "busy.txt").exists())
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "rollback-failed")

    def test_a_run_cut_short_says_interrupted_and_its_undo_puts_the_originals_back(self):
        job, work, _ = self.build("--from", str(self.build_folder))
        (work / "install.bin").write_bytes(b"pack")
        code, out = self.cli("stick", "prepare", str(self.stick), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        self.car.power_cut_after_copy = f"{AUTOKIT_CE}\\{CODEC}".lower()
        self.car.insert(self.stick, work, job)  # the power goes once the new avcodec is in
        mix = {**ORIGINALS, CODEC: NEW[CODEC]}
        self.assertEqual(self.car_files(), mix)
        self.car.insert(self.stick, work, job)  # the same stick runs again at the next start
        _, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        self.assertIn(f"{job.id}: interrupted", imported)  # not stale: the car did not change on its own
        self.assertIn("Run the undo stick", imported)
        self.assertEqual(self.car_files(), mix)  # the second run changed nothing
        self.assertTrue((Store().report(SERIAL, job.id) / "started-before.txt").is_file())
        _, _, _, imported = self.run_job("--restore", job.id)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_an_import_straight_after_a_power_cut_says_interrupted(self):
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.power_cut_after_copy = f"{AUTOKIT_CE}\\{CODEC}".lower()
        self.car.insert(self.stick, work, job)  # the power goes; the stick goes back to the Mac as it is
        self.assertTrue((self.stick / "SyncExtPack" / "install.bin").is_file())  # UpdateService never finished
        imported = self.imported()
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{job.id}: interrupted: it started but did not finish (power cut or stick pulled). "
                      f"Run the undo stick. Build it with `s2am job decoder --restore {job.id}`; "
                      "AutoKit may not start until it has run", imported)
        self.assertNotIn("pending", imported)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "interrupted")
        _, _, _, imported = self.run_job("--restore", job.id)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_a_power_cut_before_any_change_leaves_the_job_pending(self):
        # cut while the backup is copied: the car's decoder is untouched and the report has no
        # CHANGING yet; the stick still runs the job at the next start, which then says it started before
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.power_cut_after_copy = f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}\\{UTIL}".lower()
        self.car.insert(self.stick, work, job)
        self.assertEqual(self.car_files(), ORIGINALS)
        self.assertIn(f"{job.id}: pending", self.imported())

    def test_a_run_cut_short_says_so_even_while_autokit_runs(self):
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.power_cut_after_copy = f"{AUTOKIT_CE}\\{CODEC}".lower()
        self.car.insert(self.stick, work, job)
        mix = {**ORIGINALS, CODEC: NEW[CODEC]}
        self.car.autokit_running = True  # opened at the next start, on the half-changed decoder
        self.car.insert(self.stick, work, job)
        imported = self.imported()
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{job.id}: interrupted", imported)
        self.assertNotIn(f"{job.id}: busy", imported)  # busy would say "nothing changed" and offer the same job
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / "started-before.txt").is_file())
        self.assertFalse((report / "busy.txt").exists())
        # its undo waits for AutoKit too, and says this run changed nothing, not that all is well
        undo, undo_work, _, imported = self.run_job("--restore", job.id)
        self.assertIn(f"{undo.id}: busy: the app was running, so this run changed nothing", imported)
        self.assertTrue((Store().report(SERIAL, undo.id) / "busy.txt").is_file())
        self.assertIn(AUTOKIT_BUSY_RESTORE, swap_script(undo))  # what the car writes into it
        self.assertEqual(self.car_files(), mix)
        self.car.autokit_running = False
        imported = self.run_built(undo, undo_work)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_a_restore_cut_short_runs_again_from_its_stick_prepared_again(self):
        job, _, _, _ = self.run_job("--from", str(self.build_folder))
        undo, undo_work, _ = self.build("--restore", job.id)
        self.prepared(undo_work)
        self.car.power_cut_after_copy = f"{AUTOKIT_CE}\\{UTIL}".lower()
        self.car.insert(self.stick, undo_work, undo)
        imported = self.imported()
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{undo.id}: interrupted: the original files may not all be back. Prepare this restore "
                      f"stick again with `s2am stick prepare` and the same job ({undo.id}), then insert it", imported)
        imported = self.run_built(undo, undo_work)
        self.assertEqual(self.code, 0, imported)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_a_copy_damaged_at_full_length_is_not_a_success(self):
        # the sizes match, so the car's own checks pass; only the Mac's byte check sees it
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        job, work, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{job.id}: not-verified: the files on the car do not match byte for byte (below). "
                      f"Run the undo stick. Build it with `s2am job decoder --restore {job.id}`; "
                      "AutoKit may not start until it has run", imported)
        self.assertIn(f"NOT verified: these files on the car are not the planned ones: ['{UTIL}']", imported)
        self.assertNotIn("verified: the new decoder", imported)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")
        # the same stick again: the car counts the job as done and runs nothing; the failed check stands
        imported = self.run_built(job, work)
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{job.id}: not-verified (stick was inserted again; nothing ran twice)", imported)
        self.assertIn(f"NOT verified: these files on the car are not the planned ones: ['{UTIL}']\n",
                      imported)  # checked again from the first run's copy on this stick
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")
        # a restore damaged the same way is not a success either, and a new restore job is the way on
        undo, _, _, imported = self.run_job("--restore", job.id)
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{undo.id}: not-verified: the original files are not all back. Build the restore again "
                      f"(a new job) with `s2am job decoder --restore {job.id}`", imported)
        self.car.garbled_copies.clear()
        _, _, _, imported = self.run_job("--restore", job.id)
        self.assertEqual(self.code, 0, imported)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_a_replay_before_the_first_import_is_still_checked(self):
        # the job runs to the end with avutil damaged at full length (its size passes); the power
        # goes before UpdateService uses the stick up, so the next start runs it again: a replay
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.power_cut_after_job = True
        self.car.insert(self.stick, work, job)
        self.car.insert(self.stick, work, job)
        imported = self.imported()
        self.assertIn("nothing ran twice", imported)
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{job.id}: not-verified", imported)  # checked from its first run's copy on the stick
        self.assertIn(f"NOT verified: these files on the car are not the planned ones: ['{UTIL}']", imported)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")

    def test_a_replay_with_nothing_to_check_is_not_verified_until_its_first_stick_is(self):
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.insert(self.stick, work, job)  # it runs, but this stick stays in a drawer for now
        other = self.tmp / "other"
        other.mkdir()
        code, out = self.cli("stick", "prepare", str(other), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        self.car.insert(other, work, job)  # the car runs nothing: the job is done there
        code, imported = self.cli("stick", "import", str(other), "--any-path")
        self.assertNotEqual(code, 0)
        self.assertIn(f"{job.id}: not-verified (stick was inserted again; nothing ran twice)", imported)
        self.assertIn("this stick holds no copy from the run that finished the job", imported)
        imported = self.imported()  # the first stick, with its run's copy: the check succeeds now
        self.assertEqual(self.code, 0, imported)
        self.assertIn(f"{job.id}: applied", imported)
        self.assertIn("verified: the new decoder is on the car", imported)
        record = Store().job(SERIAL, job.id)
        self.assertEqual(record["status"], "applied")
        self.assertNotIn("not_verified", record)

    def test_a_failed_check_survives_a_stick_imported_before_it_ran(self):
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        job, work, _, _ = self.run_job("--from", str(self.build_folder))
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        code, out = self.cli("stick", "prepare", str(fresh), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        code, imported = self.cli("stick", "import", str(fresh), "--any-path")  # before it went to the car
        self.assertIn(f"{job.id}: pending", imported)
        self.assertIn("its last byte check, at an earlier import: NOT verified", imported)
        self.assertIn("not_verified", Store().job(SERIAL, job.id))
        self.car.insert(fresh, work, job)  # a replay: the car runs nothing
        code, imported = self.cli("stick", "import", str(fresh), "--any-path")
        self.assertNotEqual(code, 0)
        self.assertIn(f"{job.id}: not-verified", imported)
        self.assertIn("(from an earlier import)", imported)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")

    def test_the_newest_inventory_still_counts_but_says_it_was_not_verified(self):
        _, _, _, _ = self.run_job("--from", str(self.build_folder))
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        self.car.put(f"{AUTOKIT_CE}\\{CODEC}", ORIGINALS[CODEC])  # a fresh car for a second job
        self.car.put(f"{AUTOKIT_CE}\\{UTIL}", ORIGINALS[UTIL])
        self.car.put(f"{AUTOKIT_CE}\\{FORMAT}", ORIGINALS[FORMAT])
        job, _, _, _ = self.run_job("--from", str(self.build_folder))
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")
        code, out = self.cli("status", "--serial", SERIAL)
        self.assertIn(f"report {job.id}", out)  # the newest picture of the car, not an older one
        self.assertIn(f"warning: job {job.id} did not pass the byte check", out)
        self.assertEqual(Store().latest_inventory(SERIAL)[0], job.id)

    def cut_restore(self):
        """A decoder job, then its restore cut short once it has copied the originals back onto the
        stick (applied/), before it is done: (restore job, its folder, the CE path of applied/)."""
        job, _, _, _ = self.run_job("--from", str(self.build_folder))
        undo, undo_work, _ = self.build("--restore", job.id)
        self.prepared(undo_work)
        applied = f"{STICK_MOUNTS[0]}\\s2am\\reports\\{undo.id}\\applied"
        self.car.power_cut_after_copy = f"{applied}\\{FORMAT}".lower()  # the last of the three
        self.car.insert(self.stick, undo_work, undo)
        report = self.stick / "s2am" / "reports" / undo.id
        self.assertEqual({p.name: p.read_bytes() for p in (report / "applied").iterdir()}, ORIGINALS)
        self.assertFalse((report / "done.txt").exists())
        return undo, undo_work, applied

    def test_a_retried_restore_is_not_verified_by_the_copies_of_the_run_before(self):
        # at the next start the restore runs again: avutil goes wrong at full length (its size
        # passes) and so does its copy onto the stick, which would leave the earlier run's good copy
        undo, undo_work, applied = self.cut_restore()
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        self.car.locked_files.add(f"{applied}\\{UTIL}".lower())
        self.car.insert(self.stick, undo_work, undo)
        imported = self.imported()
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{undo.id}: not-verified", imported)
        self.assertIn(f"NOT verified: these files on the car are not the planned ones: ['{UTIL}']", imported)
        self.assertNotIn("verified: the original decoder is back", imported)
        report = Store().report(SERIAL, undo.id)
        self.assertFalse((report / "applied" / UTIL).exists())  # this run's copy failed; the old one is gone
        self.assertEqual((report / "applied" / CODEC).read_bytes(), ORIGINALS[CODEC])  # this run's
        self.assertNotEqual(self.car_files()[UTIL], ORIGINALS[UTIL])

    def test_deltree_on_a_folder_that_is_not_there_takes_the_report_folder_with_it(self):
        # the car, 2026-11-15 and 11-16: both decoder jobs came back without their report folder.
        # MortScript's DelTree on a missing folder removes the empty folder it searched. Run on the
        # simulated car: the script as it was loses the report, the script as it is keeps it.
        from s2am import job as job_module
        unguarded = [line for name in READBACK
                     for line in (f'DelTree(out & "\\{name}")', f'RmDir(out & "\\{name}")')]
        with mock.patch.object(job_module, "_clear_readback", lambda: unguarded):
            job, work, _ = self.build("--from", str(self.build_folder))
            self.prepared(work)
            self.car.insert(self.stick, work, job)
            self.assertFalse((self.stick / "s2am" / "reports" / job.id).exists())
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.insert(self.stick, work, job)
        report = self.stick / "s2am" / "reports" / job.id
        self.assertTrue((report / "dec-applied.txt").is_file())
        self.assertEqual({p.name: p.read_bytes() for p in (report / "backup").iterdir()}, ORIGINALS)

    def test_copies_that_cannot_be_deleted_stop_the_run_before_it_changes_anything(self):
        undo, undo_work, applied = self.cut_restore()
        self.car.stuck_files.add(applied.lower())
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())  # would damage avutil, if it ran
        self.car.insert(self.stick, undo_work, undo)
        self.assertEqual(self.car_files(), ORIGINALS)  # as the cut run left it
        imported = self.imported()
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{undo.id}: failed", imported)
        self.assertNotIn("verified", imported)
        _, shown = self.cli("report", "--serial", SERIAL, undo.id)
        self.assertIn(f"[{OLD_REPORT_MARKER}] ", shown)  # the car writes OLD_REPORT there (the fake car its name)
        self.car.garbled_copies.clear()
        other = self.tmp / "other"  # as it says: the job on another stick
        other.mkdir()
        code, out = self.cli("stick", "prepare", str(other), "--job", str(undo_work), "--any-path")
        self.assertEqual(code, 0, out)
        self.car.insert(other, undo_work, undo)
        code, imported = self.cli("stick", "import", str(other), "--any-path")
        self.assertEqual(code, 0, imported)
        self.assertIn("verified: the original decoder is back", imported)

    def test_a_replay_of_a_run_cut_short_is_not_checked_from_its_copies(self):
        # the restore cut short on this stick finishes from another, where avutil goes wrong at full
        # length; this stick then replays: its copies are from the run that did not finish
        undo, undo_work, _ = self.cut_restore()
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        other = self.tmp / "other"
        other.mkdir()
        code, out = self.cli("stick", "prepare", str(other), "--job", str(undo_work), "--any-path")
        self.assertEqual(code, 0, out)
        self.car.insert(other, undo_work, undo)
        code, imported = self.cli("stick", "import", str(other), "--any-path")
        self.assertIn(f"{undo.id}: not-verified", imported)
        self.car.insert(self.stick, undo_work, undo)  # the first stick: the car runs nothing
        imported = self.imported()
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{undo.id}: not-verified (stick was inserted again; nothing ran twice)", imported)
        self.assertIn("(from an earlier import)", imported)
        self.assertNotIn("verified: the original decoder is back", imported)
        self.assertEqual(Store().job(SERIAL, undo.id)["status"], "not-verified")

    def test_a_stick_prepared_again_keeps_the_jobs_place_among_the_inventories(self):
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        job, work, _, _ = self.run_job("--from", str(self.build_folder))  # not-verified: the newest inventory
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        code, out = self.cli("stick", "prepare", str(fresh), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "on-stick")
        code, out = self.cli("status", "--serial", SERIAL)
        self.assertIn(f"report {job.id}", out)
        self.assertIn(f"warning: job {job.id} did not pass the byte check", out)
        self.car.garbled_copies.clear()
        undo, _, _, _ = self.run_job("--restore", job.id)  # a newer inventory
        self.assertEqual(Store().latest_inventory(SERIAL)[0], undo.id)
        code, imported = self.cli("stick", "import", str(fresh), "--any-path")  # before the car ran it
        self.assertIn(f"{job.id}: pending", imported)
        record = Store().job(SERIAL, job.id)
        self.assertEqual((record["status"], record["outcome"]), ("pending", "not-verified"))
        self.assertEqual(Store().latest_inventory(SERIAL)[0], undo.id)  # it keeps its own time, too
        self.assertEqual([r["id"] for r in Store().successful(SERIAL)][-2:], [job.id, undo.id])

    def test_any_job_prepared_again_keeps_its_place_among_the_inventories(self):
        work = self.tmp / "inventory"  # not a swap: no byte check, only the import records its outcome
        code, out = self.cli("job", "inventory", "--serial", SERIAL, "--upstream", str(self.upstream), "--no-pack",
                             "--work", str(work))
        self.assertEqual(code, 0, out)
        job = Job.from_json((work / "job.json").read_text())
        self.assertIn(f"{job.id}: applied", self.run_built(job, work))
        self.prepared(work)  # the same stick again: the car would replay it
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "on-stick")
        self.assertEqual(Store().latest_inventory(SERIAL)[0], job.id)

    def test_a_record_from_before_outcomes_were_kept_keeps_its_place(self):
        work = self.tmp / "inventory"
        code, out = self.cli("job", "inventory", "--serial", SERIAL, "--upstream", str(self.upstream), "--no-pack",
                             "--work", str(work))
        self.assertEqual(code, 0, out)
        job = Job.from_json((work / "job.json").read_text())
        self.run_built(job, work)
        store = Store()

        def saved_before(status: str) -> str:  # the record as an import saved it before OUTCOME: status only
            record = {key: value for key, value in store.job(SERIAL, job.id).items() if key != "outcome"}
            store.save_job(SERIAL, job.id, {**record, "status": status})
            return record["imported_utc"]
        when = saved_before("applied")
        self.prepared(work)  # through `s2am stick prepare`
        record = store.job(SERIAL, job.id)
        self.assertEqual((record["status"], record["outcome"], record["imported_utc"]), ("on-stick", "applied", when))
        self.assertEqual(store.latest_inventory(SERIAL)[0], job.id)
        # a replay's record ("applied" is kept as it is: the import says it ran from another stick)
        when = saved_before("already-applied")
        fresh = self.tmp / "fresh"  # a stick put together without this Mac's records, imported before it ran
        fresh.mkdir()
        stick.prepare(fresh, work / "install.bin", job, require_volume=False)
        code, imported = self.cli("stick", "import", str(fresh), "--any-path")
        self.assertIn(f"{job.id}: pending", imported)
        record = store.job(SERIAL, job.id)
        self.assertEqual((record["status"], record["outcome"], record["imported_utc"]),
                         ("pending", "already-applied", when))
        self.assertEqual(store.latest_inventory(SERIAL)[0], job.id)

    def test_a_stop_marker_an_earlier_run_left_that_will_not_go_stops_the_next_run(self):
        # the first run finds AutoKit running; at the next start its busy.txt will not delete, and
        # a copy and the rollback would both fail: the import must not read "busy, nothing changed"
        self.car.autokit_running = True
        job, work, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertIn(f"{job.id}: busy", imported)
        self.car.autokit_running = False
        self.car.stuck_files.add(f"{STICK_MOUNTS[0]}\\s2am\\reports\\{job.id}\\busy.txt".lower())
        self.car.broken_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        imported = self.run_built(job, work)
        self.assertEqual(self.car_files(), ORIGINALS)  # it stopped before anything on the car changed
        self.assertFalse(self.car.exists(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}"))
        self.assertNotEqual(self.code, 0)
        self.assertIn(f"{job.id}: failed", imported)
        self.assertNotIn(f"{job.id}: busy", imported)
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / OLD_REPORT_MARKER).is_file())
        self.assertTrue((report / "busy.txt").is_file())  # still there, and read below the stop beside it
        self.assertFalse((report / CHANGING).exists())

    def test_a_backup_that_did_not_reach_the_stick_whole_does_not_stop_the_swap_and_is_not_verified(self):
        # the car's backup copied, the stick's copy of it did not (a short copy, or none at all):
        # the car-first job swaps all the same, and the Mac says it could not check, not that all is well
        for knob in (self.car.broken_copies, self.car.locked_files):
            job, work, _ = self.build("--from", str(self.build_folder))
            knob.add(f"{STICK_MOUNTS[0]}\\s2am\\reports\\{job.id}\\backup\\{UTIL}".lower())
            imported = self.run_built(job, work)
            with self.subTest(knob=knob):
                self.assertEqual(self.car_files(), NEW)
                self.assertNotEqual(self.code, 0)
                self.assertIn(f"{job.id}: not-verified", imported)
                report = Store().report(SERIAL, job.id)
                self.assertFalse((report / "backup-failed.txt").exists())
                self.assertTrue((report / "dec-applied.txt").is_file())
                backup = self.car._resolve(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}")
                self.assertEqual({p.name: p.read_bytes() for p in backup.iterdir()}, ORIGINALS)
            _, _, _, undone = self.run_job("--restore", job.id)  # back to the originals for the next knob
            self.assertEqual(self.car_files(), ORIGINALS)
            knob.clear()

    def test_a_second_visit_after_a_finished_swap_only_writes_the_report(self):
        # the swap finished but its report never reached the stick (as in the car, 2026-11-16): the
        # backup is on the car and the three new files are in place, so the same job put in again
        # writes the report, AutoKit running or not, and changes nothing
        job, work, _ = self.build("--from", str(self.build_folder))
        self.prepared(work)
        self.car.insert(self.stick, work, job)
        self.assertEqual(self.car_files(), NEW)
        shutil.rmtree(self.stick / "s2am" / "reports" / job.id)  # the report was lost
        self.car._resolve(ce_path(job.done_marker)).unlink()     # and with it the done marker
        self.prepared(work)
        self.car.running.add("autokit.exe")
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())  # would damage avutil, if it copied again
        self.car.insert(self.stick, work, job)
        self.assertEqual(self.car_files(), NEW)
        imported = self.imported()
        self.assertIn(f"{job.id}: applied", imported)
        report = Store().report(SERIAL, job.id)
        self.assertFalse((report / "busy.txt").exists())
        self.assertFalse((report / "started-before.txt").exists())
        self.assertEqual({p.name: p.read_bytes() for p in (report / "backup").iterdir()}, ORIGINALS)

    def test_a_backup_that_was_never_made_on_the_car_stops_before_any_change(self):
        job, work, _ = self.build("--from", str(self.build_folder))
        self.car.locked_files.add(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}\\{UTIL}".lower())
        imported = self.run_built(job, work)
        self.assertEqual(self.car_files(), ORIGINALS)
        self.assertIn(f"{job.id}: failed", imported)
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / "backup-failed.txt").is_file())
        self.assertFalse((report / CHANGING).exists())

    def test_the_restore_carries_the_originals_so_the_cars_backup_is_not_needed(self):
        job, _, _, _ = self.run_job("--from", str(self.build_folder))
        shutil.rmtree(self.car._resolve(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}"))
        _, _, _, imported = self.run_job("--restore", job.id)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_the_restore_waits_for_autokit_too(self):
        job, _, _, _ = self.run_job("--from", str(self.build_folder))
        self.car.running.add("autokit.exe")
        undo, _, _, imported = self.run_job("--restore", job.id)
        self.assertIn(f"{undo.id}: busy", imported)
        self.assertEqual(self.car_files(), NEW)

    def test_a_file_autokit_holds_does_not_copy_and_the_others_go_back(self):
        # AutoKit opened after the check: its avcodec cannot be written, the other two are
        self.car.locked_files.add(f"{AUTOKIT_CE}\\{CODEC}".lower())
        job, _, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertIn(f"{job.id}: failed", imported)
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / "copy-failed.txt").is_file())
        self.assertFalse((report / "rollback-failed.txt").exists())
        # the car compared sizes; the Mac compares what the rollback put back, byte for byte
        self.assertIn("  verified: the originals are back (3 files match byte for byte)", imported)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "failed")
        self.assertEqual(self.car_files(), ORIGINALS)  # never a mix of old and new

    def test_a_rollback_that_matches_in_size_only_is_not_verified(self):
        # avcodec is held by AutoKit, so the job rolls back; avutil goes wrong at full length,
        # both ways, and every size still matches
        self.car.locked_files.add(f"{AUTOKIT_CE}\\{CODEC}".lower())
        self.car.garbled_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        job, _, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertNotEqual(self.code, 0)
        report = Store().report(SERIAL, job.id)
        self.assertTrue((report / "copy-failed.txt").is_file())
        self.assertIn(f"{job.id}: not-verified: the files on the car do not match byte for byte (below). "
                      f"Run the undo stick. Build it with `s2am job decoder --restore {job.id}`; "
                      "AutoKit may not start until it has run", imported)
        self.assertIn(f"NOT verified: after the rollback these files on the car are not the originals: ['{UTIL}']",
                      imported)
        self.assertEqual(Store().job(SERIAL, job.id)["status"], "not-verified")
        self.assertNotEqual(self.car_files()[UTIL], ORIGINALS[UTIL])
        self.car.locked_files.clear()
        self.car.garbled_copies.clear()
        _, _, _, imported = self.run_job("--restore", job.id)
        self.assertEqual(self.code, 0, imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_a_copy_that_breaks_and_will_not_roll_back_needs_the_restore_stick(self):
        self.car.broken_copies.add(f"{AUTOKIT_CE}\\{UTIL}".lower())
        job, _, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertIn(f"{job.id}: rollback-failed", imported)
        now = self.car_files()
        self.assertEqual({n: now[n] for n in (CODEC, FORMAT)}, {n: ORIGINALS[n] for n in (CODEC, FORMAT)})
        self.assertNotEqual(now[UTIL], ORIGINALS[UTIL])
        self.car.broken_copies.clear()
        _, _, _, imported = self.run_job("--restore", job.id)
        self.assertIn("verified: the original decoder is back", imported)
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_a_changed_car_stops_the_job(self):
        self.car.put(f"{AUTOKIT_CE}\\{UTIL}", ORIGINALS[UTIL] + b"another AutoKit")
        before = self.car_files()
        job, _, _, imported = self.run_job("--from", str(self.build_folder))
        self.assertIn(f"{job.id}: stale", imported)
        self.assertEqual(self.car_files(), before)
        self.assertFalse(self.car.exists(f"\\SyncExtendedPack\\_s2am\\backup\\{job.id}"))

    def test_an_incomplete_job_folder_stops_the_job(self):
        job, work, _ = self.build("--from", str(self.build_folder))
        staged = work / "payload" / job.job_dir.lstrip("/") / f"new-{FORMAT}"
        staged.write_bytes(staged.read_bytes()[:-100])
        imported = self.run_built(job, work)
        self.assertIn(f"{job.id}: failed", imported)
        self.assertTrue((Store().report(SERIAL, job.id) / "payload-bad.txt").is_file())
        self.assertEqual(self.car_files(), ORIGINALS)

    def test_the_plan_refuses_files_that_would_not_load(self):
        cases = (
            ({UTIL: NEW[UTIL], FORMAT: NEW[FORMAT]}, f"has no {CODEC}: a decoder job replaces all three"),
            ({**NEW, UTIL: pe(UTIL_EXPORTS, {"coredll.dll": ["free"]}, machine=0x8664)}, "another processor"),
            ({**NEW, CODEC: pe([c for c in CODEC_EXPORTS if c != "av_parser_close"])}, "av_parser_close"),
            ({**NEW, FORMAT: pe(decoder.CALLS[FORMAT], dll=False)}, "not a DLL"),
            ({**NEW, FORMAT: pe(decoder.CALLS[FORMAT], {CODEC: ["avcodec_send_packet"]})}, "not from one build"),
            ({**NEW, CODEC: ORIGINALS[CODEC]}, "the same as AutoKit's own"),
            ({**NEW, UTIL: pe(UTIL_EXPORTS, filler=b"x", size=len(ORIGINALS[UTIL]))},
             "exactly as long as AutoKit's own"),
            ({**NEW, CODEC: b"<html>"}, "does not start with MZ"),
        )
        for i, (files, why) in enumerate(cases):
            folder = self.tmp / f"bad{i}"
            self.write(folder, files)
            with self.subTest(why):
                self.assertIn(why, self.refused("--from", str(folder)))
        self.assertIn("is not a folder", self.refused("--from", str(self.tmp / "nowhere")))

    def test_the_restore_is_only_for_a_decoder_job_and_its_originals(self):
        job, _, _, _ = self.run_job("--from", str(self.build_folder))
        undo, _, _, _ = self.run_job("--restore", job.id)
        self.assertIn("is not a decoder job", self.refused("--restore", undo.id))  # an undo of an undo
        other = Job(SERIAL, "theme", params={"files": {}})
        Store().save_job(SERIAL, other.id, {**json.loads(other.to_json()), "status": "applied"})
        self.assertIn("is not a decoder job", self.refused("--restore", other.id))
        self.write(self.upstream / decoder.STOCK, {UTIL: ORIGINALS[UTIL] + b"a newer SyncExtPack"})
        self.assertIn(f"SyncExtPack's {UTIL} is not what {job.id} replaced", self.refused("--restore", job.id))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):  # one or the other
            cli.main(["job", "decoder", "--from", str(self.build_folder), "--restore", job.id, "--serial", SERIAL])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["job", "decoder", "--serial", SERIAL])

    def test_no_syncextpack_no_decoder_job(self):
        shutil.rmtree(self.upstream / decoder.STOCK)
        self.assertIn("SyncExtPack's AutoKit folder", self.refused("--from", str(self.build_folder)))


if __name__ == "__main__":
    unittest.main()
