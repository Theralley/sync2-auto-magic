"""Tests for the runner guard: the native program's shape and the on/off job."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import apps, cli, mortscript, native, stick  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.state import Store  # noqa: E402
from s2am.job import (BOOST_LEVELS, BOOST_STUCK_OFF, BOOST_STUCK_ON, BOOST_STUCK_WRITE, CALM_STUCK_OFF,  # noqa: E402
                      CALM_STUCK_ON, GUARD_BOOST, GUARD_CALM, GUARD_MIC, MIC_STUCK_ON,
                      MENU_XML, TOOLS_CE, Job, guard_script, load_folder)

UPSTREAM = ROOT.parent / "syncextpack"
HAVE_UPSTREAM = (UPSTREAM / "FullPack").is_dir()
SERIAL = "XV31M13H"
SOURCE = (native.SOURCES / "s2amrun.c").read_text()
RUNNER = UPSTREAM / "FullPack/SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe"
STOCK = RUNNER.read_bytes() if RUNNER.exists() else b"stock runner".ljust(1024, b"\0")
GUARD = b"MZ s2amrun stand-in"
PARAMS = {"stock_size": len(STOCK)}
COMMANDS = ["/SyncExtendedPack/Apps/Media/AutoKit/AutoKit.exe",  # as AutoKitPlugin.dll writes it
            "\\SyncExtendedPack\\Apps\\Tools\\explorer.exe",
            '"/Storage Card/My Apps/App.exe" -x', "  App.exe arg"]


def function(name):
    """One C function of s2amrun.c, from its first line to its closing brace."""
    start = re.search(rf"^\w[\w ]*?\**\b{name}\(", SOURCE, re.M).start()
    return SOURCE[start:SOURCE.index("\n}\n", start) + 3]


def build(work: Path, parts: list[str]) -> Path:
    """Compile pieces of s2amrun.c with the Mac's compiler, as plain C; returns the program."""
    (work / "part.c").write_text("\n".join(["#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>",
                                            "typedef int BOOL;", "#define TRUE 1", "#define FALSE 0",
                                            *parts]))
    subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-o", str(work / "part"), str(work / "part.c")],
                   check=True, capture_output=True)
    return work / "part"


class Source(unittest.TestCase):
    """The guard must repeat the stock runner's own steps; these come from its disassembly."""

    def test_gives_the_screen_back_like_the_stock_runner(self):
        show = function("show_sync")
        order = [show.index(s) for s in ('L"SYNC_DESKTOP_SHOW_UI"', "ShowWindow(desktop, SW_SHOW)",
                                         "SetForegroundWindow", 'L"show"', 'L"HandleShow"')]
        self.assertEqual(order, sorted(order))
        self.assertIn('FindWindowW(L"DESKTOP", NULL)', SOURCE)

    def test_starts_the_original_and_never_takes_its_mutex(self):
        self.assertIn('L"SyncAppsRunner.orig.exe"', SOURCE)
        self.assertNotIn("SyncAppsRunnerMutex", SOURCE)  # the original must still see itself as first

    def test_never_closes_an_app_that_has_not_shown_a_window(self):
        for counter in ("hidden", "unseen"):
            rule = re.search(rf"rules->{counter} = \((.*?)\) \?", SOURCE).group(1)
            self.assertIn("rules->shown && app && !vis", rule)

    def test_the_stuck_rule_acts_only_when_nothing_usable_is_on_the_screen(self):
        # no visible window but SYNC's shell background, as before the hidden rule
        self.assertIn("others == 0", re.search(r"rules->hidden = \((.*?)\) \?", SOURCE).group(1))
        self.assertIn("!usable", re.search(r"gone = \((.*)\) \?", SOURCE).group(1))
        self.assertIn("BOOL usable = !empty || ", function("restore_step"))
        self.assertIn("empty = !vis && scan.others == 0;", SOURCE)

    def test_the_hidden_rule_counts_only_the_apps_own_window(self):
        # issue 2: the installer's window (or SYNC) on the screen must not keep a hidden app alive
        self.assertNotIn("others", re.search(r"rules->unseen = \((.*?)\) \?", SOURCE).group(1))
        self.assertIn('note("hidden", "no window of the app on the screen for 5 s, closing pid ", watched.pid);',
                      SOURCE)
        self.assertIn("#define HIDDEN_TICKS 5 ", SOURCE)  # the log line says 5 s

    def test_both_closes_go_through_the_same_steps(self):
        cases = SOURCE[SOURCE.index("switch (judge("):]
        cases = cases[:cases.index("default:")]
        self.assertLess(cases.index("case CLOSE_STUCK:"), cases.index("close_app(watched.process, watched.pid, FALSE)"))
        self.assertLess(cases.index("case CLOSE_HIDDEN:"), cases.index("close_app(watched.process, watched.pid, TRUE)"))
        self.assertEqual(cases.count("judge_after_close(&rules, outcome);"), 2)
        # every look's outcome, a close or none, goes to the restore step (run in Restore)
        loop = SOURCE[SOURCE.index("for (;;) {"):]
        self.assertLess(loop.index("outcome = NOT_BACK;"), loop.index("switch (judge("))
        self.assertLess(loop.index("default:"),
                        loop.index("act = restore_step(&restore, app, vis, empty, outcome, runner_done);"))
        self.assertNotIn("PostMessageW", function("scan_window"))  # a look only collects (review C)

    def test_the_background_is_the_one_measured_in_the_car(self):
        # s2amwatch, 2026-10-30: after AutoKit's Exit only mishell.exe's window stayed visible
        self.assertIn('#define BACKGROUND_CLASS L"DesktopExplorerWindow"', SOURCE)

    def test_a_new_app_instance_starts_with_a_clean_state(self):
        # a quick relaunch after a terminate must not inherit "killed" (Codex review); follow_app()
        # itself is run in Bookkeeping
        adopt = SOURCE[SOURCE.index("if (follow_app(&watched, name)) {"):]
        adopt = adopt[:adopt.index("app = watched.pid != 0;")]
        for reset in ("judge_again(&rules);", "restore_again(&restore);"):
            self.assertIn(reset, adopt)
        self.assertEqual(SOURCE.count("follow_app(&watched, name)"), 1)
        # the boost's entries go only where the app's handle said it ended (review A)
        self.assertEqual(SOURCE.count("boost_forget();"), 1)
        follow = function("follow_app")
        self.assertLess(follow.index("!= WAIT_OBJECT_0"), follow.index("boost_forget();"))
        self.assertLess(follow.index("boost_forget();"), follow.index("find_process("))
        again = function("judge_again")
        fields = re.findall(r"(?:BOOL|int) (\w+);", re.search(r"typedef struct \{[^}]*\} Rules;", SOURCE).group())
        self.assertEqual(fields, ["shown", "hidden", "unseen"])
        for field in fields:
            self.assertIn(f"rules->{field} =", again)  # every counter of both rules

    def test_keeps_watching_while_the_app_lives(self):
        # run in Restore; here only that the loop leaves on the step's word and nowhere else
        loop = SOURCE[SOURCE.index("for (;;) {"):SOURCE.index("    if (watched.process)\n        CloseHandle")]
        self.assertEqual(loop.count("break;  /*"), 1)
        self.assertIn("if (act & STOP)\n            break;", loop)
        self.assertIn("if (act & SHOW_SYNC) {", loop)
        self.assertIn("show_sync();", loop[loop.index("if (act & SHOW_SYNC) {"):loop.index("if (act & STOP)")])

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
    def test_name_and_screen_rules_compiled_and_run(self):
        """app_name and usable() from s2amrun.c itself, built for the Mac and run."""
        background = re.search(r"#define BACKGROUND_CLASS .*", SOURCE).group()
        program = "\n".join([
            "#include <stdio.h>", "#include <wchar.h>", "typedef wchar_t WCHAR;", "typedef int BOOL;",
            background, function("usable"), function("app_name"),
            "int main(void) {", "    WCHAR name[260];",
            *[f'    app_name(L{json.dumps(command)}, name, 260); printf("%ls\\n", name);'
              for command in COMMANDS],
            '    printf("%d %d %d %d\\n", usable(L"DesktopExplorerWindow", 1), usable(L"DESKTOP", 1),',
            '           usable(L"VideoRenderer", 1), usable(L"DESKTOP", 0));',
            "    return 0;", "}"])
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work)
        (work / "rules.c").write_text(program)
        subprocess.run(["cc", "-Wall", "-Werror", "-o", str(work / "rules"), str(work / "rules.c")],
                       check=True, capture_output=True)
        out = subprocess.run([str(work / "rules")], check=True, capture_output=True, text=True).stdout
        self.assertEqual(out.splitlines(), ["AutoKit.exe", "explorer.exe", "App.exe", "App.exe",
                                            "0 1 1 0"])

    def test_registered_and_cached(self):
        self.assertEqual(native.PROGRAMS["s2amrun.exe"], "s2amrun.c")

    @unittest.skipUnless((ROOT / "build" / "native" / "s2amrun.exe").exists(), "run `s2am native build`")
    def test_built_binary_needs_only_coredll(self):
        native.check((ROOT / "build" / "native" / "s2amrun.exe").read_bytes(), "s2amrun.exe")


def define(name):
    return re.search(rf"#define {name} .*", SOURCE).group()


def declared(pattern):
    return re.search(pattern, SOURCE).group()


# Windows types and names as the host compiler needs them for pieces of s2amrun.c.
WINDOWS = ["#include <stdint.h>", "#include <wchar.h>", "typedef uint32_t DWORD;", "typedef int32_t LONG;",
           "typedef void *HANDLE;", "typedef wchar_t WCHAR;", "#define WINAPI",
           "#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)", "#define WAIT_OBJECT_0 0",
           "#define WAIT_TIMEOUT 258", "#define WAIT_FAILED 0xFFFFFFFF", "#define THREAD_SET_INFORMATION 0x20"]
# ... and for the window scan.
SCREEN = ["typedef void *HWND;", "typedef intptr_t LPARAM;", "typedef uintptr_t WPARAM;", "typedef unsigned UINT;",
          "#define CALLBACK", "typedef BOOL (*WNDENUMPROC)(HWND, LPARAM);", "#define WM_CLOSE 0x0010"]

