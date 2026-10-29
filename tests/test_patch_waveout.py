"""Tests for tools/patch_waveout.py against the real SyncExtPack binaries.

The fixtures live in the sibling syncextpack clone; the tests skip without it.
"""
import contextlib
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import patch_waveout as pw  # noqa: E402

APPS = ROOT.parent / "syncextpack" / "FullPack" / "SyncExtendedPack" / "Apps"
AUTOKIT = APPS / "Media" / "AutoKit"
HOOK = APPS / "Media" / "VideoPlayer_EN" / "WaveOutHooks.dll"
QUARTZ = APPS / "Media" / "VideoPlayer_EN" / "Filters" / "quartz.dll"


def imports(image):
    return {name: [value for _, value in image.thunks(lookup, iat)]
            for _, name, lookup, iat in image.import_descriptors()}


@unittest.skipUnless(HOOK.exists(), "syncextpack fixtures not present")
class PatchAutoKit(unittest.TestCase):
    targets = ("AutoKit.exe", "libgstwaveoutsink.dll", "libgstwaveform.dll")

    def patched(self, name):
        original = (AUTOKIT / name).read_bytes()
        return original, pw.patch(original, HOOK.read_bytes())

    def test_hook_dll_is_imported_with_custom_functions(self):
        for name in self.targets:
            with self.subTest(name):
                _, out = self.patched(name)
                image = pw.PEImage(out)
                hook = imports(image)[pw.HOOK_DLL_NAME]
                functions = {image.cstring(value + 2) for value in hook}
                self.assertEqual(functions, {"waveOutOpenCustom", "waveOutCloseCustom"})

    def test_hook_iat_matches_lookup_table_and_is_terminated(self):
        for name in self.targets:
            with self.subTest(name):
                _, out = self.patched(name)
                image = pw.PEImage(out)
                _, _, lookup, iat = image.import_descriptors()[-1]
                lookup_table = image.rva_to_offset(lookup)
                address_table = image.rva_to_offset(iat)
                for i in range(2):
                    entry = image.u32(address_table + 4 * i)
                    self.assertNotEqual(entry, 0)
                    self.assertEqual(entry, image.u32(lookup_table + 4 * i))
                    self.assertEqual(entry % 2, 0)  # hint/name entries are 2-byte aligned
                self.assertEqual(image.u32(address_table + 8), 0)
                self.assertEqual(image.u32(lookup_table + 8), 0)
                rva, size = image.directory(pw.DIR_IMPORT)
                terminator = image.rva_to_offset(rva) + size - 20
                self.assertEqual(bytes(image.data[terminator:terminator + 20]), b"\0" * 20)

    def test_original_imports_are_kept_unchanged(self):
        for name in self.targets:
            with self.subTest(name):
                original, out = self.patched(name)
                before, after = imports(pw.PEImage(original)), imports(pw.PEImage(out))
                hook = after.pop(pw.HOOK_DLL_NAME)
                self.assertEqual(before, after)
                self.assertEqual(len(hook), 2)

    def test_thunks_point_at_hook_slots(self):
        for name in self.targets:
            with self.subTest(name):
                original, out = self.patched(name)
                before, after = pw.PEImage(original), pw.PEImage(out)
                hook = [d for d in after.import_descriptors() if d[1] == pw.HOOK_DLL_NAME][0]
                slots = {after.cstring(value + 2): slot
                         for slot, value in after.thunks(hook[2], hook[3])}
                for redirect in pw.find_redirects(before, pw.DEFAULT_FUNCTIONS):
                    target = before.image_base + slots[redirect.function + "Custom"]
                    for literal in redirect.thunk_literal_offsets:
                        self.assertEqual(after.u32(literal), target)

    def test_only_headers_thunk_literals_and_new_section_change(self):
        for name in self.targets:
            with self.subTest(name):
                original, out = self.patched(name)
                before = pw.PEImage(original)
                allowed = set()
                for redirect in pw.find_redirects(before, pw.DEFAULT_FUNCTIONS):
                    for literal in redirect.thunk_literal_offsets:
                        allowed.update(range(literal, literal + 4))
                header_end = before.section_table + 40 * (len(before.sections) + 1)
                changed = [i for i in range(header_end, len(original))
                           if original[i] != out[i] and i not in allowed]
                self.assertEqual(changed, [])

    def test_new_section_is_well_formed(self):
        for name in self.targets:
            with self.subTest(name):
                original, out = self.patched(name)
                before, after = pw.PEImage(original), pw.PEImage(out)
                self.assertEqual(len(after.sections), len(before.sections) + 1)
                new = after.sections[-1]
                self.assertEqual(new.name, pw.NEW_SECTION_NAME)
                self.assertEqual(new.raw_pointer % after.file_alignment, 0)
                self.assertEqual(new.virtual_address % after.section_alignment, 0)
                self.assertEqual(len(out), new.raw_pointer + new.raw_size)
                size_of_image = after.u32(after.opt + 56)
                self.assertEqual(size_of_image % after.section_alignment, 0)
                self.assertGreaterEqual(size_of_image, new.virtual_address + new.virtual_size)
                rva, size = after.directory(pw.DIR_IMPORT)
                self.assertEqual(rva, new.virtual_address)
                self.assertEqual(size, 20 * (len(before.import_descriptors()) + 2))

    def test_relocations_still_cover_redirected_literals(self):
        original, out = self.patched("libgstwaveoutsink.dll")
        after = pw.PEImage(out)
        relocated = after.relocated_rvas()
        for redirect in pw.find_redirects(pw.PEImage(original), pw.DEFAULT_FUNCTIONS):
            for literal in redirect.thunk_literal_offsets:
                self.assertIn(after.offset_to_rva(literal), relocated)

    def test_volume_functions_are_optional(self):
        original = (AUTOKIT / "libgstwaveoutsink.dll").read_bytes()
        functions = pw.DEFAULT_FUNCTIONS + ("waveOutGetVolume", "waveOutSetVolume")
        out = pw.PEImage(pw.patch(original, HOOK.read_bytes(), functions))
        hook = imports(out)[pw.HOOK_DLL_NAME]
        self.assertEqual(len(hook), 4)

    def test_patching_twice_is_refused(self):
        _, out = self.patched("AutoKit.exe")
        with self.assertRaisesRegex(pw.PatchError, "already imports"):
            pw.patch(out, HOOK.read_bytes())

    def test_iidking_patched_reference_is_refused(self):
        with self.assertRaisesRegex(pw.PatchError, "already imports"):
            pw.patch(QUARTZ.read_bytes(), HOOK.read_bytes())

    def test_hook_without_custom_exports_is_refused(self):
        not_a_hook = (AUTOKIT / "libRRAudio.dll").read_bytes()
        with self.assertRaisesRegex(pw.PatchError, "does not export"):
            pw.patch((AUTOKIT / "AutoKit.exe").read_bytes(), not_a_hook)

    def test_module_without_waveout_is_refused(self):
        with self.assertRaisesRegex(pw.PatchError, "waveOutOpen"):
            pw.patch((AUTOKIT / "Thread2.dll").read_bytes(), HOOK.read_bytes())

    def test_input_bytes_are_not_modified(self):
        original = (AUTOKIT / "AutoKit.exe").read_bytes()
        copy = bytes(original)
        pw.patch(original, HOOK.read_bytes())
        self.assertEqual(original, copy)

    def test_short_data_directory_table_is_refused(self):
        data = bytearray((AUTOKIT / "AutoKit.exe").read_bytes())
        image = pw.PEImage(data)
        struct.pack_into("<I", data, image.opt + 92, 7)
        with self.assertRaisesRegex(pw.PatchError, "16 standard data directories"):
            pw.patch(bytes(data), HOOK.read_bytes())

    def test_duplicate_waveout_import_is_refused(self):
        data = bytearray((AUTOKIT / "AutoKit.exe").read_bytes())
        image = pw.PEImage(data)
        _, _, lookup, iat = [d for d in image.import_descriptors()
                             if d[1].upper() == "COREDLL.DLL"][0]
        close_slot = [slot for slot, value in image.thunks(lookup, iat)
                      if value == 0x80000000 | pw.WAVEOUT_ORDINALS["waveOutClose"]][0]
        struct.pack_into("<I", data, image.rva_to_offset(lookup + close_slot - iat),
                         0x80000000 | pw.WAVEOUT_ORDINALS["waveOutOpen"])
        with self.assertRaisesRegex(pw.PatchError, "imported more than once"):
            pw.patch(bytes(data), HOOK.read_bytes())

    def test_new_section_clears_raw_extent_of_last_section(self):
        data = bytearray((AUTOKIT / "libgstwaveoutsink.dll").read_bytes())
        last = pw.PEImage(data).sections[-1]
        struct.pack_into("<I", data, last.header_offset + 8, 0)  # VirtualSize = 0
        new = pw.PEImage(pw.patch(bytes(data), HOOK.read_bytes())).sections[-1]
        self.assertGreaterEqual(new.virtual_address, last.virtual_address + last.raw_size)


