"""Tests for s2am.mortscript: the car's MortScript rules and the bare-keyword bug."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import mortscript  # noqa: E402
from s2am.job import Job, autokit_script, hello_script, inventory_script, logger_script  # noqa: E402

SERIAL = "XV31M13H"

# The tail of inventory job 20261029-190450-inv-8606, which stopped in the car with
# "'If' without 'EndIf'" on the If line: the bare EndIf after it was dropped.
CAR_FAILURE = "\r\n".join([
    'Copy("\\8inchSkins\\Ford\\Sync\\Apps\\Info\\SyncApps\\SyncApps.xml", out & "\\SyncApps.xml", TRUE)',
    'If (FileExists("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\screenconfig"))',
    '  Copy("\\SyncExtendedPack\\Apps\\Media\\AutoKit\\screenconfig", out & "\\autokit-screenconfig.txt", TRUE)',
    "EndIf",
]) + "\r\n"


class Harden(unittest.TestCase):
    def test_bare_keywords_get_brackets(self):
        for word in ("EndIf", "  EndForEach", "Exit", "Else", "EndWhile"):
            with self.subTest(word):
                self.assertEqual(mortscript.harden(word), word + "()")

    def test_other_lines_are_left_alone(self):
        for line in ('If (a = 1)', 'x = 1', 'WriteFile(f, "EndIf")', "# comment", "", "EndIf()"):
            with self.subTest(line):
                self.assertEqual(mortscript.harden(line), line)

    def test_hardened_car_failure_passes(self):
        mortscript.check("\r\n".join(mortscript.harden(l) for l in CAR_FAILURE.split("\r\n")))


class Check(unittest.TestCase):
    def test_flags_the_script_that_failed_in_the_car(self):
        with self.assertRaisesRegex(mortscript.ScriptError, "line 4: bare 'EndIf'"):
            mortscript.check(CAR_FAILURE)

    def test_unclosed_and_mismatched_blocks(self):
        with self.assertRaisesRegex(mortscript.ScriptError, "line 1: IF is never closed"):
            mortscript.check("If (a)\r\n  x = 1\r\n")
        with self.assertRaisesRegex(mortscript.ScriptError, "line 2: EndForEach with open IF"):
            mortscript.check("If (a)\r\nEndForEach()\r\n")
        with self.assertRaisesRegex(mortscript.ScriptError, "Else with nothing open"):
            mortscript.check("Else()\r\n")

    def test_comments_start_at_hash_semicolon_and_slashes_outside_strings(self):
        # Each If is closed only by text that a comment would hide.
        for closer in ("x = 1 # EndIf()", "x = 1 ; EndIf()", "x = 1 // EndIf()"):
            with self.subTest(closer), self.assertRaisesRegex(mortscript.ScriptError, "never closed"):
                mortscript.check(f"If (a)\r\n{closer}\r\n")
        mortscript.check('If (a = "#;//")\r\nEndIf()\r\n')
        mortscript.check("If (a = '#;\"')\r\nEndIf()\r\n")

    def test_backslash_continues_the_line(self):
        mortscript.check("If (a = 1 \\\r\n  or b = 2)\r\nEndIf()\r\n")
        with self.assertRaisesRegex(mortscript.ScriptError, "never closed"):
            mortscript.check('If (a)\r\nWriteFile(f, "x")\\\r\nEndIf()\r\n')

    def test_assignments_are_not_commands(self):
        mortscript.check("If = 1\r\nForEach = 2\r\n")


class JobScripts(unittest.TestCase):
    """Every script s2am builds goes through the check; spot-check the shapes here."""

    def scripts(self):
        yield inventory_script(Job(SERIAL, "inv"))
        yield autokit_script(Job(SERIAL, "akpatch"), "patched")
        yield hello_script(Job(SERIAL, "hello"))
        yield logger_script(Job(SERIAL, "log", params={"seconds": 60, "native": True}))
        yield logger_script(Job(SERIAL, "log", params={"seconds": 60}))

    def test_no_bare_keyword_lines(self):
        for text in self.scripts():
            mortscript.check(text)
            bare = [l for _, l in mortscript.logical_lines(text) if mortscript.WORD.fullmatch(l)]
            self.assertEqual(bare, [])

    def test_replay_guard_exit_is_hardened(self):
        self.assertIn("  Exit()\r\n", inventory_script(Job(SERIAL, "inv")))


if __name__ == "__main__":
    unittest.main()