# How a close went, by name, both ways (after the enum from s2amrun.c).
OUTCOMES = r"""
const char *outcome_name(int outcome)
{
    return outcome == APP_BACK ? "back" : outcome == OTHERS_BACK ? "others" : outcome == APP_ENDED ? "ended"
         : outcome == APP_TERMINATED ? "terminated" : outcome == CLOSE_FAILED ? "failed" : "not back";
}

int outcome_of(const char *name)
{
    int outcome;
    for (outcome = NOT_BACK; outcome <= CLOSE_FAILED; outcome++)
        if (!strcmp(outcome_name(outcome), name))
            return outcome;
    abort();
}
"""


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Rules(unittest.TestCase):
    """judge() and judge_after_close() from s2amrun.c, built for the Mac, replay what the guard
    saw in the car (guard.log). Each close goes as the test says: back (a window of the app shows),
    others (only something else is on the screen again), ended, terminated or failed."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        cls.program = build(cls.work, [
            define("STUCK_TICKS"), define("HIDDEN_TICKS"),
            declared(r"typedef struct \{[^}]*\} Rules;"),
            declared(r"enum \{ KEEP, CLOSE_STUCK, CLOSE_HIDDEN \};"),
            declared(r"enum \{ NOT_BACK,[^}]*\};"), OUTCOMES,
            function("judge"), function("judge_again"), function("judge_after_close"),
            "int main(int argc, char **argv) {",
            "    Rules rules;",
            "    int app, vis, others, verdict, closes = 1;",
            "    judge_again(&rules);",
            '    while (scanf("%d %d %d", &app, &vis, &others) == 3) {',
            "        verdict = judge(&rules, app, vis, others);",
            '        printf("%s\\n", verdict == KEEP ? "keep" : verdict == CLOSE_STUCK ? "stuck" : "hidden");',
            "        if (verdict != KEEP)  /* as WinMain does after each close */",
            "            judge_after_close(&rules, closes < argc ? outcome_of(argv[closes++]) : APP_ENDED);",
            "    }",
            "    return 0;",
            "}"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def replay(self, *runs, closes=()):
        """Looks once a second: (app runs, a window of it shown, other usable windows), repeated."""
        looks = [look for look, times in runs for _ in range(times)]
        text = "".join(f"{app} {vis} {others}\n" for app, vis, others in looks)
        out = subprocess.run([str(self.program), *closes], input=text,
                             check=True, capture_output=True, text=True).stdout
        verdicts = out.split()
        self.assertEqual(len(verdicts), len(looks))
        return [(i, v) for i, v in enumerate(verdicts) if v != "keep"]

    def test_issue_2_the_installer_window_no_longer_keeps_a_hidden_autokit(self):
        # 2026-11-15 (akcfg-9ccd): 2 looks with nothing usable after Exit, then the installer's
        # window, then SYNC; the stuck rule never held and AutoKit kept running for minutes
        acts = self.replay(((1, 0, 0), 2), ((1, 1, 0), 300), ((1, 0, 0), 2), ((1, 0, 1), 200))
        self.assertEqual(acts, [(2 + 300 + 4, "hidden")])  # the 5th look without its window

    def test_a_normal_exit_is_still_the_stuck_rule_after_3_s(self):
        # the usual Exit in the same log: stuck 2 s after the hide, AutoKit gone 0.5 s later
        self.assertEqual(self.replay(((1, 0, 0), 2), ((1, 1, 0), 10), ((1, 0, 0), 5)),
                         [(2 + 10 + 2, "stuck")])

    def test_a_starting_app_is_never_closed(self):
        # Media.exe: no window of its own for 2-3 s, while something else is on the screen
        self.assertEqual(self.replay(((1, 0, 0), 1), ((1, 0, 1), 30)), [])
        self.assertEqual(self.replay(((1, 0, 0), 30)), [])

    def test_sync_shown_over_the_app_never_closes_it(self):
        # the second tap and the parking screen show SYNC over the app; its window stays visible
        self.assertEqual(self.replay(((1, 1, 0), 3), ((1, 1, 1), 600), ((1, 1, 0), 3)), [])

    def test_a_short_hide_starts_the_count_again(self):
        self.assertEqual(self.replay(((1, 1, 0), 3), ((1, 0, 1), 4), ((1, 1, 0), 1), ((1, 0, 1), 4),
                                     ((1, 1, 1), 1), ((1, 0, 0), 2), ((1, 1, 0), 1)), [])

    def test_an_ended_app_is_left_to_the_restore_rule(self):
        self.assertEqual(self.replay(((1, 1, 0), 3), ((0, 0, 0), 30), ((0, 0, 1), 30)), [])

    def test_a_terminated_app_that_lingers_is_not_closed_every_few_seconds(self):
        acts = self.replay(((1, 1, 0), 3), ((1, 0, 1), 60), closes=["terminated"])
        self.assertEqual(acts, [(3 + 4, "hidden")])

    def test_an_app_that_survives_the_close_hidden_is_closed_again(self):
        # review point 1: a close that found the app back must not disarm the five-look rule
        acts = self.replay(((1, 1, 0), 3), ((1, 0, 1), 60), closes=["back", "back", "terminated"])
        self.assertEqual(acts, [(7, "hidden"), (12, "hidden"), (17, "hidden")])

    def test_a_stuck_close_that_found_something_on_the_screen_leads_to_the_hidden_rule(self):
        # the stuck rule's close left it because a window came up; the app itself stayed hidden,
        # and its 3 looks without a window still count (review D): the 5th comes 2 looks later
        acts = self.replay(((1, 1, 0), 3), ((1, 0, 0), 3), ((1, 0, 1), 20), closes=["others", "ended"])
        self.assertEqual(acts, [(5, "stuck"), (7, "hidden")])

    def test_something_coming_up_now_and_then_never_puts_the_hidden_rule_off(self):
        # review D: 3 empty looks, a stuck close that something else stops, again and again; the
        # app never shows its window, so the hidden rule closes it on its 5th look without one
        cycle = (((1, 0, 0), 3), ((1, 0, 1), 1)) * 6
        acts = self.replay(((1, 1, 0), 3), *cycle, closes=["others", "terminated"])
        self.assertEqual(acts, [(5, "stuck"), (7, "hidden")])
        # had each close found the app's own window instead, the count would start again each
        # time: what the first version did for anything on the screen
        acts = self.replay(((1, 1, 0), 3), *cycle, closes=["back"] * 6)
        self.assertEqual(acts, [(5, "stuck"), (9, "stuck"), (13, "stuck"), (17, "stuck"), (21, "stuck"),
                                (25, "stuck")])

    def test_a_close_that_failed_is_tried_again_once_the_rule_holds_again(self):
        # review B: no handle, a failed wait or a refused terminate is not an end; the app stays
        # judged, and the rule that fired holds again after its 5 (or 3) looks, not on every look
        acts = self.replay(((1, 1, 0), 3), ((1, 0, 1), 20), closes=["failed", "failed", "terminated"])
        self.assertEqual(acts, [(7, "hidden"), (12, "hidden"), (17, "hidden")])
        acts = self.replay(((1, 1, 0), 3), ((1, 0, 0), 10), closes=["failed", "terminated"])
        self.assertEqual(acts, [(5, "stuck"), (8, "stuck")])


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Restore(unittest.TestCase):
    """restore_step() and restore_again() from s2amrun.c, built for the Mac: when the guard gives
    SYNC the screen itself, and when it stops watching. One look per line, after the rules."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        cls.program = build(cls.work, [
            define("STUCK_TICKS"),
            declared(r"enum \{ NOT_BACK,[^}]*\};"), OUTCOMES,
            declared(r"typedef struct \{[^}]*\} Restore;"),
            declared(r"enum \{ SHOW_SYNC[^}]*\};"),
            function("restore_again"), function("restore_step"),
            r"""
int main(void)
{
    Restore restore = {FALSE, FALSE, FALSE, 0};
    char close[16];
    int app, vis, empty, done, act;
    while (scanf("%15s", close) == 1) {
        if (!strcmp(close, "new")) {  /* another instance, as WinMain does */
            restore_again(&restore);
            continue;
        }
        if (scanf("%d %d %d %d", &app, &vis, &empty, &done) != 4)
            return 1;
        act = restore_step(&restore, app, vis, empty, strcmp(close, "none") ? outcome_of(close) : NOT_BACK, done);
        printf("%s killed %d restored %d gone %d\n",
               act == 0 ? "-" : act == SHOW_SYNC ? "show" : act == STOP ? "stop" : "show+stop",
               restore.killed, restore.restored, restore.gone);
        if (act & STOP)
            return 0;  /* WinMain leaves the loop */
    }
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def watch(self, *runs):
        """Looks: ((app runs, a window of it shows, nothing usable on the screen, the runner has
        ended), this look's close: an outcome or "none"), repeated; or "new" for another instance.
        Returns [(look, what it asked for)] and each look's (killed, restored, gone)."""
        lines = []
        for run in runs:
            if run == "new":
                lines.append("new\n")
                continue
            (app, vis, empty, done), close, times = run
            lines += [f"{close} {app} {vis} {empty} {done}\n"] * times
        out = subprocess.run([str(self.program)], input="".join(lines), check=True, capture_output=True,
                             text=True).stdout.splitlines()
        acts = [(i, line.split()[0]) for i, line in enumerate(out) if not line.startswith("-")]
        states = [tuple(map(int, line.split()[2::2])) for line in out]
        return acts, states

    SHOWN = ((1, 1, 0, 0), "none")  # the app in front
    HIDDEN = ((1, 0, 1, 0), "none")  # the app hidden, nothing usable on the screen
    COVERED = ((1, 0, 0, 0), "none")  # the app hidden, SYNC (or anything usable) on the screen
    FAILED = ((1, 0, 1, 0), "failed")  # the stuck close on such a look could not be done

    def test_two_freezes_of_the_same_app_both_get_the_screen_back(self):
        # review round 3: failed close, SYNC gets the screen, the app shows its window again,
        # then another freeze with a failed close; the second restore was blocked for good
        acts, states = self.watch((*self.SHOWN, 3), (*self.HIDDEN, 2), (*self.FAILED, 1), (*self.HIDDEN, 2),
                                  (*self.COVERED, 2), (*self.SHOWN, 3),
                                  (*self.HIDDEN, 2), (*self.FAILED, 1), (*self.HIDDEN, 3))
        self.assertEqual(acts, [(7, "show"), (17, "show")])  # 3 looks after each failed close
        self.assertEqual(states[8], (1, 0, 0))  # SYNC on the screen: re-armed, the failure stays
        self.assertEqual(states[10], (0, 0, 0))  # the app's window: the failure is over
        self.assertEqual(states[-1], (1, 1, 4))  # once per freeze: not again while it lasts

    def test_a_restore_that_did_not_take_is_not_repeated(self):
        # the screen stayed empty after show_sync: no second one every few seconds, whatever
        # the closes tried in the meantime came to, as long as none of them saw the app back
        acts, _ = self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 20))
        self.assertEqual(acts, [(5, "show")])
        acts, _ = self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 2),
                             (*self.FAILED, 1), (*self.HIDDEN, 4), (*self.FAILED, 1), (*self.HIDDEN, 4),
                             (self.HIDDEN[0], "terminated", 1), (*self.HIDDEN, 4))
        self.assertEqual(acts, [(5, "show")])

    def test_a_close_that_found_the_app_back_re_arms_the_restore(self):
        # review round 4: a show_sync without effect, then a close retry whose own look found the
        # app back, on a look that began empty; the window goes again before the next look, and
        # the next freeze must get its own restore
        for close in ("back", "others"):
            acts, states = self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 4),
                                      (self.HIDDEN[0], close, 1),
                                      (*self.HIDDEN, 1), (*self.FAILED, 1), (*self.HIDDEN, 3))
            self.assertEqual(acts, [(5, "show"), (12, "show")], close)
            self.assertEqual(states[8], (0, 0, 0), close)  # re-armed, nothing gone, nothing failed

    def test_a_window_of_the_app_ends_what_a_failed_close_left(self):
        _, states = self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (*self.SHOWN, 1), (*self.HIDDEN, 2))
        self.assertEqual(states[3], (1, 0, 1))
        self.assertEqual(states[4:], [(0, 0, 0)] * 3)  # an empty screen alone is left to the rules

    def test_closes_that_ended_or_found_the_app_back_leave_nothing_behind(self):
        for close in ("back", "others", "ended"):
            _, states = self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (self.HIDDEN[0], close, 1))
            self.assertEqual(states[-1][0], 0, close)
        _, states = self.watch((*self.SHOWN, 3), (self.HIDDEN[0], "terminated", 1))
        self.assertEqual(states[-1], (1, 0, 1))

    def test_another_instance_starts_with_nothing_left_over(self):
        acts, states = self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 2), "new",
                                  (*self.HIDDEN, 2))
        self.assertEqual(acts, [(5, "show")])
        self.assertEqual(states[-2:], [(0, 0, 0), (0, 0, 0)])

    def test_keeps_watching_while_the_app_lives(self):
        acts, _ = self.watch((*self.SHOWN, 3), ((1, 1, 0, 1), "none", 20), ((1, 0, 0, 1), "none", 20))
        self.assertEqual(acts, [])

    def test_the_exits(self):
        # never started: the runner ended and the app never ran
        self.assertEqual(self.watch(((0, 0, 1, 0), "none", 5), ((0, 0, 1, 1), "none", 1))[0], [(5, "stop")])
        # back to normal: the app ended and the runner gave SYNC the screen
        self.assertEqual(self.watch((*self.SHOWN, 3), ((0, 0, 0, 1), "none", 1))[0], [(3, "stop")])
        # repaired: the app and the runner ended, SYNC stayed hidden
        self.assertEqual(self.watch((*self.SHOWN, 3), ((0, 0, 1, 1), "none", 5))[0], [(5, "show+stop")])
        # the app ended first; the runner later, after the guard had given SYNC the screen
        self.assertEqual(self.watch((*self.SHOWN, 3), ((0, 0, 1, 0), "none", 4), ((0, 0, 1, 1), "none", 1))[0],
                         [(5, "show"), (7, "stop")])
        # the app would not end and SYNC got the screen; then it ended, and so did the runner
        self.assertEqual(self.watch((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 2),
                                    ((0, 0, 1, 1), "none", 1))[0], [(5, "show"), (6, "stop")])

    def test_always_stops_within_3_looks_once_the_app_and_the_runner_have_ended(self):
        # what "given up" used to guard: the restore comes first, so no other limit is needed
        befores = [(), ((*self.SHOWN, 3),), ((*self.SHOWN, 3), (*self.FAILED, 1)),
                   ((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 2)),
                   ((*self.SHOWN, 3), (*self.FAILED, 1), (*self.HIDDEN, 2), (*self.COVERED, 1)),
                   ((*self.SHOWN, 3), ((0, 0, 1, 0), "none", 2))]
        for before in befores:
            start = sum(run[2] for run in before)
            for empty in (0, 1):
                acts, _ = self.watch(*before, ((0, 0, empty, 1), "none", 10))
                stops = [i for i, act in acts if "stop" in act]
                self.assertTrue(stops, (before, empty))
                self.assertLess(stops[0] - start, 3 if empty else 1, (before, empty))


SENT = "close|sent WM_CLOSE to pid "
OWN_BACK = "recovered|the app shows a window again, leaving pid "
OTHERS_BACK = "recovered|something is on the screen again, leaving pid "


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Close(unittest.TestCase):
    """close_app(), came_back() and the window scan itself (scan_window, scan_screen, usable) from
    s2amrun.c, over a scripted screen and process: EnumWindows and the window calls, the waits and
    the terminate are fakes."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        cls.program = build(cls.work, [
            *WINDOWS, *SCREEN, define("CLOSE_WAIT_MS"), define("CLOSE_POLL_MS"), define("MAX_WINDOWS"),
            define("BACKGROUND_CLASS"),
            declared(r"typedef struct \{[^}]*\} WindowScan;"),
            declared(r"enum \{ NOT_BACK,[^}]*\};"), OUTCOMES,
            r"""
/* One look per EnumWindows, from the command line, one letter per window in the order the
   system lists them: A/a a window of the app (pid 42) shown/hidden, O/o another program's,
   B SYNC's shell background. Past the last look the last one stays. Window n of look l is
   the handle l*100+n+1. */
static char **looks;
static int nlooks, looked = -1, terminates;
static const char *waits;  /* per wait: t timeout, e ended, f failed; then timeouts */

static char kind(HWND window)
{
    intptr_t at = (intptr_t)window - 1;
    return looks[at / 100][at % 100];
}

static BOOL EnumWindows(WNDENUMPROC callback, LPARAM param)
{
    int n;
    if (looked < nlooks - 1)
        looked++;
    for (n = 0; looks[looked][n]; n++)
        if (!callback((HWND)(intptr_t)(looked * 100 + n + 1), param))
            break;
    return TRUE;
}

static BOOL IsWindowVisible(HWND window)
{
    return kind(window) == 'A' || kind(window) == 'O' || kind(window) == 'B';
}

static DWORD GetWindowThreadProcessId(HWND window, DWORD *pid)
{
    *pid = kind(window) == 'A' || kind(window) == 'a' ? 42 : 7;
    return 1;
}

static int GetClassNameW(HWND window, WCHAR *name, int size)
{
    (void)size;
    wcscpy(name, kind(window) == 'B' ? BACKGROUND_CLASS : L"Other");
    return (int)wcslen(name);
}

static BOOL PostMessageW(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    intptr_t at = (intptr_t)window - 1;
    (void)wparam; (void)lparam;
    printf("%s to %d.%d\n", message == WM_CLOSE ? "WM_CLOSE" : "?", (int)(at / 100), (int)(at % 100));
    return TRUE;
}

static DWORD WaitForSingleObject(HANDLE process, DWORD ms)
{
    char next = *waits ? *waits++ : 't';
    (void)process; (void)ms;
    return next == 'e' ? WAIT_OBJECT_0 : next == 'f' ? WAIT_FAILED : WAIT_TIMEOUT;
}

static BOOL TerminateProcess(HANDLE process, DWORD code)
{
    (void)process; (void)code;
    return terminates;
}

static void note(const char *event, const char *detail, unsigned long value)
{
    (void)value;
    printf("%s|%s\n", event, detail ? detail : "");
}
""",
            function("usable"), function("scan_window"), function("scan_screen"), function("came_back"),
            function("close_app"),
            r"""
