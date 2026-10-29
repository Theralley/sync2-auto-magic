"""Tests for tools/make_pack.py staging; the container build is exercised by hand."""
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import make_pack as mp  # noqa: E402
import patch_waveout as pw  # noqa: E402

UPSTREAM = ROOT.parent / "syncextpack"


def bucket(moment):
    return int(moment.timestamp() / (60 * 60 * 24 * 30) - 0.48)


@unittest.skipUnless((UPSTREAM / mp.AUTOKIT_DIR).exists(), "syncextpack fixtures not present")
class Stage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        # A small upstream with only what staging touches.
        self.upstream = self.tmp / "upstream"
        autokit = self.upstream / mp.AUTOKIT_DIR
        autokit.mkdir(parents=True)
        for name in mp.PATCH_TARGETS:
            shutil.copy2(UPSTREAM / mp.AUTOKIT_DIR / name, autokit / name)
        (self.upstream / mp.HOOK_SOURCE).parent.mkdir(parents=True)
        shutil.copy2(UPSTREAM / mp.HOOK_SOURCE, self.upstream / mp.HOOK_SOURCE)
        (self.upstream / "FlashTools").mkdir()
        (self.upstream / "FlashTools" / "swfmill").symlink_to("/opt/homebrew/bin/swfmill")
        (self.upstream / "crypto_pack").write_bytes(b"\x7fELF")
        (self.upstream / "crypto_pack_docker.sh").write_text("#!/bin/sh\n")
        (self.upstream / ".git").mkdir()
        (self.upstream / "Apps").mkdir()
        (self.upstream / "Apps" / "AutoKit-WINCE.rar").write_bytes(b"rar")
        self.before = {p: p.read_bytes() for p in self.upstream.rglob("*") if p.is_file()}
        self.staging = self.tmp / "stage"

    def test_stage_patches_copy_and_keeps_originals(self):
        changes = mp.stage(self.upstream, self.staging)
        autokit = self.staging / mp.AUTOKIT_DIR
        for name in mp.PATCH_TARGETS:
            original = (self.upstream / mp.AUTOKIT_DIR / name).read_bytes()
            self.assertEqual((autokit / (name + ".orig")).read_bytes(), original)
            self.assertEqual((autokit / (name + ".patched")).read_bytes(),
                             (autokit / name).read_bytes())
            imports = [d[1] for d in pw.PEImage((autokit / name).read_bytes()).import_descriptors()]
            self.assertEqual(imports[-1], pw.HOOK_DLL_NAME)
        self.assertTrue((autokit / pw.HOOK_DLL_NAME).is_file())
        self.assertEqual([c["file"] for c in changes],
                         list(mp.PATCH_TARGETS) + [pw.HOOK_DLL_NAME])

    def test_stage_never_touches_upstream(self):
        mp.stage(self.upstream, self.staging)
        after = {p: p.read_bytes() for p in self.upstream.rglob("*") if p.is_file()}
        self.assertEqual(after, self.before)

    def test_stage_prepares_container_tools(self):
        mp.stage(self.upstream, self.staging)
        self.assertFalse((self.staging / "crypto_pack_docker.sh").exists())
        self.assertEqual(str((self.staging / "FlashTools" / "swfmill").readlink()),
                         "/usr/bin/swfmill")
        self.assertFalse((self.staging / ".git").exists())
        self.assertFalse((self.staging / "Apps" / "AutoKit-WINCE.rar").exists())

    def test_restaging_starts_clean(self):
        mp.stage(self.upstream, self.staging)
        (self.staging / "leftover").write_text("x")
        mp.stage(self.upstream, self.staging)
        self.assertFalse((self.staging / "leftover").exists())

    def test_dry_run_builds_nothing(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = mp.main(["XV31M13H", "--upstream", str(self.upstream),
                            "--staging", str(self.staging), "--output", str(self.tmp / "out"),
                            "--dry-run"])
        self.assertEqual(code, 0)
        self.assertFalse((self.tmp / "out").exists())


class Arguments(unittest.TestCase):
    def test_rejects_bad_serials(self):
        for serial in ("XV31M13", "XV31M13HH", "XVO1M13H", "XV31M1;H"):
            with self.subTest(serial), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                mp.main([serial, "--dry-run"])

    def test_requires_autokit_and_plain_unit_names(self):
        for apps in (["Explorer"], ["AutoKit", "Reboot;rm"]):
            with self.subTest(apps), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                mp.main(["XV31M13H", *apps, "--dry-run"])


class ValidThru(unittest.TestCase):
    def test_is_last_second_of_current_key_bucket(self):
        now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
        end = mp.valid_thru(now)
        self.assertEqual(bucket(end), bucket(now))
        self.assertNotEqual(bucket(end + timedelta(seconds=1)), bucket(now))
        self.assertLess(end - now, timedelta(days=31))


if __name__ == "__main__":
    unittest.main()
