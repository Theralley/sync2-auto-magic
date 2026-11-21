import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from s2am import flashtune, mortscript, native  # noqa: E402
from s2am.job import Job, flash_script  # noqa: E402

SERIAL = "TEST0001"
SOURCE = (native.SOURCES / "s2amflash.c").read_text()


class Plan(unittest.TestCase):
    def test_limits_match_the_native_tool(self):
        rows = re.findall(r'\{"(\w+)", (\d+), (\d+)\}', SOURCE)
        self.assertEqual([(name, int(low), int(high)) for name, low, high in rows],
                         [(name, low, high) for name, (low, high, _, _) in flashtune.LIMITS.items()])

    def test_backup_path_matches_the_native_tool(self):
        self.assertIn('L"' + flashtune.BACKUP.replace("\\", "\\\\") + '"', SOURCE)

    def test_fords_values_are_inside_the_limits(self):
        for name, (low, high, ford, _) in flashtune.LIMITS.items():
            with self.subTest(name=name):
                self.assertTrue(low <= ford <= high)

    def test_argument(self):
        self.assertEqual(flashtune.argument({"values": {"FastThreadPrio256": 251, "ThreadPrio256": 252}}),
                         "set:ThreadPrio256=252,FastThreadPrio256=251")
        self.assertEqual(flashtune.argument({"undo": True}), "undo")

    def test_bad_requests_are_refused(self):
        for params in ({}, {"values": {}}, {"values": {"ThreadPrio256": 249}}, {"values": {"ThreadPrio256": 254}},
                       {"values": {"ThreadPrio256": True}}, {"values": {"ThreadPrio256": "252"}},
                       {"values": {"WatchdogThreadPriority256": 250}}, {"values": {"FlashFastTimerInterval": 65}},
                       {"undo": True, "values": {"ThreadPrio256": 252}}, {"undo": "yes"},
                       {"values": {"ThreadPrio256|x": 252}}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                flash_script(Job(SERIAL, "flash", params=params))

    def test_script(self):
        script = flash_script(Job(SERIAL, "flash", params={"values": {"ThreadPrio256": 252}}))
        mortscript.check(script)
        kill = script[script.index("If (started = 1)"):script.index('Kill("s2amflash.exe")')]
        self.assertIn('If (NOT FileExists(out & "\\flash-done.txt"))', kill)  # never another job's tool
        self.assertEqual(script.count("started = 1"), 2)  # set only where the tool is started
        order = [script.index(part) for part in ('If (FileExists(out & "\\flash-done.txt"))', "s2amflash.exe\", \"set:",
                                                 'Kill("s2amflash.exe")', "flash-killed.txt", "flash-backup.txt")]
        self.assertEqual(order, sorted(order))  # a replay keeps its result; a hang is ended and marked
        self.assertIn('\\s2amflash.exe", "set:ThreadPrio256=252|" & out)', script)
        self.assertIn("flash-done.txt", script)
        self.assertIn("flash-backup.txt", script)
        undo = flash_script(Job(SERIAL, "flash", params={"undo": True}))
        mortscript.check(undo)
        self.assertIn('"undo|" & out)', undo)


class Summary(unittest.TestCase):
    def setUp(self):
        self.report = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.report)

    def write(self, *lines):
        (self.report / "flash.txt").write_bytes("".join(line + "\r\n" for line in lines).encode())

    def text(self, params=None):
        return "\n".join(flashtune.summary(self.report, self.PARAMS if params is None else params))

    BEFORE = ["before|ThreadPrio256|250", "before|FastThreadPrio256|248",
              "before|FlashNormalTimerInterval|500", "before|FlashFastTimerInterval|66"]
    AFTER = ["after|ThreadPrio256|252", "after|FastThreadPrio256|251",
             "after|FlashNormalTimerInterval|500", "after|FlashFastTimerInterval|66"]
    BACK = [line.replace("before", "after") for line in BEFORE]
    PARAMS = {"values": {"ThreadPrio256": 252, "FastThreadPrio256": 251}}

    def test_no_result(self):
        self.assertIn("NOT known", self.text())

    def test_killed_is_not_known_whatever_the_report_says(self):
        self.write(*self.BEFORE, "backup|written", "flush|0", *self.AFTER, "done|ok")
        (self.report / "flash-killed.txt").write_text("x")
        self.assertIn("NOT known", self.text())
        self.assertNotIn("verified:", self.text().replace("NOT verified:", ""))

    def test_applied(self):
        self.write(*self.BEFORE, "backup|written", "flush|0", *self.AFTER, "done|ok")
        text = self.text()
        self.assertIn("before: ThreadPrio256 250, FastThreadPrio256 248", text)
        self.assertIn("now: ThreadPrio256 252, FastThreadPrio256 251", text)
        self.assertIn("verified: the values read back as asked", text)
        self.assertNotIn("NOT", text)
        self.assertIn("after SYNC restarts", text)

    def test_done_ok_needs_the_whole_chain(self):
        good = [*self.BEFORE, "backup|kept", "flush|0", *self.AFTER, "done|ok"]
        self.write(*good)
        self.assertIn("kept from an earlier run", self.text())
        wrong_value = [line.replace("FastThreadPrio256|251", "FastThreadPrio256|248") for line in good]
        other_value = [line.replace("after|FlashFastTimerInterval|66", "after|FlashFastTimerInterval|70") for line in good]
        for name, lines in (("no flush", [x for x in good if not x.startswith("flush")]),
                            ("flush failed", [x.replace("flush|0", "flush|5") for x in good]),
                            ("no backup", [x for x in good if not x.startswith("backup")]),
                            ("backup removed", [x.replace("backup|kept", "backup|removed") for x in good]),
                            ("no read-back", [x for x in good if not x.startswith("after")]),
                            ("partial read-back", [x for x in good if x != self.AFTER[3]]),
                            ("no before", [x for x in good if not x.startswith("before")]),
                            ("wrong value", wrong_value), ("another value moved", other_value)):
            with self.subTest(name=name):
                self.write(*lines)
                self.assertIn("NOT verified", self.text())
                self.assertNotIn("\nverified", "\n" + self.text())

    def test_failed_before_any_write(self):
        self.write(*self.BEFORE, "done|refused|the backup could not be written")
        self.assertIn("nothing changed: the backup could not be written", self.text())

    def test_failed_and_taken_back(self):
        self.write(*self.BEFORE, "backup|written", "flush|0", *self.BACK,
                   "done|failed|a value could not be written; the earlier values are back")
        self.assertIn("FAILED, nothing is changed", self.text())

    def test_failed_with_changed_values(self):
        self.write(*self.BEFORE, "backup|written", "flush|5", *self.AFTER,
                   "done|failed|the registry could not be saved to storage")
        text = self.text()
        self.assertIn("flash-tune --undo", text)
        self.assertIn("may differ from before", text)
        self.assertIn("now: ThreadPrio256 252", text)

    def test_failed_with_unsaved_old_values_is_not_called_unchanged(self):
        self.write(*self.BEFORE, "backup|written", "flush|5", *self.BACK, "done|failed|x")
        self.assertNotIn("nothing is changed", self.text())

    def test_failed_needs_evidence_to_be_called_unchanged(self):
        back = [*self.BEFORE, "backup|written", "flush|0", *self.BACK, "done|failed|x"]
        self.write(*back)
        self.assertIn("nothing is changed", self.text())
        for name, lines in (("no flush", [x for x in back if not x.startswith("flush")]),
                            ("no after", [x for x in back if not x.startswith("after")]),
                            ("no before", [x for x in back if not x.startswith("before")]),
                            ("bare failure", ["done|failed|a value could not be written"]),
                            ("only before", [*self.BEFORE, "done|failed|the registry could not be saved"])):
            with self.subTest(name=name):
                self.write(*lines)
                self.assertNotIn("nothing", self.text())
                self.assertIn("flash-tune --undo", self.text())

    def test_failed_without_read_back_is_not_known(self):
        self.write(*self.BEFORE, "backup|written", "flush|0", "done|failed|the values cannot be read back")
        self.assertIn("NOT known", self.text())

    def test_undo(self):
        restore = [line.replace("before", "restore") for line in self.BEFORE]
        good = [*[line.replace("after", "before") for line in self.AFTER], *restore, "flush|0", *self.BACK,
                "backup|removed", "done|ok"]
        self.write(*good)
        self.assertIn("verified: Ford's values are back", self.text({"undo": True}))
        for name, lines in (("no restore lines", [x for x in good if not x.startswith("restore")]),
                            ("backup not removed", [x for x in good if not x.startswith("backup")]),
                            ("no read-back", [x for x in good if not x.startswith("after")]),
                            ("differs", [x.replace("after|ThreadPrio256|250", "after|ThreadPrio256|252") for x in good]),
                            ("flush failed", [x.replace("flush|0", "flush|5") for x in good])):
            with self.subTest(name=name):
                self.write(*lines)
                self.assertIn("NOT verified", self.text({"undo": True}))

    def test_undo_without_backup_changed_nothing(self):
        self.write(*self.BEFORE, "done|refused|there is no backup, so nothing was changed by this tool")
        self.assertIn("nothing changed: there is no backup", self.text({"undo": True}))

    def test_absent_and_junk_lines(self):
        self.write("before|ThreadPrio256|absent", "before|Other|1", "before|ThreadPrio256", "junk", "done|ok")
        self.assertEqual(flashtune.parse(self.report)["before"], {"ThreadPrio256": None})