int main(int argc, char **argv)
{
    /* own, the waits, a handle (1) or none (0), the terminate works (1) or not (0), the looks */
    int outcome;
    waits = argv[2];
    terminates = atoi(argv[4]);
    looks = argv + 5;
    nlooks = argc - 5;
    outcome = close_app(atoi(argv[3]) ? (HANDLE)1 : NULL, 42, atoi(argv[1]));
    printf("%s\n", outcome_name(outcome));
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def close(self, *looks, own=True, waits="", handle=True, terminates=True):
        return subprocess.run([str(self.program), str(int(own)), waits, str(int(handle)), str(int(terminates)),
                               *looks], check=True, capture_output=True, text=True).stdout.splitlines()

    def test_a_window_of_the_app_shown_in_the_closing_look_gets_no_wm_close(self):
        # review C: a hidden window listed before the shown one used to get WM_CLOSE on the spot
        self.assertEqual(self.close("aA"), [OWN_BACK, "back"])
        self.assertEqual(self.close("Aa"), [OWN_BACK, "back"])
        self.assertEqual(self.close("OaA", own=False), [OWN_BACK, "back"])

    def test_wm_close_goes_to_each_window_of_the_closing_look_and_nothing_else(self):
        # the hidden rule, whatever else is on the screen: SYNC, the installer, the background
        self.assertEqual(self.close("OaBa"), ["WM_CLOSE to 0.1", "WM_CLOSE to 0.3", SENT, "terminate|pid ",
                                              "terminated"])
        self.assertEqual(self.close("Oa", waits="te"), ["WM_CLOSE to 0.1", SENT, "closed|pid ", "ended"])

    def test_counts_as_back_only_when_its_own_window_shows(self):
        self.assertEqual(self.close("Oa", "Oa", "OA"), ["WM_CLOSE to 0.1", SENT, OWN_BACK, "back"])

    def test_the_stuck_close_stops_for_anything_usable_but_the_background(self):
        self.assertEqual(self.close("OBa", own=False), [OTHERS_BACK, "others"])  # nothing sent
        self.assertEqual(self.close("Ba", "Ba", "BaO", own=False), ["WM_CLOSE to 0.1", SENT, OTHERS_BACK, "others"])
        self.assertEqual(self.close("oBa", own=False), ["WM_CLOSE to 0.2", SENT, "terminate|pid ", "terminated"])

    def test_a_close_that_cannot_be_done_is_never_an_end(self):
        # review B: each of these used to read as "ended", which disarmed the rules
        self.assertEqual(self.close("a", handle=False), ["close|not possible, no handle for pid ", "failed"])
        self.assertEqual(self.close("a", waits="f"), ["WM_CLOSE to 0.0", SENT,
                                                      "close|failed, could not wait for pid ", "failed"])
        self.assertEqual(self.close("a", waits="tf"), ["WM_CLOSE to 0.0", SENT,
                                                       "close|failed, could not wait for pid ", "failed"])
        self.assertEqual(self.close("a", terminates=False), ["WM_CLOSE to 0.0", SENT, "terminate|refused for pid ",
                                                             "failed"])

    def test_keeps_as_many_windows_as_fit(self):
        out = self.close("a" * 40, waits="e")
        self.assertEqual(sum(line.startswith("WM_CLOSE to 0.") for line in out), int(define("MAX_WINDOWS").split()[2]))
        self.assertEqual(out[-1], "ended")


class Boost(unittest.TestCase):
    """The optional boost: what it may touch, and that without its file nothing of it runs."""

    def test_the_file_and_levels_match_the_job(self):
        self.assertEqual(BOOST_LEVELS, (250, 251))  # never above Ford's screens (Desktop.exe, 250)
        self.assertIn(f'#define BOOST_PATH L"{GUARD_BOOST.replace(chr(92), chr(92) * 2)}"', SOURCE)
        self.assertIn(f"#define BOOST_HIGHEST {min(BOOST_LEVELS)}\n", SOURCE)
        self.assertIn(f"#define BOOST_LOWEST {max(BOOST_LEVELS)}\n", SOURCE)
        self.assertIn("#define BOOST_FROM 252 ", SOURCE)

    def test_without_the_file_nothing_of_the_boost_runs(self):
        # run in StartBoost; here only where WinMain calls it
        self.assertIn("static int boost_level;", SOURCE)  # 0 until the file names a level
        self.assertIn("    if (watching)\n        start_boost();", SOURCE)  # never in a passing instance
        self.assertEqual(SOURCE.count("boost(&watched, "), 1)
        self.assertIn("if (!boost_level || !app->process)\n        return;", function("boost"))

    def test_boosts_only_while_the_app_is_alone_and_before_either_rule(self):
        loop = SOURCE[SOURCE.index("for (;;) {"):]
        self.assertLess(loop.index("follow_app(&watched, name)"), loop.index("boost(&watched, "))
        self.assertLess(loop.index("boost(&watched, vis && scan.others == 0)"), loop.index("switch (judge("))

    def test_the_guard_stays_ahead_of_what_it_raises(self):
        start = function("start_boost")
        self.assertIn("set_priority(GetCurrentThread(), boost_level - 1)", start)
        self.assertLess(start.index("boost_level - 1"), start.index('note("boost", "on:'))
        self.assertIn("boost_level = 0;", start[start.index("boost_level - 1"):])  # refused: off

    def test_sets_priorities_only_through_held_handles_and_on_itself(self):
        calls = re.findall(r"set_priority\(((?:[^()]|\([^()]*\))*)\)", SOURCE)
        self.assertEqual(sorted(calls), ["GetCurrentThread(), CALM_FROM - 1", "GetCurrentThread(), boost_level - 1",
                                         "boosted[i].thread, BOOST_FROM", "boosted[i].thread, boost_level",
                                         "calmed[i].thread, CALM_FROM", "calmed[j].thread, CALM_LEVEL"])

    def test_imports_nothing_new_by_name(self):
        for name in ("OpenThread", "CeSetThreadPriority", "Thread32First", "Thread32Next"):
            self.assertIn(f'L"{name}")', SOURCE)  # looked up at run time, like toolhelp

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
    def test_reads_only_250_and_251_from_the_file(self):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work)
        program = build(work, [define("BOOST_HIGHEST"), define("BOOST_LOWEST"),
                               function("is_blank"), function("boost_level_of"),
                               "int main(int argc, char **argv) {",
                               "    int i;",
                               "    for (i = 1; i < argc; i++)",
                               '        printf("%d\\n", boost_level_of(argv[i], (int)strlen(argv[i])));',
                               "    return 0;", "}"])
        cases = {"250": 250, "251": 251, "250\r\n": 250, " 251 ": 251, "\t250\n": 250, "249": 0,
                 "252": 0, "248": 0, "25": 0, "2500": 0, "0250": 0, "250x": 0, "x250": 0, "-250": 0,
                 "": 0, "2 50": 0, "on": 0}
        out = subprocess.run([str(program), *cases], check=True, capture_output=True, text=True).stdout
        self.assertEqual(dict(zip(cases, map(int, out.split()))), cases)


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class ThreadList(unittest.TestCase):
    """read_threads() from s2amrun.c over a scripted toolhelp list: a failed list is not an empty one."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        cls.program = build(cls.work, [
            *WINDOWS, define("TH32CS_SNAPPROCESS"), define("TH32CS_SNAPTHREAD"), define("TH32CS_SNAPNOHEAPS"),
            declared(r"typedef struct \{[^}]*\} ThreadEntry;"),
            declared(r"typedef struct \{[^}]*\} Listed;"),
            "static DWORD owners[16]; static int threads, at, no_snapshot, no_first;",
            "static HANDLE snapshot(DWORD flags, DWORD pid)",
            "{ (void)flags; (void)pid; at = 0; return no_snapshot ? INVALID_HANDLE_VALUE : (HANDLE)1; }",
            "static BOOL next_thread(HANDLE list, ThreadEntry *entry)",
            "{ (void)list; if (at >= threads) return FALSE; entry->th32ThreadID = 100 + at;",
            "  entry->th32OwnerProcessID = owners[at]; entry->tpBasePri = 252; at++; return TRUE; }",
            "static BOOL first_thread(HANDLE list, ThreadEntry *entry)",
            "{ return no_first ? FALSE : next_thread(list, entry); }",
            "static BOOL close_snapshot(HANDLE list) { (void)list; return TRUE; }",
            function("read_threads"),
            "int main(int argc, char **argv) {",
            "    Listed list[4];",
            "    int i, count;",
            "    no_snapshot = atoi(argv[1]);",
            "    no_first = atoi(argv[2]);",
            "    for (i = 3; i < argc; i++)",
            "        owners[threads++] = (DWORD)atoi(argv[i]);",
            "    count = read_threads(7, list, 4);",
            '    printf("%d", count);',
            "    for (i = 0; i < count; i++)",
            '        printf(" %u", (unsigned)list[i].id);',
            '    printf("\\n");',
            "    return 0;",
            "}"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def read(self, *owners, no_snapshot=0, no_first=0):
        return subprocess.run([str(self.program), str(no_snapshot), str(no_first), *map(str, owners)],
                              check=True, capture_output=True, text=True).stdout.split()

    def test_lists_only_the_apps_threads(self):
        self.assertEqual(self.read(7, 3, 7, 9), ["2", "100", "102"])

    def test_a_list_that_could_not_be_taken_is_no_list(self):
        # review point 2: "not taken" must never read as "the thread has ended"
        self.assertEqual(self.read(7, no_snapshot=1), ["-1"])
        self.assertEqual(self.read(7, no_first=1), ["-1"])
        self.assertEqual(self.read(3, 9), ["-1"])  # a running app has a thread
        self.assertEqual(self.read(7, 7, 7, 7, 7), ["-1"])  # more than fit: nothing is decided


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class ProcessList(unittest.TestCase):
    """find_process() from s2amrun.c over a scripted toolhelp list: no list is not "not running"."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        cls.program = build(cls.work, [
            *WINDOWS, "#define MAX_PATH 260", "#define _wcsicmp wcscasecmp",
            define("TH32CS_SNAPPROCESS"), define("TH32CS_SNAPNOHEAPS"),
            declared(r"typedef struct \{[^}]*\} ProcessEntry;"),
            r"""
static char **names;
static int nnames, at, no_snapshot, no_first;

static HANDLE snapshot(DWORD flags, DWORD pid)
{
    (void)flags; (void)pid;
    at = 0;
    return no_snapshot ? INVALID_HANDLE_VALUE : (HANDLE)1;
}

static BOOL next_process(HANDLE list, ProcessEntry *entry)
{
    (void)list;
    if (at >= nnames)
        return FALSE;
    mbstowcs(entry->szExeFile, names[at], MAX_PATH);
    entry->th32ProcessID = 100 + at++;
    return TRUE;
}

static BOOL first_process(HANDLE list, ProcessEntry *entry)
{
    return no_first ? FALSE : next_process(list, entry);
}

static BOOL close_snapshot(HANDLE list) { (void)list; return TRUE; }
""",
            function("find_process"),
            r"""
int main(int argc, char **argv)
{
    DWORD pid = 99;
    int count = -1;
    BOOL listed;
    no_snapshot = atoi(argv[1]);
    no_first = atoi(argv[2]);
    names = argv + 3;
    nnames = argc - 3;
    listed = find_process(L"AutoKit.exe", &pid, &count);
    printf("%d %u %d\n", listed, (unsigned)pid, count);
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def find(self, *names, no_snapshot=0, no_first=0):
        """(a list was taken, the pid found, processes counted)"""
        out = subprocess.run([str(self.program), str(no_snapshot), str(no_first), *names], check=True,
                             capture_output=True, text=True).stdout
        return tuple(map(int, out.split()))

    def test_finds_the_first_instance_by_file_name_in_any_case(self):
        self.assertEqual(self.find("nk.exe", "autokit.EXE", "AutoKit.exe"), (1, 101, 3))
        self.assertEqual(self.find("nk.exe", "Media.exe"), (1, 0, 2))  # listed, and not running

    def test_a_list_that_could_not_be_taken_says_nothing(self):
        # review A: a failed lookup must not read as "the app has ended"
        self.assertEqual(self.find("AutoKit.exe", no_snapshot=1), (0, 0, 0))
        self.assertEqual(self.find("AutoKit.exe", no_first=1), (0, 0, 0))


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class StartBoost(unittest.TestCase):
    """start_boost() and boost() from s2amrun.c, the real thread list included, over fakes for the
    file, toolhelp and the thread functions: without a valid file there is no thread list and no
    priority call at all."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        names = ("put_uint", "put_text", "is_blank", "boost_level_of", "read_threads", "note_thread", "listed_at",
                 "drop", "boost_settle", "boost_open", "boost_raise", "boost_report", "boost", "start_boost")
        cls.program = build(cls.work, [
            *WINDOWS, define("BOOST_PATH"), define("BOOST_FROM"), define("BOOST_HIGHEST"), define("BOOST_LOWEST"),
            define("MAX_BOOSTED"), define("MAX_LISTED"), define("TH32CS_SNAPPROCESS"), define("TH32CS_SNAPTHREAD"),
            define("TH32CS_SNAPNOHEAPS"),
            "#define GENERIC_READ 0x80000000", "#define FILE_SHARE_READ 1", "#define OPEN_EXISTING 3",
            "#define FILE_ATTRIBUTE_NORMAL 0x80",
            declared(r"typedef struct \{[^}]*\} ThreadEntry;"),
            declared(r"typedef struct \{[^}]*\} Listed;"),
            declared(r"enum \{ LEFT, OPENED, RAISED \};"),
            declared(r"typedef struct \{(?:[^}]|\*/)*?\} Boosted;"),
            declared(r"typedef struct \{[^}]*\} Watched;"),
            declared(r"static int boost_level;"), declared(r"static Boosted boosted\[MAX_BOOSTED\];"),
            declared(r"static int boosted_count;"),
            r"""
#define OWN ((HANDLE)4000)
#define THREAD ((HANDLE)5000)
static const char *content;  /* the boost file's text; NULL: there is none */
static int functions = 1, own_allowed = 1, snapshots, sets, at, real = 252;

static HANDLE CreateFileW(const WCHAR *path, DWORD access, DWORD share, void *security, DWORD disposition,
                          DWORD attributes, HANDLE template_file)
{
    (void)path; (void)access; (void)share; (void)security; (void)disposition; (void)attributes;
    (void)template_file;
    return content ? (HANDLE)2000 : INVALID_HANDLE_VALUE;
}

static BOOL ReadFile(HANDLE file, void *buffer, DWORD size, DWORD *got, void *overlapped)
{
    (void)file; (void)overlapped;
    *got = (DWORD)strlen(content) < size ? (DWORD)strlen(content) : size;
    memcpy(buffer, content, *got);
    return TRUE;
}

static BOOL CloseHandle(HANDLE handle) { (void)handle; return TRUE; }
static HANDLE GetCurrentThread(void) { return OWN; }
static BOOL load_priority(void) { return functions; }

static HANDLE snapshot(DWORD flags, DWORD pid)
{
    (void)flags; (void)pid;
    snapshots++;
    at = 0;
    return (HANDLE)3000;
}

static BOOL next_thread(HANDLE list, ThreadEntry *entry)
{
    (void)list;
    if (at++ > 0)
        return FALSE;
    entry->th32ThreadID = 10;  /* the app's one thread, at 252 until it is raised */
    entry->th32OwnerProcessID = 7;
    entry->tpBasePri = real;
    return TRUE;
}

static BOOL first_thread(HANDLE list, ThreadEntry *entry) { return next_thread(list, entry); }
static BOOL close_snapshot(HANDLE list) { (void)list; return TRUE; }
static HANDLE open_thread(DWORD access, BOOL inherit, DWORD id) { (void)access; (void)inherit; (void)id; return THREAD; }

static BOOL set_priority(HANDLE thread, int priority)
{
    sets++;
    printf("set %s %d\n", thread == OWN ? "guard" : "thread", priority);
    if (thread == OWN)
        return own_allowed;
    real = priority;
    return TRUE;
}

static void note(const char *event, const char *detail, unsigned long value)
{
    printf("log %s%s", event, detail ? "|" : "\n");
    if (detail)
        printf("%s%lu\n", detail, value);
}
""",
            *(function(name) for name in names),
            r"""
int main(int argc, char **argv)
{
    /* the file's text ("-": none), the thread functions there (1/0), the guard's own change
       allowed (1/0); then three looks alone on the screen and one not */
    Watched app;
    int i;
    (void)argc;
    content = strcmp(argv[1], "-") ? argv[1] : NULL;
    functions = atoi(argv[2]);
    own_allowed = atoi(argv[3]);
    app.pid = 7;
    app.process = (HANDLE)1007;
    start_boost();
    for (i = 0; i < 4; i++)
        boost(&app, i < 3);
    printf("level %d snapshots %d sets %d\n", boost_level, snapshots, sets);
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def start(self, content, functions=True, own_allowed=True):
        return subprocess.run([str(self.program), content, str(int(functions)), str(int(own_allowed))], check=True,
                              capture_output=True, text=True).stdout.splitlines()

    def test_without_the_file_nothing_of_the_boost_runs(self):
        self.assertEqual(self.start("-"), ["level 0 snapshots 0 sets 0"])  # not even a log line

    def test_a_file_without_250_or_251_turns_it_off(self):
        for content in ("249", "252", "on", ""):
            self.assertEqual(self.start(content), ["log boost|off: the boost file holds neither 250 nor 251",
                                                   "level 0 snapshots 0 sets 0"])

    def test_a_system_without_the_thread_functions_or_that_refuses_the_guard_turns_it_off(self):
        off = "log boost|off: the thread functions are missing or refused"
        self.assertEqual(self.start("251", functions=False), [off, "level 0 snapshots 0 sets 0"])
        self.assertEqual(self.start("251", own_allowed=False), ["set guard 250", off, "level 0 snapshots 0 sets 1"])

    def test_with_the_file_the_guard_goes_first_then_the_apps_thread(self):
        out = self.start("251\r\n")
        self.assertEqual(out[:2], ["set guard 250",
                                   "log boost|on: while the app is alone on the screen, its threads at 252 run at 251"])
        self.assertEqual([line for line in out if line.startswith("set thread ")], ["set thread 251", "set thread 252"])
        self.assertEqual(out[-1], "level 251 snapshots 6 sets 3")


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Bookkeeping(unittest.TestCase):
    """follow_app(), boost() and its steps from s2amrun.c, one look at a time as WinMain runs them,
    over a fake kernel: the app's process (its list entry, its handle and that handle's wait),
    threads with a real priority, a thread list that may or may not show a change, OpenThread,
    CeSetThreadPriority, handles."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        names = ("put_uint", "put_text", "note_thread", "listed_at", "drop", "boost_settle", "boost_open",
                 "boost_raise", "boost_report", "boost_forget", "boost", "follow_app")
        cls.program = build(cls.work, [
            *WINDOWS, define("BOOST_FROM"), define("MAX_BOOSTED"), define("MAX_LISTED"),
            declared(r"typedef struct \{[^}]*\} Listed;"),
            declared(r"enum \{ LEFT, OPENED, RAISED \};"),
            declared(r"typedef struct \{(?:[^}]|\*/)*?\} Boosted;"),
            declared(r"typedef struct \{[^}]*\} Watched;"),
            declared(r"static int boost_level;"), declared(r"static Boosted boosted\[MAX_BOOSTED\];"),
            declared(r"static int boosted_count;"),
            r"""
#define MAXT 64
static struct { DWORD id; int real, listed, alive, handles, refuse, noopen, vanish; } T[MAXT];
static int nT, reflects = 1, fail_reads, reads;

/* The app's process: pid 7, then 8 after a relaunch. A handle is 1000 + the pid it was opened
   for, and is signalled once that instance has ended. */
static struct { DWORD pid; int alive, handles, no_list, no_open, wait_fails; } P = {7, 1, 0, 0, 0, 0};
static Watched watched;

static BOOL find_process(const WCHAR *name, DWORD *pid, int *count)
{
    (void)name; (void)count;
    *pid = 0;
    if (P.no_list)
        return FALSE;
    *pid = P.alive ? P.pid : 0;
    return TRUE;
}

static HANDLE OpenProcess(DWORD access, BOOL inherit, DWORD pid)
{
    (void)access; (void)inherit;
    if (P.no_open || !P.alive || pid != P.pid)
        return NULL;
    P.handles++;
    return (HANDLE)(intptr_t)(1000 + pid);
}

static DWORD WaitForSingleObject(HANDLE process, DWORD ms)
{
    (void)ms;
    if (P.wait_fails)
        return WAIT_FAILED;
    return P.alive && (intptr_t)process - 1000 == (intptr_t)P.pid ? WAIT_TIMEOUT : WAIT_OBJECT_0;
}

static DWORD GetLastError(void) { return 6; }  /* ERROR_INVALID_HANDLE */

static int find(DWORD id)
{
    int i;
    for (i = 0; i < nT; i++)
        if (T[i].id == id)
            return i;
    return -1;
}

static int read_threads(DWORD pid, Listed *list, int size)
{
    int i, count = 0;
    (void)pid;
    if (fail_reads & (1 << ++reads))
        return -1;
    for (i = 0; i < nT && count < size; i++)
        if (T[i].alive) {
            list[count].id = T[i].id;
            list[count].priority = T[i].listed;
            count++;
        }
    return count > 0 ? count : -1;
}

static HANDLE fake_open(DWORD access, BOOL inherit, DWORD id)
{
    int i = find(id);
    (void)access; (void)inherit;
    if (i < 0 || !T[i].alive || T[i].noopen)
        return NULL;
    T[i].handles++;
    printf("open %u\n", (unsigned)id);
    if (T[i].vanish)
        T[i].alive = 0;  /* it ends right after it was opened */
    return (HANDLE)(intptr_t)(i + 1);
}

static BOOL fake_set(HANDLE thread, int priority)
{
    int i = (int)(intptr_t)thread - 1;
    printf("set %u %d\n", (unsigned)T[i].id, priority);
    if (T[i].refuse)
        return FALSE;
    T[i].real = priority;
    if (reflects)
        T[i].listed = priority;
    return TRUE;
}

static BOOL CloseHandle(HANDLE handle)
{
    if ((intptr_t)handle >= 1000)
        P.handles--;
    else
        T[(intptr_t)handle - 1].handles--;
    return TRUE;
}

static void note(const char *event, const char *detail, unsigned long value)
{
    if (detail)
        printf("log %s|%s%lu\n", event, detail, value);
    else
        printf("log %s\n", event);
}

typedef HANDLE (*OpenThreadFn)(DWORD, BOOL, DWORD);
typedef BOOL (*SetPriorityFn)(HANDLE, int);
static OpenThreadFn open_thread = fake_open;
static SetPriorityFn set_priority = fake_set;
""",
            *(function(name) for name in names),
            r"""
int main(void)
{
    char word[16];
    unsigned id;
    int value, i, renewed;
    while (scanf("%15s", word) == 1) {
        if (!strcmp(word, "thread") && scanf("%u %d", &id, &value) == 2) {
            T[nT].id = id; T[nT].real = T[nT].listed = value; T[nT].alive = 1; nT++;
        } else if (!strcmp(word, "exit")) {  /* the app's process ends, and its threads with it */
            P.alive = 0;
            for (i = 0; i < nT; i++)
                T[i].alive = 0;
        } else if (!strcmp(word, "launch")) {  /* a new instance */
            P.pid++;
            P.alive = 1;
        } else if (!strcmp(word, "nolist") && scanf("%d", &value) == 1) {
            P.no_list = value;  /* the process list cannot be taken */
        } else if (!strcmp(word, "noopenapp") && scanf("%d", &value) == 1) {
            P.no_open = value;
        } else if (!strcmp(word, "waitfails") && scanf("%d", &value) == 1) {
            P.wait_fails = value;
        } else if (!strcmp(word, "end") && scanf("%u", &id) == 1) {
            T[find(id)].alive = 0;
        } else if (!strcmp(word, "app") && scanf("%u %d", &id, &value) == 2) {
            T[find(id)].real = T[find(id)].listed = value;  /* the app sets it itself */
        } else if (!strcmp(word, "reflect") && scanf("%d", &value) == 1) {
            reflects = value;
        } else if (!strcmp(word, "refuse") && scanf("%u %d", &id, &value) == 2) {
            T[find(id)].refuse = value;
        } else if (!strcmp(word, "noopen") && scanf("%u %d", &id, &value) == 2) {
            T[find(id)].noopen = value;
        } else if (!strcmp(word, "vanish") && scanf("%u", &id) == 1) {
            T[find(id)].vanish = 1;
        } else if (!strcmp(word, "failread") && scanf("%d", &value) == 1) {
            fail_reads |= 1 << value;  /* that list of the next look fails */
        } else if (!strcmp(word, "level") && scanf("%d", &value) == 1) {
            boost_level = value;
        } else if (!strcmp(word, "look") && scanf("%d", &value) == 1) {  /* as WinMain, alone or not */
            reads = 0;
            renewed = follow_app(&watched, L"AutoKit.exe");
            printf("app %u held %d%s\n", (unsigned)watched.pid, watched.process != NULL, renewed ? " new" : "");
            boost(&watched, value);
            fail_reads = 0;
        } else if (!strcmp(word, "show")) {
            for (i = 0; i < nT; i++)
                printf("thread %u real %d handles %d\n", (unsigned)T[i].id, T[i].real, T[i].handles);
            printf("entries %d\n", boosted_count);
            printf("process handles %d\n", P.handles);
        }
        fflush(stdout);
    }
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_kernel(self, script):
        """Runs the commands; returns the output of each "look" and "show" in turn."""
        out = subprocess.run([str(self.program)], input="level 251\n" + script, check=True,
                             capture_output=True, text=True).stdout
        return out.splitlines()

    def state(self, lines):
        """The last "show": {thread: (real priority, open handles)}, and the number of entries."""
        start = max(i for i, line in enumerate(lines) if line.startswith("thread ")
                    and (i == 0 or not lines[i - 1].startswith("thread ")))
        threads = {}
        for line in lines[start:]:
            if line.startswith("entries "):
                return threads, int(line.split()[1])
            _, tid, _, real, _, handles = line.split()
            threads[int(tid)] = (int(real), int(handles))
        raise AssertionError(lines)

    def logs(self, lines):
        return [line[4:] for line in lines if line.startswith("log ")]

    def test_raises_the_apps_252_threads_while_alone_and_puts_them_back(self):
        lines = self.run_kernel("thread 10 252\nthread 11 251\nthread 12 252\nlook 1\nshow\n")
        self.assertEqual(self.state(lines), ({10: (251, 1), 11: (251, 0), 12: (251, 1)}, 2))
        self.assertEqual(self.logs(lines), ["boost|thread 12 from 252 to 251", "boost|thread 10 from 252 to 251",
                                            "boost|thread 10 listed at 251 after the change",
                                            "boost|thread 12 listed at 251 after the change"])
        lines = self.run_kernel("thread 10 252\nthread 11 251\nthread 12 252\nlook 1\nlook 1\nlook 1\n"
                                "look 0\nshow\nlook 0\n")
        self.assertEqual(self.state(lines), ({10: (252, 0), 11: (251, 0), 12: (252, 0)}, 0))
        self.assertEqual(len(self.logs(lines)), 4 + 2)  # each change once; nothing on the extra looks
        self.assertEqual(sum(line.startswith("open ") for line in lines), 2)

    def test_puts_back_a_thread_whose_list_never_shows_the_change(self):
        # review point 6: if the list keeps showing 252, the thread still goes back
        lines = self.run_kernel("reflect 0\nthread 10 252\nlook 1\nshow\nlook 1\nlook 0\nshow\n")
        self.assertIn("boost|thread 10 listed at 252 after the change", self.logs(lines))
        self.assertEqual(sum(line.startswith("set 10 251") for line in lines), 1)  # not raised twice
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))

    def test_leaves_a_priority_the_app_set_itself(self):
        lines = self.run_kernel("thread 10 252\nlook 1\napp 10 248\nlook 0\nshow\n")
        self.assertIn("boost|thread 10 left as the app set it, at 248", self.logs(lines))
        self.assertEqual(self.state(lines), ({10: (248, 0)}, 0))

    def test_a_way_back_that_fails_is_tried_again_on_every_look(self):
        # review point 2: a refused restore is not forgotten
        lines = self.run_kernel("thread 10 252\nlook 1\nrefuse 10 1\nlook 0\nlook 0\nshow\n"
                                "refuse 10 0\nlook 0\nshow\n")
        self.assertEqual(self.logs(lines).count("boost|thread 10 would not go back from 251"), 1)
        self.assertEqual(sum(line == "set 10 252" for line in lines), 3)
        self.assertIn("boost|thread 10 from 251 to 252", self.logs(lines))
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))

    def test_without_a_list_nothing_is_decided(self):
        # review point 2: a failed list keeps every raised thread for the next look
        lines = self.run_kernel("thread 10 252\nlook 1\nfailread 1\nlook 0\nshow\n")
        self.assertEqual(self.state(lines), ({10: (251, 1)}, 1))
        lines = self.run_kernel("thread 10 252\nlook 1\nfailread 1\nlook 0\nlook 0\nshow\n")
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))

    def test_ended_threads_free_their_places(self):
        # review point 4: 32 threads that would not open, then end; a new video thread still goes up
        setup = "".join(f"thread {n} 252\nnoopen {n} 1\n" for n in range(1, 33))
        lines = self.run_kernel(setup + "look 1\nshow\n")
        self.assertEqual(self.state(lines)[1], 32)
        ends = "".join(f"end {n}\n" for n in range(1, 33))
        lines = self.run_kernel(setup + "look 1\n" + ends + "thread 100 252\nlook 1\nshow\n")
        self.assertEqual(self.state(lines)[0][100], (251, 1))
        self.assertEqual(self.state(lines)[1], 1)

    def test_a_raised_thread_that_ends_lets_go_of_its_handle(self):
        lines = self.run_kernel("thread 10 252\nthread 11 251\nlook 1\nend 10\nlook 1\nshow\n")
        self.assertEqual(self.state(lines), ({10: (251, 0), 11: (251, 0)}, 0))

    def test_holds_each_raised_thread_and_puts_it_back_through_that_handle(self):
        # review point 5: no second OpenThread by id on the way back
        lines = self.run_kernel("thread 10 252\nlook 1\nshow\nlook 0\nshow\n")
        self.assertEqual(sum(line.startswith("open ") for line in lines), 1)
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))
        first = lines[:lines.index("entries 1") + 1]
        self.assertEqual(self.state(first), ({10: (251, 1)}, 1))

    def test_raises_nothing_without_a_second_list(self):
        lines = self.run_kernel("thread 10 252\nfailread 2\nlook 1\nshow\nlook 1\nshow\n")
        first = lines[:lines.index("entries 0") + 1]
        self.assertEqual(self.state(first), ({10: (252, 0)}, 0))
        self.assertEqual(self.state(lines), ({10: (251, 1)}, 1))

    def test_never_sets_a_thread_that_ended_after_it_was_opened(self):
        # its id is not the app's any more: the second list must show it in the app at 252
        lines = self.run_kernel("thread 10 252\nthread 11 251\nvanish 10\nlook 1\nshow\n")
        self.assertFalse([line for line in lines if line.startswith("set ")])
        self.assertEqual(self.state(lines), ({10: (252, 0), 11: (251, 0)}, 0))

    def test_a_refused_raise_waits_until_the_app_is_alone_again(self):
        lines = self.run_kernel("thread 10 252\nrefuse 10 1\nlook 1\nlook 1\nshow\nrefuse 10 0\n"
                                "look 0\nlook 1\nshow\n")
        self.assertEqual(self.logs(lines).count("boost|thread 10 would not change from 252"), 1)
        self.assertEqual(self.state(lines), ({10: (251, 1)}, 1))

    def test_reports_the_list_on_the_next_look_when_its_own_failed(self):
        lines = self.run_kernel("thread 10 252\nfailread 3\nlook 1\nshow\nlook 1\n")
        logs = self.logs(lines)
        self.assertEqual(logs.count("boost|thread 10 listed at 251 after the change"), 1)
        self.assertLess(lines.index("entries 1"), lines.index("log boost|thread 10 listed at 251 after the change"))

    def apps(self, lines):
        """What each look made of the app's process: "<pid> held <0/1>[ new]"."""
        return [line[4:] for line in lines if line.startswith("app ")]

    def process_handles(self, lines):
        return int([line for line in lines if line.startswith("process handles ")][-1].split()[2])

    def test_forgets_every_handle_once_the_apps_handle_says_it_ended(self):
        lines = self.run_kernel("thread 10 252\nthread 12 252\nlook 1\nexit\nlook 1\nshow\n")
        self.assertEqual(self.state(lines), ({10: (251, 0), 12: (251, 0)}, 0))
        self.assertEqual(self.apps(lines), ["7 held 1 new", "0 held 0"])
        self.assertEqual(self.process_handles(lines), 0)
        # ended, and the list fails on the same look: the handle said so, the list is not needed
        lines = self.run_kernel("thread 10 252\nlook 1\nexit\nnolist 1\nlook 1\nshow\n")
        self.assertEqual(self.state(lines), ({10: (251, 0)}, 0))
        self.assertEqual(self.apps(lines), ["7 held 1 new", "0 held 0"])

    def test_a_list_that_fails_never_drops_raised_threads(self):
        # review A: while the guard holds the app's handle, no failed lookup can say it ended
        lines = self.run_kernel("thread 10 252\nlook 1\nnolist 1\nlook 1\nlook 0\nshow\n")
        self.assertEqual(self.apps(lines), ["7 held 1 new", "7 held 1", "7 held 1"])
        self.assertIn("boost|thread 10 from 251 to 252", self.logs(lines))
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))
        self.assertEqual(self.process_handles(lines), 1)

    def test_a_wait_that_fails_keeps_the_app_and_what_was_raised(self):
        lines = self.run_kernel("thread 10 252\nlook 1\nwaitfails 1\nnolist 1\nlook 1\nlook 1\nshow\n"
                                "waitfails 0\nnolist 0\nlook 0\nshow\n")
        first = lines[:lines.index("entries 1") + 1]
        self.assertEqual(self.state(first), ({10: (251, 1)}, 1))
        self.assertEqual(self.apps(lines), ["7 held 1 new", "7 held 1", "7 held 1", "7 held 1"])
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))

    def test_a_wait_that_fails_is_logged_once_with_the_error(self):
        # review round 3: it keeps the guard watching, so a car log must show it; once per stretch
        told = "error|cannot wait for the app, it counts as running, error 6"
        lines = self.run_kernel("look 1\nwaitfails 1\nlook 1\nlook 1\nlook 1\nwaitfails 0\nlook 1\n"
                                "waitfails 1\nlook 1\nlook 1\n")
        self.assertEqual(self.logs(lines).count(told), 2)
        self.assertEqual(self.apps(lines), ["7 held 1 new"] + ["7 held 1"] * 6)

    def test_without_a_handle_for_the_app_nothing_is_raised(self):
        # review A: the app's end could not be told, so nothing may be held for it
        lines = self.run_kernel("noopenapp 1\nthread 10 252\nlook 1\nlook 1\nshow\n")
        self.assertFalse([line for line in lines if line.startswith(("open ", "set "))])
        self.assertEqual(self.state(lines), ({10: (252, 0)}, 0))
        self.assertEqual(self.apps(lines), ["7 held 0 new", "7 held 0"])
        # the handle is asked for again on each look; once it opens, the boost runs
        lines = self.run_kernel("noopenapp 1\nthread 10 252\nlook 1\nnoopenapp 0\nlook 1\nshow\n")
        self.assertEqual(self.apps(lines), ["7 held 0 new", "7 held 1"])
        self.assertEqual(self.state(lines), ({10: (251, 1)}, 1))

    def test_a_list_that_fails_leaves_the_last_answer(self):
        # no handle: a failed list says neither "ended" nor "another instance"
        lines = self.run_kernel("noopenapp 1\nlook 1\nnolist 1\nlook 1\nexit\nlook 1\nnolist 0\nlook 1\n")
        self.assertEqual(self.apps(lines), ["7 held 0 new", "7 held 0", "7 held 0", "0 held 0"])

    def test_a_relaunch_starts_over_with_the_new_instance(self):
        lines = self.run_kernel("thread 10 252\nlook 1\nexit\nlaunch\nthread 20 252\nlook 1\nshow\n")
        self.assertEqual(self.apps(lines), ["7 held 1 new", "8 held 1 new"])
        self.assertEqual(self.state(lines), ({10: (251, 0), 20: (251, 1)}, 1))
        self.assertEqual(self.process_handles(lines), 1)  # the old instance's handle is closed


