"""Tests for tools/make_pack.py staging; the container build is exercised by hand."""
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from unittest import mock
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
                         list(mp.PATCH_TARGETS) + [pw.HOOK_DLL_NAME, "lang"])
        self.assertEqual((autokit / "lang").read_bytes(), b"\x09\x04\x00\x00")  # English

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


class VerifyPacks(unittest.TestCase):
    """make_pack unpacks both packs with crypto_pack (mocked here) and checks the contents."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.result = self.tmp / "SyncExtPack" / "XV31M13H" / "SyncExtPack"
        self.result.mkdir(parents=True)
        import hashlib
        self.changes = [{"file": "AutoKit.exe", "original_sha256": "a" * 64, "patched_sha256": "b" * 64},
                        {"file": "WaveOutHooks.dll", "sha256": hashlib.sha256(b"h").hexdigest()},
                        {"file": "lang", "sha256": hashlib.sha256(b"\x09\x04\x00\x00").hexdigest()}]

    def fake_unpack(self, good):
        def run(staging, *command, quiet=False):
            target = staging / command[3]
            if command[2].endswith("update.bin"):
                (target / "windows").mkdir(parents=True)
                (target / "windows" / "UpdateService.dll").write_bytes(b"u")
                return
            files = {"windows/AutoKitPlugin.dll": b"p", "windows/ExplorerPlugin.dll": b"p",
                     "windows/RebootPlugin.dll": b"p", "SyncExtendedPack/Apps/Tools/explorer.exe": b"e",
                     "SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe": b"r",
                     "SyncExtendedPack/Apps/Media/AutoKit/WaveOutHooks.dll": b"h"}
            for path, data in files.items():
                (target / path).parent.mkdir(parents=True, exist_ok=True)
                (target / path).write_bytes(data)
            autokit = target / "SyncExtendedPack/Apps/Media/AutoKit"
            (autokit / "AutoKit.exe").write_bytes(b"patched")
            (autokit / "lang").write_bytes(b"\x09\x04\x00\x00" if good else b"\x04\x08\x00\x00")
            (autokit / "AutoKit.exe.patched").write_bytes(b"patched")
            (autokit / "AutoKit.exe.orig").write_bytes(b"orig" if good else b"wrong")
            menu = target / mp.MENU_PATH
            menu.parent.mkdir(parents=True)
            menu.write_bytes(mp.apps_menu.render_menu([("AutoKit", "AutoKitPlugin", ""),
                                                       ("Total Commander", "ExplorerPlugin", ""),
                                                       ("Reboot", "RebootPlugin", "")]))
        return run

    def check(self, good):
        import hashlib
        self.changes[0]["original_sha256"] = hashlib.sha256(b"orig").hexdigest()
        self.changes[0]["patched_sha256"] = hashlib.sha256(b"patched").hexdigest()
        with mock.patch.object(mp.container, "run", side_effect=self.fake_unpack(good)):
            mp.verify_packs(self.tmp, self.result, "XV31M13H", mp.DEFAULT_APPS, self.changes)

    def test_expected_contents_pass_and_folders_are_cleaned(self):
        self.check(good=True)
        self.assertFalse((self.tmp / "verify_apps").exists())

    def test_wrong_original_module_fails(self):
        with self.assertRaisesRegex(mp.BuildError, "AutoKit.exe.orig"):
            self.check(good=False)
