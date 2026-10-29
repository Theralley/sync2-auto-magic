"""Tests for s2am/pack.py: crypto_pack invocation and the unpack round-trip check (container mocked)."""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import pack  # noqa: E402
from s2am.job import Job  # noqa: E402

SAFE_NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.upstream = self.tmp / "upstream"
        self.upstream.mkdir()
        (self.upstream / "crypto_pack").write_bytes(b"\x7fELF")
        self.work = self.tmp / "work"
        (self.work / "payload" / "SyncExtendedPack" / "_s2am").mkdir(parents=True)
        (self.work / "payload" / "SyncExtendedPack" / "_s2am" / "a.txt").write_text("a")
        (self.work / "payload" / "windows").mkdir()
        (self.work / "payload" / "windows" / "b.dll").write_bytes(b"b")
        self.calls = []

    def fake_run(self, unpack):
        def run(workdir, *command, quiet=False):
            self.calls.append(command)
            if command[1] == "-p":
                (workdir / "install.bin").write_bytes(b"packed")
            elif command[1] == "-u":
                unpack(workdir / "payload", workdir / command[3])
        return run

    def build(self, unpack):
        with mock.patch.object(pack.container, "ensure_image"), \
                mock.patch.object(pack.container, "run", side_effect=self.fake_run(unpack)):
            return pack.build(Job("XV31M13H", "inv"), self.work, self.upstream, now=SAFE_NOW)

    def test_source_folder_has_the_trailing_slash_upstream_uses(self):
        self.assertTrue(pack.SOURCE.endswith("/"))
        self.build(lambda src, dst: shutil.copytree(src, dst))
        self.assertEqual(self.calls[0][2], "payload/")

    def test_matching_unpack_passes_and_cleans_up(self):
        out = self.build(lambda src, dst: shutil.copytree(src, dst))
        self.assertEqual(out, self.work / "install.bin")
        self.assertFalse((self.work / pack.CHECK_DIR).exists())
        self.assertFalse((self.work / "crypto_pack").exists())

    def test_empty_unpack_fails(self):  # what the slash-less invocation produced
        with self.assertRaisesRegex(pack.PackError, "does not unpack"):
            self.build(lambda src, dst: dst.mkdir())

    def test_changed_or_extra_file_fails(self):
        def corrupt(src, dst):
            shutil.copytree(src, dst)
            (dst / "windows" / "b.dll").write_bytes(b"x")

        def extra(src, dst):
            shutil.copytree(src, dst)
            (dst / "stray.txt").write_text("?")

        for unpack in (corrupt, extra):
            with self.subTest(unpack.__name__), self.assertRaises(pack.PackError):
                self.build(unpack)
        self.assertFalse((self.work / pack.CHECK_DIR).exists())


if __name__ == "__main__":
    unittest.main()