class Script(unittest.TestCase):
    def test_both_actions_pass_the_car_rules(self):
        for action in ("enable", "disable"):
            mortscript.check(guard_script(Job(SERIAL, "guard", params={"action": action, **PARAMS})))
        for bad in ({"action": "maybe", **PARAMS}, {"action": "enable"}, {"action": "enable",
                                                                          "stock_size": "11776"}):
            with self.subTest(bad), self.assertRaises(ValueError):
                guard_script(Job(SERIAL, "guard", params=bad))

    def test_selftest_runs_before_anything_is_copied(self):
        script = guard_script(Job(SERIAL, "guard", params={"action": "enable", **PARAMS}))
        self.assertLess(script.index("--s2am-selftest"), script.index("Copy("))
        self.assertLess(script.index('ProcExists("SyncAppsRunner.exe")'), script.index("RunWait("))

    def script(self, **params):
        return guard_script(Job(SERIAL, "guard", params={**PARAMS, **params}))

    def test_boost_is_written_and_checked_once_the_guard_is_in_place(self):
        for level in BOOST_LEVELS:
            script = self.script(action="enable", boost=level)
            mortscript.check(script)
            written = script.index(f'WriteFile("{GUARD_BOOST}", "{level}")')
            self.assertLess(script.index('"\\s2amrun.exe", tools & "\\SyncAppsRunner.exe"'), written)
            self.assertLess(written, script.index(f'If (ReadFile("{GUARD_BOOST}") ne "{level}")'))
            self.assertIn("the boost did not write; the guard is on, without the boost", script)

    def test_a_guard_job_can_measure_once_the_guard_and_the_boost_are_in_place(self):
        job = Job(SERIAL, "guard", params={**PARAMS, "action": "enable", "boost": 250, "measure": 600})
        script = guard_script(job)
        mortscript.check(script)
        started = script.index('Run(logs & "\\s2amdrive.exe", "600 load " & logs)')
        self.assertLess(script.index(f'If (ReadFile("{GUARD_BOOST}") ne "250")'), started)
        self.assertIn(f'logs = "{load_folder(job.id)}"', script)
        replay = script[script.index("replayed.txt"):script.index("tools = ")]
        self.assertIn(f'Copy("{load_folder(job.id)}\\drive.log", out & "\\drive.log", TRUE)', replay)
        self.assertTrue(stick.runs_again(job))
        self.assertNotIn("s2amdrive.exe", self.script(action="enable", boost=250))
        with self.assertRaises(ValueError):
            self.script(action="disable", measure=600)

    def test_boost_off_removes_only_the_boost(self):
        script = self.script(action="enable", boost=0)
        mortscript.check(script)
        self.assertIn(f'  Delete("{GUARD_BOOST}")', script)
        self.assertNotIn(f'WriteFile("{GUARD_BOOST}"', script)
        self.assertIn(BOOST_STUCK_ON, script)

    def test_without_boost_the_file_is_left_as_it_is(self):
        script = self.script(action="enable")
        self.assertNotIn(f'WriteFile("{GUARD_BOOST}"', script)
        self.assertNotIn(f'Delete("{GUARD_BOOST}")', script)

    def test_off_takes_the_boost_with_it(self):
        script = self.script(action="disable")
        mortscript.check(script)
        self.assertLess(script.index("Delete(tools & \"\\SyncAppsRunner.orig.exe\")"),
                        script.index(f'Delete("{GUARD_BOOST}")'))

    def test_a_boost_that_did_not_write_is_removed_and_the_removal_checked(self):
        script = self.script(action="enable", boost=250)
        tail = script[script.index(f'If (ReadFile("{GUARD_BOOST}") ne "250")'):]
        order = [tail.index(s) for s in (f'Delete("{GUARD_BOOST}")', f'If (FileExists("{GUARD_BOOST}"))',
                                         BOOST_STUCK_WRITE, "the guard is on, without the boost")]
        self.assertEqual(order, sorted(order))

    def test_off_checks_the_boost_is_gone_once_the_stock_runner_is_back(self):
        # a stuck file must not stop --off: without the guard it does nothing (reported)
        script = self.script(action="disable")
        order = [script.index(s) for s in ('Copy(tools & "\\SyncAppsRunner.orig.exe", tools & "\\SyncAppsRunner.exe"',
                                           f'Delete("{GUARD_BOOST}")', BOOST_STUCK_OFF, "inv = out")]
        self.assertEqual(order, sorted(order))

    def test_refuses_any_other_boost(self):
        for bad in ({"action": "enable", "boost": 252}, {"action": "enable", "boost": 249},
                    {"action": "enable", "boost": 248},
                    {"action": "enable", "boost": "250"}, {"action": "enable", "boost": True},
                    {"action": "disable", "boost": 250}, {"action": "disable", "boost": 0}):
            with self.subTest(bad), self.assertRaises(ValueError):
                self.script(**bad)