FOLDER = "\\USB Disk\\s2am\\reports\\job 1"
FORD = "250,248,500,66"
FORD_BACKUP = "ThreadPrio256=250\nFastThreadPrio256=248\nFlashNormalTimerInterval=500\nFlashFastTimerInterval=66\n"


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Native(unittest.TestCase):
    """All of s2amflash.c, run on the Mac against a stand-in registry and file system
    (tests/fakece), with failures put in at every step. The report it writes goes through
    flashtune.summary, so what the owner is told is checked against what really happened."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        fake = Path(__file__).resolve().parent / "fakece"
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(fake),
                        "-I", str(native.SOURCES), "-o", str(cls.work / "flash"), str(fake / "flash_main.c")],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_tool(self, registry, backup, mode, fail="", lock="", folder=FOLDER):
        out = subprocess.run([str(self.work / "flash"), registry, backup, f"{mode}|{folder}"], check=True,
                             capture_output=True, env={"FAIL": fail, "LOCK": lock}).stdout.decode("ascii")
        parts = re.match(r"REG (.*)\nBACKUP (.*)\nSTAGING (.*)\nDONE (.*)\nREPORT (.*)\nRET (\d+) lock (\d)\n\Z",
                         out, re.S)
        self.assertIsNotNone(parts, out)
        reg, backup_now, staging, done, report, ret, held = parts.groups()
        self.assertEqual(held, "0")  # the lock is always given back
        self.assertEqual(staging, "-")  # no staging file is ever left behind
        folder_path = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder_path)
        (folder_path / "flash.txt").write_bytes(report.encode()) if report != "-" else None
        try:
            params = {"undo": True} if mode == "undo" else {
                "values": {k: int(v) for k, v in (item.split("=") for item in mode[4:].split(","))}}
            told = "\n".join(flashtune.summary(folder_path, params))
        except ValueError:
            told = "invalid request"
        return {"reg": reg.replace(" ", ","), "backup": backup_now, "done": done, "report": report,
                "ret": int(ret), "told": told}

    def assert_verified(self, result):
        self.assertIn("\nverified", "\n" + result["told"])
        self.assertEqual((result["ret"], result["done"]), (0, "ok"))

    def assert_not_verified(self, result):
        self.assertNotIn("\nverified", "\n" + result["told"])
        self.assertEqual(result["ret"], 1)
        self.assertIn(result["done"], ("failed", "refused"))

    def test_set_then_set_again_then_undo(self):
        first = self.run_tool(FORD, "-", "set:ThreadPrio256=251,FastThreadPrio256=251")
        self.assert_verified(first)
        self.assertEqual((first["reg"], first["backup"]), ("251,251,500,66", FORD_BACKUP))
        second = self.run_tool(first["reg"], first["backup"], "set:ThreadPrio256=252,FlashFastTimerInterval=100")
        self.assert_verified(second)
        self.assertEqual((second["reg"], second["backup"]), ("252,251,500,100", FORD_BACKUP))  # Ford's stay
        undone = self.run_tool(second["reg"], second["backup"], "undo")
        self.assert_verified(undone)
        self.assertEqual((undone["reg"], undone["backup"]), (FORD, "-"))
        twice = self.run_tool(undone["reg"], undone["backup"], "undo")
        self.assert_not_verified(twice)
        self.assertEqual(twice["reg"], FORD)
        self.assertIn("nothing changed", twice["told"])

    def test_absent_values_are_backed_up_and_removed_again(self):
        done = self.run_tool("250,a,500,66", "-", "set:FastThreadPrio256=251")
        self.assert_verified(done)
        self.assertIn("FastThreadPrio256=absent\n", done["backup"])
        undone = self.run_tool(done["reg"], done["backup"], "undo")
        self.assert_verified(undone)
        self.assertEqual(undone["reg"], "250,a,500,66")

    def test_a_ten_digit_value_survives_the_backup(self):
        done = self.run_tool("250,248,4294967295,66", "-", "set:ThreadPrio256=251")
        self.assert_verified(done)
        self.assertEqual(self.run_tool(done["reg"], done["backup"], "undo")["reg"], "250,248,4294967295,66")

    def test_refused_before_anything_is_touched(self):
        for name, registry, backup, mode, fail, lock in (
                ("no key", "nokey", "-", "set:ThreadPrio256=251", "", ""),
                ("a text value", "250,s,500,66", "-", "set:ThreadPrio256=251", "", ""),
                ("unreadable value", FORD, "-", "set:ThreadPrio256=251", "query=2", ""),
                ("out of limits", FORD, "-", "set:ThreadPrio256=249", "", ""),
                ("unknown name", FORD, "-", "set:WatchdogThreadPriority256=250", "", ""),
                ("unknown mode", FORD, "-", "reset", "", ""),
                ("lock held", FORD, "-", "set:ThreadPrio256=251", "", "held"),
                ("backup cannot be made", FORD, "-", "set:ThreadPrio256=251", "create=1", ""),
                ("backup write cut short", FORD, "-", "set:ThreadPrio256=251", "write=1", ""),
                ("backup cannot take its name", FORD, "-", "set:ThreadPrio256=251", "move=1", ""),
                ("empty backup", FORD, "\n", "set:ThreadPrio256=251", "", ""),
                ("cut-off backup", FORD, FORD_BACKUP[:-1], "set:ThreadPrio256=251", "", ""),
                ("partial backup", FORD, "ThreadPrio256=250\n", "set:ThreadPrio256=251", "", ""),
                ("windows line ends", FORD, FORD_BACKUP.replace("\n", "\r\n"), "undo", "", ""),
                ("undo with a broken backup", "251,251,500,66", "ThreadPrio256=250\n", "undo", "", "")):
            with self.subTest(name=name):
                result = self.run_tool(registry, backup, mode, fail, lock)
                self.assert_not_verified(result)
                self.assertEqual(result["reg"], registry.replace("nokey", "a,a,a,a"))
                self.assertEqual(result["backup"], backup)  # a backup that cannot be read is never replaced
                self.assertEqual(result["done"], "refused")
                self.assertIn("nothing changed" if name != "unknown mode" else "invalid request", result["told"])

    def test_an_abandoned_lock_is_taken(self):
        self.assert_verified(self.run_tool(FORD, "-", "set:ThreadPrio256=251", lock="abandoned"))

    def test_a_failed_write_is_taken_back(self):
        result = self.run_tool(FORD, "-", "set:ThreadPrio256=251,FastThreadPrio256=251", fail="set=2")
        self.assert_not_verified(result)
        self.assertEqual((result["reg"], result["backup"]), (FORD, FORD_BACKUP))
        self.assertIn("FAILED, nothing is changed", result["told"])

    def test_a_failed_take_back_is_reported_as_changed(self):
        result = self.run_tool(FORD, "-", "set:ThreadPrio256=251,FastThreadPrio256=251", fail="set=2+")
        self.assert_not_verified(result)
        self.assertEqual((result["reg"], result["backup"]), ("251,248,500,66", FORD_BACKUP))  # the backup stays
        self.assertIn("are not all back", result["report"])
        self.assertEqual(result["done"], "failed")
        self.assertIn("may differ from before", result["told"])
        self.assertIn("flash-tune --undo", result["told"])
        undone = self.run_tool(result["reg"], result["backup"], "undo")
        self.assert_verified(undone)
        self.assertEqual(undone["reg"], FORD)

    def test_an_unsaved_registry_is_a_failure_and_keeps_the_backup(self):
        for mode, registry, backup in (("set:ThreadPrio256=251", FORD, "-"), ("undo", "251,251,500,66", FORD_BACKUP)):
            with self.subTest(mode=mode):
                result = self.run_tool(registry, backup, mode, fail="flush=1")
                self.assert_not_verified(result)
                self.assertEqual(result["backup"], FORD_BACKUP)
                self.assertNotIn("nothing is changed", result["told"])

    def test_a_failed_read_back_is_not_known(self):
        result = self.run_tool(FORD, "-", "set:ThreadPrio256=251", fail="query=5+")
        self.assert_not_verified(result)
        self.assertEqual(result["backup"], FORD_BACKUP)
        self.assertIn("NOT known", result["told"])

    def test_undo_that_fails_half_way_keeps_the_backup(self):
        for fail in ("set=2", "set=2+", "delfile=1"):
            with self.subTest(fail=fail):
                result = self.run_tool("252,251,600,100", FORD_BACKUP, "undo", fail=fail)
                self.assert_not_verified(result)
                self.assertEqual(result["backup"], FORD_BACKUP)
                again = self.run_tool(result["reg"], result["backup"], "undo")
                self.assert_verified(again)
                self.assertEqual((again["reg"], again["backup"]), (FORD, "-"))

    def test_a_report_that_loses_lines_never_says_more_than_happened(self):
        """Writes to flash.txt fail at every point, once or from there on, in runs that work, fail
        and fail to take the change back. Whatever is left of the report must not be read as
        "verified" or "nothing changed" unless that is what the registry shows."""
        for mode, registry, backup, wanted in (
                ("set:ThreadPrio256=251,FastThreadPrio256=251", FORD, "-", "251,251,500,66"),
                ("undo", "500,248,5000,66", "ThreadPrio256=250\nFastThreadPrio256=248\n"
                                            "FlashNormalTimerInterval=500\nFlashFastTimerInterval=66\n", FORD),
                ("undo", "250,248,500,66", "ThreadPrio256=250\nFastThreadPrio256=248\n"
                                           "FlashNormalTimerInterval=5000\nFlashFastTimerInterval=66\n",
                 "250,248,5000,66")):
            for fail in ("", "set=2", "set=2+", "flush=1", "delfile=1"):
                for kind in ("report", "short"):
                    for at in range(1, 30):
                        for rest in ("", "+"):
                            plan = ",".join(x for x in (fail, f"{kind}={at}{rest}") if x)
                            with self.subTest(mode=mode, registry=registry, fail=plan):
                                result = self.run_tool(registry, backup, mode, fail=plan)
                                if "\nverified" in "\n" + result["told"]:
                                    self.assertEqual(result["reg"], wanted)
                                    self.assertEqual(result["backup"], "-" if mode == "undo" else FORD_BACKUP)
                                if "nothing" in result["told"]:
                                    self.assertEqual(result["reg"], registry.replace(" ", ","))
                                if "done|" not in result["report"]:
                                    self.assertIn("NOT known", result["told"])

    def test_a_broken_report_line_ends_the_report(self):
        """The reviewed case: an undo puts 5000 back, the line saying so is cut to "...|500", and
        removing the backup then fails. The report must stop there, not go on to a done line."""
        backup = "ThreadPrio256=250\nFastThreadPrio256=248\nFlashNormalTimerInterval=5000\nFlashFastTimerInterval=66\n"
        for at in range(1, 30):
            with self.subTest(at=at):
                result = self.run_tool(FORD, backup, "undo", fail=f"delfile=1,short={at}")
                self.assertEqual(result["reg"], "250,248,5000,66")
                self.assertNotIn("nothing", result["told"])
                if "done|" in result["report"]:  # the cut came after the last line: the report is whole
                    self.assertIn("after|FlashNormalTimerInterval|5000\r\n", result["report"])
                else:
                    self.assertIn("NOT known", result["told"])

    def test_only_the_four_values_can_be_touched(self):
        header = (Path(__file__).resolve().parent / "fakece" / "windows.h").read_text()
        self.assertIn("a value outside the four was touched", header)  # the stand-in aborts on any other
        self.assertEqual(SOURCE.count("RegSetValueExW("), 1)
        self.assertEqual(SOURCE.count("RegDeleteValueW("), 1)
        for forbidden in ("RegCreateKey", "RegDeleteKey", "WatchdogThreadPriority256", "InternalWDInterval"):
            self.assertNotIn(forbidden, SOURCE)


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Helpers(unittest.TestCase):
    """The plain-C helpers of s2amflash.c (between "pure: begin" and "pure: end"), built for the Mac."""

    @classmethod
    def setUpClass(cls):
        pure = SOURCE[SOURCE.index("/* pure: begin"):SOURCE.index("/* pure: end */")]
        program = "\n".join([
            "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>", "#define NAMES 4", pure,
            "int main(int argc, char **argv) {",
            "    struct plan plan; char out[512]; int i, ok; (void)argc;",
            "    ok = read_plan(argv[2], argv[1][0] == 's' ? ',' : '\\n', argv[1][0] == 's', &plan);",
            "    if (!ok) { printf(\"refused\\n\"); return 0; }",
            "    if (argv[1][0] == 'b') { if (!complete(&plan)) { printf(\"incomplete\\n\"); return 0; }",
            "        backup_text(&plan, out, sizeof(out)); printf(\"%s\", out); return 0; }",
            "    for (i = 0; i < NAMES; i++) if (plan.wanted[i]) printf(\"%s=%lu \", settings[i].name, plan.value[i]);",
            "    printf(\"\\n\"); return 0;", "}"])
        cls.work = Path(tempfile.mkdtemp())
        (cls.work / "flash.c").write_text(program)
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-o", str(cls.work / "flash"), str(cls.work / "flash.c")],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_helper(self, mode, text):
        return subprocess.run([str(self.work / "flash"), mode, text], check=True, capture_output=True,
                              text=True).stdout

    def test_what_python_sends_is_accepted(self):
        sent = flashtune.argument({"values": {"ThreadPrio256": 252, "FlashFastTimerInterval": 100}})
        self.assertEqual(self.run_helper("set", sent[4:]).strip(), "ThreadPrio256=252 FlashFastTimerInterval=100")

    def test_every_limit_is_enforced(self):
        for name, (low, high, _, _) in flashtune.LIMITS.items():
            for value, good in ((low, True), (high, True), (low - 1, False), (high + 1, False)):
                with self.subTest(name=name, value=value):
                    self.assertEqual(self.run_helper("set", f"{name}={value}").strip() != "refused", good)

    def test_malformed_requests_are_refused(self):
        for text in ("", "ThreadPrio256", "ThreadPrio256=", "ThreadPrio256=25x", "ThreadPrio256=252,",
                     ",ThreadPrio256=252", "ThreadPrio256=252,ThreadPrio256=251", "threadprio256=252",
                     "WatchdogThreadPriority256=250", "ThreadPrio256=absent", "ThreadPrio256=2520000000000",
                     "ThreadPrio256=252 ", "ThreadPrio256=-1", "ThreadPrio256=252;FastThreadPrio256=251"):
            with self.subTest(text=text):
                self.assertEqual(self.run_helper("set", text).strip(), "refused")

    def test_backup_round_trip(self):
        text = "ThreadPrio256=250\nFastThreadPrio256=absent\nFlashNormalTimerInterval=7\nFlashFastTimerInterval=66"
        self.assertEqual(self.run_helper("backup", text), text + "\n")

    def test_partial_backup_is_not_complete(self):
        self.assertEqual(self.run_helper("backup", "ThreadPrio256=250").strip(), "incomplete")
        self.assertEqual(self.run_helper("backup", "ThreadPrio256=250\n\nFastThreadPrio256=1").strip(), "refused")


if __name__ == "__main__":
    unittest.main()