@unittest.skipUnless(HOOK.exists(), "syncextpack fixtures not present")
class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.module = self.tmp / "AutoKit.exe"
        shutil.copy2(AUTOKIT / "AutoKit.exe", self.module)

    def test_hard_linked_output_is_refused_and_input_survives(self):
        link = self.tmp / "link.exe"
        os.link(self.module, link)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            pw.main([str(self.module), str(link), "--hook", str(HOOK)])
        self.assertEqual(self.module.read_bytes(), (AUTOKIT / "AutoKit.exe").read_bytes())

    def test_writes_patched_copy(self):
        out = self.tmp / "out.exe"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pw.main([str(self.module), str(out), "--hook", str(HOOK)]), 0)
        self.assertEqual(pw.PEImage(out.read_bytes()).import_descriptors()[-1][1],
                         pw.HOOK_DLL_NAME)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["AutoKit.exe", "out.exe"])


@unittest.skipUnless(QUARTZ.exists(), "syncextpack fixtures not present")
class ReferencePatchLayout(unittest.TestCase):
    """The IIDKing-patched quartz.dll that plays sound on SYNC 2 has the same shape."""

    def test_reference_hook_descriptor_is_last_and_thunk_redirected(self):
        image = pw.PEImage(QUARTZ.read_bytes())
        descriptors = image.import_descriptors()
        self.assertEqual(descriptors[-1][1], pw.HOOK_DLL_NAME)
        _, _, lookup, iat = descriptors[-1]
        for slot, _ in image.thunks(lookup, iat):
            needle = struct.pack("<I", image.image_base + slot)
            hit = image.data.find(needle)
            self.assertNotEqual(hit, -1)
            self.assertEqual(image.data[hit - 12:hit], pw.ARM_IMPORT_THUNK)


class Checksum(unittest.TestCase):
    def test_checksum_skips_its_own_field(self):
        data = bytearray(64)
        struct.pack_into("<I", data, 8, 0xFFFFFFFF)
        self.assertEqual(pw.pe_checksum(bytes(data), 8), 64)


if __name__ == "__main__":
    unittest.main()