@unittest.skipUnless(HAVE_UPSTREAM, "syncextpack fixtures not present")
class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        for patcher in (mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")}),
                        mock.patch.object(native, "binary", return_value=GUARD)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.car.put(MENU_XML, apps.render_menu([("AutoKit", "AutoKitPlugin", "")]))
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.exe", STOCK)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def runner(self, name="SyncAppsRunner.exe"):
        path = self.car._resolve(f"{TOOLS_CE}\\{name}")
        return path.read_bytes() if path.exists() else None

    def run_job(self, *args):
        work = self.tmp / f"job{len(list(self.tmp.glob('job*')))}"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["job", *args, "--serial", SERIAL, "--no-pack", "--work", str(work)])
        self.assertEqual(code, 0, out.getvalue())
        job = Job.from_json((work / "job.json").read_text())
        (work / "install.bin").write_bytes(b"pack")
        stick.prepare(self.stick, work / "install.bin", job, require_volume=False)
        self.car.insert(self.stick, work, job)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["stick", "import", str(self.stick), "--any-path"])
        return out.getvalue()

    def status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["status", "--serial", SERIAL])
        return out.getvalue()

    def test_on_keeps_the_stock_runner_and_off_puts_it_back(self):
        imported = self.run_job("runner-guard")
        self.assertIn("verified: runner guard is on (self-test: s2amrun ok", imported)
        self.assertEqual(self.runner(), GUARD)
        self.assertEqual(self.runner("SyncAppsRunner.orig.exe"), STOCK)
        self.assertIn("runner guard (fixes the freeze when leaving an app): on", self.status())

        newer = GUARD + b" v2"  # turned on again with a newer guard: it replaces the old one
        with mock.patch.object(native, "binary", return_value=newer):
            imported = self.run_job("runner-guard")
        self.assertIn("verified: runner guard is on", imported)
        self.assertEqual(self.runner(), newer)
        self.assertEqual(self.runner("SyncAppsRunner.orig.exe"), STOCK)  # still the stock runner, never the guard

        imported = self.run_job("runner-guard", "--off")
        self.assertIn("verified: runner guard is off", imported)
        self.assertEqual(self.runner(), STOCK)
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))

    def test_nothing_changes_if_the_guard_cannot_run_on_the_car(self):
        self.car.native_runs = False
        imported = self.run_job("runner-guard")
        self.assertIn("failed", imported)
        self.assertEqual(self.runner(), STOCK)
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))

    def test_waits_while_an_app_is_open(self):
        self.car.running.add("syncappsrunner.exe")
        self.assertIn("busy", self.run_job("runner-guard"))
        self.assertEqual(self.runner(), STOCK)

    def test_a_damaged_keep_is_rebuilt_from_the_stock_runner(self):
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.orig.exe", STOCK[:100])  # power cut mid-copy
        self.assertIn("runner guard is on", self.run_job("runner-guard"))
        self.assertEqual(self.runner("SyncAppsRunner.orig.exe"), STOCK)
        self.assertEqual(self.runner(), GUARD)

    def test_an_unknown_runner_is_never_replaced(self):
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.exe", b"someone else's runner")
        self.assertIn("failed", self.run_job("runner-guard"))
        self.assertEqual(self.runner(), b"someone else's runner")
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))

    def test_off_refuses_a_damaged_keep(self):
        self.run_job("runner-guard")
        self.car.put(f"{TOOLS_CE}\\SyncAppsRunner.orig.exe", STOCK[:100])
        self.assertIn("failed", self.run_job("runner-guard", "--off"))
        self.assertEqual(self.runner(), GUARD)  # still working, not replaced by a broken file

    def test_builder_refuses_a_guard_the_size_of_the_stock_runner(self):
        with mock.patch.object(native, "binary", return_value=b"x" * len(STOCK)):
            out = io.StringIO()
            with contextlib.redirect_stderr(out):
                code = cli.main(["job", "runner-guard", "--serial", SERIAL, "--no-pack",
                                 "--work", str(self.tmp / "same")])
        self.assertEqual(code, 1)
        self.assertIn("exactly the size", out.getvalue())

    def test_guard_log_shows_in_status(self):
        self.car.put("\\SyncExtendedPack\\_s2am\\guard.log", b"0|start|AutoKit.exe\r\n5|stuck|x1\r\n")
        self.run_job("inventory")
        self.assertIn("5|stuck|x1", self.status())

    def boost_file(self):
        path = self.car._resolve(GUARD_BOOST)
        return path.read_bytes() if path.exists() else None

    def test_boost_on_then_off_keeps_the_guard(self):
        imported = self.run_job("runner-guard", "--boost", "250")
        self.assertIn("verified: runner guard is on (self-test: s2amrun ok", imported)
        self.assertIn("priority 1), boost 250", imported)
        self.assertEqual(self.boost_file(), b"250")
        self.assertEqual(self.runner(), GUARD)
        self.assertIn("runner guard (fixes the freeze when leaving an app): on, boost 250", self.status())

        self.assertIn("boost 250 as before", self.run_job("runner-guard"))  # turned on again: it stays
        self.assertEqual(self.boost_file(), b"250")

        imported = self.run_job("runner-guard", "--boost", "off")
        self.assertIn("verified: runner guard is on", imported)
        self.assertIn(", boost off", imported)
        self.assertIsNone(self.boost_file())
        self.assertEqual(self.runner(), GUARD)
        self.assertIn("runner guard (fixes the freeze when leaving an app): on\n", self.status())

    def test_off_removes_the_boost_too(self):
        self.run_job("runner-guard", "--boost", "251")
        imported = self.run_job("runner-guard", "--off")
        self.assertIn("verified: runner guard is off", imported)
        self.assertIsNone(self.boost_file())
        self.assertEqual(self.runner(), STOCK)
        self.assertIn("runner guard (fixes the freeze when leaving an app): off", self.status())

    def test_a_car_without_the_thread_functions_is_told(self):
        self.car.thread_priority = False
        imported = self.run_job("runner-guard", "--boost", "250")
        self.assertIn("boost 250 written, but this SYNC lacks a thread function: it will not act", imported)

    def test_a_boost_that_does_not_write_fails_and_leaves_none(self):
        self.car.broken_copies.add(GUARD_BOOST.lower())
        self.assertIn("failed", self.run_job("runner-guard", "--boost", "250"))
        self.assertIsNone(self.boost_file())
        self.assertEqual(self.runner(), GUARD)  # the guard itself is on, without the boost

    def marker(self, imported):
        report = Store().report(SERIAL, imported.split(":")[0])
        return (report / "copy-failed.txt").read_text()

    def test_off_with_a_stuck_boost_file_still_takes_the_guard_away(self):
        self.run_job("runner-guard", "--boost", "251")
        self.car.stuck_files.add(GUARD_BOOST.lower())
        imported = self.run_job("runner-guard", "--off")
        self.assertIn("failed", imported)
        self.assertEqual(self.marker(imported), BOOST_STUCK_OFF)
        self.assertEqual(self.runner(), STOCK)  # off: the stock runner never reads the file
        self.assertIsNone(self.runner("SyncAppsRunner.orig.exe"))
        self.assertEqual(self.boost_file(), b"251")

    def test_boost_off_with_a_stuck_file_says_the_boost_stays(self):
        self.run_job("runner-guard", "--boost", "251")
        self.car.stuck_files.add(GUARD_BOOST.lower())
        imported = self.run_job("runner-guard", "--boost", "off")
        self.assertIn("failed", imported)
        self.assertEqual(self.marker(imported), BOOST_STUCK_ON)
        self.assertEqual(self.runner(), GUARD)
        self.assertEqual(self.boost_file(), b"251")

    def test_a_boost_that_neither_writes_nor_goes_is_reported(self):
        self.run_job("runner-guard", "--boost", "251")
        self.car.broken_copies.add(GUARD_BOOST.lower())
        self.car.stuck_files.add(GUARD_BOOST.lower())
        imported = self.run_job("runner-guard", "--boost", "250")
        self.assertIn("failed", imported)
        self.assertEqual(self.marker(imported), BOOST_STUCK_WRITE)
        left = Store().report(SERIAL, imported.split(":")[0]) / "guard-boost.txt"
        self.assertEqual(left.read_bytes(), self.boost_file())  # what the guard will find
        self.assertEqual(self.runner(), GUARD)

    def calm_file(self):
        path = self.car._resolve(GUARD_CALM)
        return path.read_bytes() if path.exists() else None

    def test_calm_on_then_off_keeps_the_guard(self):
        imported = self.run_job("runner-guard", "--calm", "on")
        self.assertIn("verified: runner guard is on (self-test: s2amrun ok", imported)
        self.assertIn("priority 1), calm on", imported)
        self.assertEqual(self.calm_file(), b"252")
        self.assertIsNone(self.boost_file())
        self.assertIn("runner guard (fixes the freeze when leaving an app): on, calm on", self.status())
        self.assertIn(", calm on", self.run_job("runner-guard"))  # turned on again: it stays
        imported = self.run_job("runner-guard", "--calm", "off")
        self.assertIn("verified: runner guard is on", imported)
        self.assertNotIn("calm on", imported)
        self.assertIsNone(self.calm_file())
        self.assertEqual(self.runner(), GUARD)

    def test_off_removes_the_calm_too(self):
        self.run_job("runner-guard", "--calm", "on")
        self.assertIn("verified: runner guard is off", self.run_job("runner-guard", "--off"))
        self.assertIsNone(self.calm_file())
        self.assertEqual(self.runner(), STOCK)

    def test_a_calm_that_does_not_write_fails_and_leaves_none(self):
        self.car.broken_copies.add(GUARD_CALM.lower())
        self.assertIn("failed", self.run_job("runner-guard", "--calm", "on"))
        self.assertIsNone(self.calm_file())
        self.assertEqual(self.runner(), GUARD)

    def test_a_stuck_calm_file_is_reported(self):
        self.run_job("runner-guard", "--calm", "on")
        self.car.stuck_files.add(GUARD_CALM.lower())
        imported = self.run_job("runner-guard", "--calm", "off")
        self.assertIn("failed", imported)
        self.assertEqual(self.marker(imported), CALM_STUCK_ON)
        imported = self.run_job("runner-guard", "--off")
        self.assertIn("failed", imported)
        self.assertEqual(self.marker(imported), CALM_STUCK_OFF)
        self.assertEqual(self.runner(), STOCK)

    def test_calm_beside_a_boost_is_refused_and_reported(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["job", "runner-guard", "--boost", "250", "--calm", "on", "--serial", SERIAL,
                             "--no-pack", "--work", str(self.tmp / "both-on")])
        self.assertNotEqual(code, 0)
        self.run_job("runner-guard", "--boost", "251")
        imported = self.run_job("runner-guard", "--calm", "on")  # the boost file is still on the car
        self.assertIn("boost 251 as before, calm written, but the boost is on", imported)
        self.assertNotIn("calm on", self.status())
        self.car.thread_priority = False
        imported = self.run_job("runner-guard", "--boost", "off", "--calm", "on")
        self.assertIn("calm written, but this SYNC lacks a thread function", imported)

    def test_status_reads_the_files_as_the_guard_does(self):
        report = self.tmp / "report"
        report.mkdir()
        for calm, boost, acts in ((b"252", None, True), (b"252\r\n", None, True), (b"252" + b" " * 13, None, False),
                                  (b" 252", None, False), (b"252", b"251", False), (b"252", b"junk", True),
                                  (b"252", b" 250\r\n", False), (b"250", None, False)):
            (report / "guard-calm.txt").write_bytes(calm)
            (report / "guard-boost.txt").unlink(missing_ok=True)
            if boost is not None:
                (report / "guard-boost.txt").write_bytes(boost)
            self.assertEqual(cli._calm_acts(report) and not cli._boost_acts(report), acts, (calm, boost))

    def test_calm_script_passes_the_car_rules_and_comes_after_the_guard(self):
        script = guard_script(Job(SERIAL, "guard", params={"action": "enable", "calm": True, **PARAMS}))
        mortscript.check(script)
        self.assertLess(script.index('"\\s2amrun.exe", tools & "\\SyncAppsRunner.exe"'),
                        script.index(f'WriteFile("{GUARD_CALM}", "252")'))
        mortscript.check(guard_script(Job(SERIAL, "guard", params={"action": "enable", "calm": False, **PARAMS})))
        for bad in ({"action": "disable", "calm": True}, {"action": "enable", "calm": 252}):
            with self.subTest(bad), self.assertRaises(ValueError):
                guard_script(Job(SERIAL, "guard", params={**PARAMS, **bad}))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["job", "runner-guard", "--off", "--calm", "on", "--serial", SERIAL, "--no-pack",
                             "--work", str(self.tmp / "never")])
        self.assertNotEqual(code, 0)
        self.assertFalse((self.tmp / "never" / "job.json").exists())

    def mic_file(self):
        path = self.car._resolve(GUARD_MIC)
        return path.read_bytes() if path.exists() else None

    def test_mic_on_then_off_keeps_the_guard_and_off_takes_it_away(self):
        imported = self.run_job("runner-guard", "--mic", "on")
        self.assertIn("verified: runner guard is on", imported)
        self.assertIn(", microphone enabled", imported)
        self.assertEqual(self.mic_file(), b"on")
        self.assertIn("runner guard (fixes the freeze when leaving an app): on, microphone enabled", self.status())
        self.assertIn(", microphone enabled", self.run_job("runner-guard"))  # turned on again: it stays
        self.assertNotIn("microphone enabled", self.run_job("runner-guard", "--mic", "off"))
        self.assertIsNone(self.mic_file())
        self.run_job("runner-guard", "--mic", "on", "--calm", "on")
        self.assertIn("verified: runner guard is off", self.run_job("runner-guard", "--off"))
        self.assertIsNone(self.mic_file())
        self.assertIsNone(self.calm_file())

    def test_a_microphone_file_that_does_not_write_or_go_is_reported(self):
        self.car.broken_copies.add(GUARD_MIC.lower())
        self.assertIn("failed", self.run_job("runner-guard", "--mic", "on"))
        self.assertIsNone(self.mic_file())
        self.car.broken_copies.clear()
        self.run_job("runner-guard", "--mic", "on")
        self.car.stuck_files.add(GUARD_MIC.lower())
        imported = self.run_job("runner-guard", "--mic", "off")
        self.assertIn("failed", imported)
        self.assertEqual(self.marker(imported), MIC_STUCK_ON)

    def test_mic_find_writes_find_and_reads_as_enabled(self):
        imported = self.run_job("runner-guard", "--mic", "find")
        self.assertIn(", microphone enabled", imported)
        self.assertEqual(self.mic_file(), b"find")
        self.run_job("runner-guard", "--mic", "on")
        self.assertEqual(self.mic_file(), b"on")

    def test_mic_script_passes_the_car_rules(self):
        for mic in (True, False, "find"):
            mortscript.check(guard_script(Job(SERIAL, "guard", params={"action": "enable", "mic": mic, **PARAMS})))
        with self.assertRaises(ValueError):
            guard_script(Job(SERIAL, "guard", params={"action": "disable", "mic": True, **PARAMS}))
        with self.assertRaises(ValueError):
            guard_script(Job(SERIAL, "guard", params={"action": "enable", "mic": "on", **PARAMS}))

    def test_boost_and_off_cannot_be_combined(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["job", "runner-guard", "--off", "--boost", "250", "--serial", SERIAL, "--no-pack",
                      "--work", str(self.tmp / "both")])

    def test_level_249_is_not_offered(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["job", "runner-guard", "--boost", "249", "--serial", SERIAL, "--no-pack",
                      "--work", str(self.tmp / "high")])



@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class StartCalm(unittest.TestCase):
    """The calm from s2amrun.c over a fake kernel that counts every handle by itself: Desktop.exe
    (pid 9) has threads 20 and 22 at 250 and 21 at 251; another process has thread 30 at 250."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        names = ("put_uint", "put_text", "is_blank", "read_threads", "listed_at", "note_calm", "calm_drop",
                 "calm_back", "calm_pin", "calm", "calm_end", "start_calm")
        cls.program = build(cls.work, [
            *WINDOWS, define("CALM_PATH"), define("CALM_NAME"), define("CALM_FROM"), define("CALM_LEVEL"),
            define("MAX_CALMED"), define("CALM_END_TRIES"), define("TICK_MS"), define("MAX_LISTED"),
            define("TH32CS_SNAPPROCESS"), define("TH32CS_SNAPTHREAD"), define("TH32CS_SNAPNOHEAPS"),
            "#define GENERIC_READ 0x80000000", "#define FILE_SHARE_READ 1", "#define OPEN_EXISTING 3",
            "#define FILE_ATTRIBUTE_NORMAL 0x80",
            "#ifndef WAIT_OBJECT_0\n#define WAIT_OBJECT_0 0\n#endif",
            "#ifndef WAIT_TIMEOUT\n#define WAIT_TIMEOUT 258\n#endif",
            declared(r"typedef struct \{[^}]*\} ThreadEntry;"),
            declared(r"typedef struct \{[^}]*\} Listed;"),
            declared(r"typedef struct \{(?:[^}]|\*/)*?\} Calmed;"),
            declared(r"static BOOL calm_on;"), declared(r"static Calmed calmed\[MAX_CALMED\];"),
            declared(r"static int calmed_count;"), declared(r"static DWORD calm_pid;"),
            declared(r"static HANDLE calm_process;"),
            r"""
#define OWN ((HANDLE)4000)
static const char *content;  /* the calm file's text; NULL: there is none */
static int boost_level, functions = 1, own_allowed = 1, shown = 1, refuse_back, cut, lists = 1;
static int desktop = 9, desktop_ended, moved, sets, sleeps, at, wrong;
static int ids[4] = {20, 21, 22, 30}, owners[4] = {9, 9, 9, 8}, real[4] = {250, 251, 250, 250};
static int alive[4] = {1, 1, 1, 1};
static const int first[4] = {250, 251, 250, 250};
static int held[8000];  /* open handles, each by its own value */

static HANDLE CreateFileW(const WCHAR *path, DWORD access, DWORD share, void *security, DWORD disposition,
                          DWORD attributes, HANDLE template_file)
{
    (void)path; (void)access; (void)share; (void)security; (void)disposition; (void)attributes;
    (void)template_file;
    return content ? (HANDLE)2000 : INVALID_HANDLE_VALUE;
}

static BOOL ReadFile(HANDLE file, void *buffer, DWORD size, DWORD *got, void *overlapped)
{
    (void)file; (void)overlapped;
    *got = (DWORD)strlen(content) < size ? (DWORD)strlen(content) : size;
    memcpy(buffer, content, *got);
    return TRUE;
}

static BOOL CloseHandle(HANDLE handle)
{
    long value = (long)handle;
    if (value >= 5000 && --held[value] < 0) {
        printf("closed twice %ld\n", value);
        wrong++;
    }
    return TRUE;
}

static int slot(int id)
{
    int i;
    for (i = 0; i < 4; i++)
        if (ids[i] == id)
            return i;
    return -1;
}

static DWORD WaitForSingleObject(HANDLE handle, DWORD ms)
{
    long value = (long)handle;
    (void)ms;
    if (held[value] <= 0) {
        printf("waited on a closed handle %ld\n", value);
        wrong++;
    }
    if (value >= 6000)
        return value - 6000 == 9 && desktop_ended ? WAIT_OBJECT_0 : WAIT_TIMEOUT;
    return alive[slot((int)value - 5000)] ? WAIT_TIMEOUT : WAIT_OBJECT_0;
}

static void Sleep(DWORD ms) { (void)ms; sleeps++; }
static HANDLE GetCurrentThread(void) { return OWN; }
static BOOL load_priority(void) { return functions; }

static BOOL find_process(const WCHAR *name, DWORD *pid, int *count)
{
    (void)name; (void)count;
    *pid = 0;
    if (!lists)
        return FALSE;
    *pid = (DWORD)desktop;
    if (moved)  /* the id changes hands between the first look at the list and the second */
        desktop = 8;
    return TRUE;
}

static HANDLE OpenProcess(DWORD access, BOOL inherit, DWORD pid)
{
    (void)access; (void)inherit;
    held[6000 + pid]++;
    return (HANDLE)(long)(6000 + pid);
}

static HANDLE snapshot(DWORD flags, DWORD pid)
{
    (void)flags; (void)pid;
    at = 0;
    return lists ? (HANDLE)3000 : INVALID_HANDLE_VALUE;
}

static BOOL next_thread(HANDLE list, ThreadEntry *entry)
{
    (void)list;
    while (at < 4 && !alive[at])
        at++;
    if (at >= (cut ? 2 : 4))  /* cut: the list ends early, threads 22 and 30 are missing */
        return FALSE;
    entry->th32ThreadID = (DWORD)ids[at];
    entry->th32OwnerProcessID = (DWORD)owners[at];
    entry->tpBasePri = shown ? real[at] : first[at];  /* or a list that never shows a change */
    at++;
    return TRUE;
}

static BOOL first_thread(HANDLE list, ThreadEntry *entry) { return next_thread(list, entry); }
static BOOL close_snapshot(HANDLE list) { (void)list; return TRUE; }

static HANDLE open_thread(DWORD access, BOOL inherit, DWORD id)
{
    (void)access; (void)inherit;
    held[5000 + id]++;
    return (HANDLE)(long)(5000 + id);
}

static BOOL set_priority(HANDLE thread, int priority)
{
    int id = (int)(long)thread - 5000;
    sets++;
    if (thread == OWN) {
        printf("set guard %d\n", priority);
        return own_allowed;
    }
    if (held[5000 + id] <= 0) {
        printf("set through a closed handle %d\n", id);
        wrong++;
    }
    if (!alive[slot(id)] || (priority == 250 && refuse_back > 0)) {
        if (alive[slot(id)])
            refuse_back--;
        printf("refused %d %d\n", id, priority);
        return FALSE;
    }
    printf("set %d %d\n", id, priority);
    real[slot(id)] = priority;
    return TRUE;
}

static void note(const char *event, const char *detail, unsigned long value)
{
    printf("log %s%s", event, detail ? "|" : "\n");
    if (detail)
        printf("%s%lu\n", detail, value);
}
""",
            *(function(name) for name in names),
            r"""
int main(int argc, char **argv)
{
    /* the file's text ("-": none), then flags as one word of letters (f: no thread functions,
       o: the guard's own change refused, b: the boost is on, s: the list never shows a change),
       ways back refused first, then one letter per step: a look alone, n look not alone,
       x look not alone without any list, c look alone with a list cut short, k thread 20 ends,
       d Desktop.exe ends (its threads with it), m the id changes hands during the next look,
       e the watch ends */
    const char *step;
    int i, left = 0;
    (void)argc;
    content = strcmp(argv[1], "-") ? argv[1] : NULL;
    functions = !strchr(argv[2], 'f');
    own_allowed = !strchr(argv[2], 'o');
    boost_level = strchr(argv[2], 'b') ? 251 : 0;
    shown = !strchr(argv[2], 's');
    refuse_back = atoi(argv[3]);
    start_calm();
    for (step = argv[4]; *step; step++) {
        lists = 1;
        cut = 0;
        switch (*step) {
        case 'a': calm(TRUE); break;
        case 'n': calm(FALSE); break;
        case 'x': lists = 0; calm(FALSE); break;
        case 'c': cut = 1; calm(TRUE); break;
        case 'k': alive[0] = 0; break;
        case 'd': desktop_ended = 1; alive[0] = alive[1] = alive[2] = 0; desktop = 0; break;
        case 'm': moved = 1; break;
        case 'e': calm_end(); break;
        }
    }
    for (i = 5000; i < 8000; i++)
        left += held[i];
    printf("on %d held %d wrong %d sleeps %d real %d %d %d %d\n", calm_on, left, wrong, sleeps,
           real[0], real[1], real[2], real[3]);
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_calm(self, content, steps, flags="-", refuse=0):
        return subprocess.run([str(self.program), content, flags, str(refuse), steps], capture_output=True,
                              text=True, check=True).stdout.splitlines()

    def sets(self, out):
        return sorted(line for line in out if line.startswith("set ") and "guard" not in line)

    UNTOUCHED = "wrong 0 sleeps 0 real 250 251 250 250"

    def test_without_a_valid_file_nothing_runs(self):
        for content in ("-", "250", "2520", "25", "x", "252             garbage"):
            out = self.run_calm(content, "aane")
            self.assertEqual(out[-1], "on 0 held 0 " + self.UNTOUCHED, content)
            self.assertFalse([line for line in out if line.startswith("set ")], content)

    def test_off_with_the_boost_or_without_the_functions_or_its_own_priority(self):
        for flags, why in (("b", "the boost is on"), ("f", "missing or refused"), ("o", "missing or refused")):
            out = self.run_calm("252", "aane", flags)
            self.assertEqual(out[-1], "on 0 held 0 " + self.UNTOUCHED, flags)
            self.assertTrue([line for line in out if line.startswith("log calm|off") and why in line], flags)
            self.assertFalse(self.sets(out))

    def test_the_guard_goes_above_desktop_before_anything_is_lowered(self):
        out = self.run_calm("252\r\n", "aa")
        self.assertEqual(out[0], "set guard 249")
        self.assertEqual(self.sets(out), ["set 20 252", "set 22 252"])  # once each; 21 and 30 untouched
        self.assertEqual(out[-1], "on 1 held 3 wrong 0 sleeps 0 real 252 251 252 250")  # two threads, the process

    def test_they_go_back_when_not_alone_and_every_handle_with_them(self):
        out = self.run_calm("252", "aane")
        self.assertIn("log calm|thread 20 from 252 to 250", out)
        self.assertEqual(out[-1], "on 1 held 0 " + self.UNTOUCHED)
        self.assertEqual(self.run_calm("252", "aanaane")[-1], "on 1 held 0 " + self.UNTOUCHED)  # and again

    def test_a_list_that_never_shows_the_change_changes_nothing(self):
        out = self.run_calm("252", "aaane", "s")
        self.assertEqual(self.sets(out), ["set 20 250", "set 20 252", "set 22 250", "set 22 252"])
        self.assertEqual(out[-1], "on 1 held 0 " + self.UNTOUCHED)

    def test_they_go_back_without_any_list_and_with_one_cut_short(self):
        self.assertEqual(self.run_calm("252", "axe")[-1], "on 1 held 0 " + self.UNTOUCHED)
        out = self.run_calm("252", "ac")  # thread 22 is missing from the list: it is not forgotten
        self.assertEqual(out[-1], "on 1 held 3 wrong 0 sleeps 0 real 252 251 252 250")
        self.assertEqual(self.run_calm("252", "acne")[-1], "on 1 held 0 " + self.UNTOUCHED)

    def test_a_way_back_that_fails_is_tried_on_every_look_and_logged_once(self):
        out = self.run_calm("252", "annn", refuse=4)
        self.assertEqual(len([line for line in out if "would not go back" in line]), 2)
        self.assertEqual(out[-1], "on 1 held 1 " + self.UNTOUCHED)  # only the process handle is left

    def test_the_guard_does_not_end_while_one_is_left(self):
        out = self.run_calm("252", "ae", refuse=6)  # the end itself is the first look that puts back
        self.assertEqual(out[-1], "on 1 held 0 wrong 0 sleeps 3 real 250 251 250 250")
        out = self.run_calm("252", "ae", refuse=1000)
        self.assertIn("log calm|gave up: threads of Desktop.exe left at 252 until SYNC restarts, 2", out)
        self.assertEqual(out[-1], "on 1 held 2 wrong 0 sleeps 29 real 252 251 252 250")

    def test_a_thread_or_desktop_that_ended_only_gives_its_handles_back(self):
        out = self.run_calm("252", "akane")
        self.assertEqual(out[-1], "on 1 held 0 wrong 0 sleeps 0 real 252 251 250 250")  # 20 ended at 252
        out = self.run_calm("252", "adae")
        self.assertEqual(out[-1], "on 1 held 0 wrong 0 sleeps 0 real 252 251 252 250")
        self.assertEqual(self.sets(out), ["set 20 252", "set 22 252"])

    def test_an_id_that_changes_hands_is_not_trusted(self):
        out = self.run_calm("252", "mae")  # the second look at the process list names another process
        self.assertFalse(self.sets(out))
        self.assertEqual(out[-1], "on 1 held 0 " + self.UNTOUCHED)

    def test_runs_beside_the_boost_and_ends_with_the_watch(self):
        self.assertIn("        boost(&watched, vis && scan.others == 0);\n        calm(vis && scan.others == 0);",
                      SOURCE)
        self.assertLess(SOURCE.index("    calm_end();"), SOURCE.index("CloseHandle(runner.hProcess);\n    if (guard)"))
        self.assertEqual(SOURCE.count("calm_end();"), 1)
        self.assertIn("    if (watching)\n        start_calm();", SOURCE)
        self.assertLess(SOURCE.index("        start_boost();"), SOURCE.index("        start_calm();"))
        self.assertIn("if (!calm_on)\n        return;", function("calm"))


@unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
class Microphone(unittest.TestCase):
    """start_mic() and mic_look() from s2amrun.c over a fake router: it refuses (error 4) while
    nothing records on device 0, connects (0) once something does, and answers 12 while the
    route is in place."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp())
        names = ("put_uint", "put_text", "is_blank", "mic_request", "mic_ask", "mic_find", "mic_tidy", "mic_look",
                 "mic_end", "start_mic")
        cls.program = build(cls.work, [
            *WINDOWS, define("MIC_PATH"), define("MIC_LINE"), define("MIC_DEVICE"), define("MIC_CONNECT"),
            define("MIC_HELD"), define("MIC_ASK_MS"), define("MIC_IDLE_MS"), define("MIC_NO_ANSWER"),
            define("MIC_FIND_MS"), define("MIC_FORGET"), define("MIC_NO_STREAM"), define("MIC_DEVICES"),
            define("MIC_KEPT"), "typedef int CRITICAL_SECTION;",
            "static int inside;",
            "static void InitializeCriticalSection(CRITICAL_SECTION *c) { *c = 0; }",
            "static void EnterCriticalSection(CRITICAL_SECTION *c) { (void)c; inside++; }",
            "static void LeaveCriticalSection(CRITICAL_SECTION *c) { (void)c; inside--; }",
            "#define GENERIC_READ 0x80000000", "#define FILE_SHARE_READ 1", "#define OPEN_EXISTING 3",
            "#define FILE_ATTRIBUTE_NORMAL 0x80", "#define WINAPI", "typedef void *LPVOID;", "typedef void *HMODULE;",
            "typedef unsigned int UINT;", "typedef unsigned long ULONG;",
            "typedef struct { unsigned int a; unsigned short b, c; unsigned char d[8]; } GUID;",
            declared(r"typedef DWORD \(WINAPI \*SetPropertyFn\)\([^;]*\);"),
            declared(r"typedef struct \{\s*DWORD source, source_dir, sink, sink_dir, flags;\s*\} LineConnect;"),
            declared(r"static const GUID MIC_ROUTER = [^;]*;"),
            declared(r"static SetPropertyFn set_property;"), declared(r"static volatile LONG mic_wanted;"),
            declared(r"static DWORD mic_last = MIC_NO_ANSWER;"), declared(r"static BOOL mic_finding;"),
            declared(r"static DWORD mic_found\[MIC_DEVICES\];"), declared(r"static BOOL mic_ours\[MIC_DEVICES\];"),
            declared(r"static CRITICAL_SECTION mic_lock;"), declared(r"static BOOL mic_over;"),
            r"""
#define LOOKUP(module, type, name) ((type)lookup(module, name))
static const char *content;  /* the microphone file's text; NULL: there is none */
static int has_function = 1, thread_starts = 1, recording, connected, asks, threads, broken;
static int records_on, table[14], forgets;  /* the device the app records on; junk table entries */
static int taken = -1;  /* a device somebody else has a route to already: it answers 12 */
static int many;        /* devices 7-13 all record at once */

static HANDLE CreateFileW(const WCHAR *path, DWORD access, DWORD share, void *security, DWORD disposition,
                          DWORD attributes, HANDLE template_file)
{
    (void)path; (void)access; (void)share; (void)security; (void)disposition; (void)attributes;
    (void)template_file;
    return content ? (HANDLE)2000 : INVALID_HANDLE_VALUE;
}

static BOOL ReadFile(HANDLE file, void *buffer, DWORD size, DWORD *got, void *overlapped)
{
    (void)file; (void)overlapped;
    *got = (DWORD)strlen(content) < size ? (DWORD)strlen(content) : size;
    memcpy(buffer, content, *got);
    return TRUE;
}

static BOOL CloseHandle(HANDLE handle) { (void)handle; return TRUE; }
static HMODULE LoadLibraryW(const WCHAR *name) { (void)name; return (HMODULE)1; }

static DWORD router(UINT device, const GUID *set, ULONG what, void *params, ULONG params_size, void *data,
                    ULONG size)
{
    const LineConnect *line = data;
    static const unsigned char id[16] = {0xd3, 0x20, 0xed, 0xb8, 0x4f, 0x95, 0xd8, 0x48,
                                         0x8a, 0x71, 0xd1, 0x36, 0xae, 0xb0, 0x8d, 0xb4};
    if (device != 0 || memcmp(set, id, 16) || (what != 0 && what != 7) || params || params_size || size != 20 ||
        line->source != 0x8003 || line->source_dir || line->sink > 13 || line->sink_dir || line->flags ||
        line->sink == 3 || line->sink == 4 || line->sink == 6) {
        printf("wrong request\n");
        return 11;
    }
    if (what == 7) {  /* take the entry out of the table; never asked for device 0 */
        if (line->sink == 0)
            printf("forgot the entry for device 0\n");
        table[line->sink] = 0;
        forgets++;
        return 0;
    }
    asks++;
    if (inside != 1)
        printf("asked outside the lock\n");
    if (line->sink)
        table[line->sink] = 1;  /* a connect enters the route in the table, also when it fails */
    if (broken)
        return 7;  /* a refusal of another kind */
    if ((int)line->sink == taken)
        return 12;
    if (!recording || ((int)line->sink != records_on && !(many && line->sink >= 7)))
        return 13;
    if (many && line->sink >= 7) {  /* several devices record at once */
        static int made[14];
        if (made[line->sink])
            return 12;
        made[line->sink] = 1;
        return 0;
    }
    if (connected)
        return 12;
    connected = 1;
    return 0;
}

static void *lookup(HMODULE module, const WCHAR *name)
{
    (void)module; (void)name;
    return has_function ? (void *)router : NULL;
}

static DWORD mic_thread(LPVOID unused) { (void)unused; return 0; }

static HANDLE CreateThread(void *security, DWORD stack, DWORD (*start)(LPVOID), LPVOID argument, DWORD flags,
                           DWORD *id)
{
    (void)security; (void)stack; (void)start; (void)argument; (void)flags; (void)id;
    threads++;
    return thread_starts ? (HANDLE)3000 : NULL;
}

static void note(const char *event, const char *detail, unsigned long value)
{
    printf("log %s%s", event, detail ? "|" : "\n");
    if (detail)
        printf("%s%lu\n", detail, value);
}
""",
            *(function(name) for name in names),
            r"""
int main(int argc, char **argv)
{
    /* the file's text ("-": none), flags (f: no waveInSetProperty, t: the thread does not
       start), then one letter per step: a the app starts, z it ends, r it starts recording,
       s it stops, b the router starts refusing in another way, l one look of the thread (its
       wait is printed) */
    const char *step;
    (void)argc;
    content = strcmp(argv[1], "-") ? argv[1] : NULL;
    has_function = !strchr(argv[2], 'f');
    thread_starts = !strchr(argv[2], 't');
    start_mic();
    for (step = argv[3]; *step; step++) {
        switch (*step) {
        case 'a': mic_wanted = 1; break;
        case 'z': mic_wanted = 0; recording = connected = 0; break;
        case 'r': recording = 1; break;
        case 's': recording = connected = 0; break;  /* the driver drops the route with the device */
        case 'b': broken = 1; break;
        case '5': records_on = 5; break;
        case 't': taken = 2; break;
        case 'm': many = 1; break;
        case 'e': mic_end(); break;
        case 'l':
            if (set_property)
                printf("wait %u\n", (unsigned)mic_look());
            break;
        }
    }
    {
        int k, junk = 0;
        for (k = 0; k < 14; k++)
            junk += table[k];
        if (mic_finding)
            printf("find asks %d forgets %d junk %d connected %d\n", asks, forgets, junk, connected);
        else
            printf("on %d threads %d asks %d connected %d\n", set_property != NULL, threads, asks, connected);
    }
    return 0;
}
"""])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work)

    def run_mic(self, content, steps, flags="-"):
        return subprocess.run([str(self.program), content, flags, steps], capture_output=True, text=True,
                              check=True).stdout.splitlines()

    def test_without_a_valid_file_nothing_runs(self):
        self.assertEqual(self.run_mic("-", "arlll"), ["on 0 threads 0 asks 0 connected 0"])  # not even a log line
        for content in ("off", "onn", "on      x", "1", "", "finder", "fin"):
            out = self.run_mic(content, "arlll")
            self.assertEqual(out, ["log mic|off: the microphone file holds neither on nor find",
                                   "on 0 threads 0 asks 0 connected 0"], content)

    def test_off_without_the_function_or_the_thread(self):
        self.assertEqual(self.run_mic("on", "arl", "f"), ["log mic|off: this SYNC has no waveInSetProperty",
                                                           "on 0 threads 0 asks 0 connected 0"])
        self.assertEqual(self.run_mic("on", "arl", "t"), ["log mic|off: its thread did not start",
                                                           "on 0 threads 1 asks 0 connected 0"])

    def test_asks_only_while_the_app_runs_and_connects_when_it_records(self):
        out = self.run_mic("on\r\n", "llalllrlllslllrlzl")
        self.assertNotIn("wrong request", out)
        self.assertEqual(out[0], "log mic|on: the router is asked to connect the microphone to the app's "
                                 "recording device")
        waits = [line for line in out if line.startswith("wait ")]
        # no app: nothing asked, a slow look; the app runs: four requests a second, recording or not
        self.assertEqual(waits, ["wait 1000"] * 2 + ["wait 250"] * 10 + ["wait 1000"])
        logs = [line for line in out if line.startswith("log mic|") and "on:" not in line]
        self.assertEqual(logs, ["log mic|not connected, the router answers 13",
                                "log mic|connected to recording device 0",
                                "log mic|not connected, the router answers 13",
                                "log mic|connected to recording device 0"])  # only changes
        self.assertEqual(out[-1], "on 1 threads 1 asks 10 connected 0")

    def test_a_recording_reopened_between_two_looks_is_connected_on_the_next(self):
        out = self.run_mic("on", "arllsrll")  # stopped and started again without a look in between
        logs = [line for line in out if line.startswith("log mic|") and "on:" not in line]
        self.assertEqual(logs, ["log mic|connected to recording device 0"] * 2)
        self.assertEqual(out[-1], "on 1 threads 1 asks 4 connected 1")

    def test_a_refusal_of_another_kind_is_logged_when_it_begins(self):
        out = self.run_mic("on", "alllblll")
        logs = [line for line in out if line.startswith("log mic|") and "on:" not in line]
        self.assertEqual(logs, ["log mic|not connected, the router answers 13",
                                "log mic|not connected, the router answers 7"])
        again = self.run_mic("on", "arlzlarl")  # after a look without the app, a new start logs its first answer again
        self.assertEqual(len([line for line in again if "connected to recording device" in line]), 2)

    def test_find_tries_every_device_but_three_and_leaves_no_table_entry_behind(self):
        out = self.run_mic("find\r\n", "5alllrlllslllz")
        self.assertNotIn("wrong request", out)  # never devices 3, 4, 6
        self.assertNotIn("forgot the entry for device 0", out)
        self.assertEqual(out[0], "log mic|find: the router is asked to connect the microphone to every recording "
                                 "device")
        self.assertEqual([line for line in out if line.startswith("wait ")], ["wait 500"] * 9)
        logs = [line for line in out if line.startswith("log mic|device")]
        self.assertEqual(logs, ["log mic|device 5 connected", "log mic|device 5 is closed again"])
        self.assertNotIn("asked outside the lock", out)
        # 9 rounds over 11 devices; every refused request for a device other than 0 is forgotten again
        self.assertEqual(out[-1], "find asks 99 forgets 87 junk 0 connected 0")

    def test_find_tidies_up_when_the_app_or_the_guard_ends_while_it_records(self):
        gone = self.run_mic("find", "5arllzl")  # the app ends while device 5 is connected; one idle look
        self.assertEqual(gone[-1].split(" junk ")[1], "0 connected 0")
        ended = self.run_mic("find", "5arlle")  # the guard itself ends: no look comes after
        self.assertEqual(ended[-1].split(" junk ")[1], "0 connected 1")
        after = self.run_mic("find", "5arllell")  # and the thread asks for nothing once it has
        self.assertEqual(after[-1], ended[-1])
        self.assertEqual([line for line in after if line.startswith("wait ")][-2:], ["wait 1000"] * 2)

    def test_find_keeps_at_most_three_routes_of_its_own(self):
        out = self.run_mic("find", "marlllz" + "l")
        connected = [line for line in out if line.endswith(" connected")]
        self.assertEqual(connected, ["log mic|device 0 connected", "log mic|device 7 connected",
                                     "log mic|device 8 connected", "log mic|device 9 connected"])  # 0, and three more
        self.assertEqual(out[-1].split(" junk ")[1].split()[0], "0")
        nothing = self.run_mic("find", "alll")  # the app never records: not one line per device
        self.assertFalse([line for line in nothing if line.startswith("log mic|device")])
        taken = self.run_mic("find", "talllz")  # device 2 is somebody else's: asked, logged once, entry removed
        self.assertEqual([line for line in taken if line.startswith("log mic|device")], ["log mic|device 2 answers 12"])
        self.assertEqual(taken[-1].split(" junk ")[1], "0 connected 0")
        other = self.run_mic("find", "alblz")
        self.assertEqual(len([line for line in other if " answers 7" in line]), 11)

    def test_the_thread_is_started_only_in_the_watching_instance_and_follows_the_app(self):
        self.assertIn("    if (watching)\n        start_mic();", SOURCE)
        self.assertIn("InterlockedExchange(&mic_wanted, app);", SOURCE)
        self.assertLess(SOURCE.index("InterlockedExchange(&mic_wanted, 0);"), SOURCE.index("    mic_end();"))
        self.assertLess(SOURCE.index("    mic_end();"), SOURCE.index("    calm_end();"))
        self.assertEqual(SOURCE.count("set_property("), 1)  # one way to the router, the microphone line only
        self.assertIn("line.source = MIC_LINE;", function("mic_request"))
        self.assertIn("for (;;)\n        Sleep(mic_look());", function("mic_thread"))
        append = function("append")  # two threads log now: one writer at a time
        self.assertLess(append.index("EnterCriticalSection(&log_lock);"), append.index("CreateFileW("))
        self.assertLess(append.index("CloseHandle(file);"), append.index("LeaveCriticalSection(&log_lock);"))
        self.assertLess(SOURCE.index("InitializeCriticalSection(&log_lock);"), SOURCE.index("judge_again(&rules);"))


if __name__ == "__main__":
    unittest.main()
