"""Tests for the neon-diagnose job: its script, and reading s2amnd.exe's report."""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import cli, mortscript, native, neondiag  # noqa: E402
from s2am.fakecar import FakeCar  # noqa: E402
from s2am.job import SCRIPTS, Job, neon_diagnose_script  # noqa: E402

SERIAL = "XV31M13H"
REGISTERS = "|".join(["00012340"] * 18)


def report(stages: dict[str, tuple[str, str, list[str]]], complete: bool = True, debug: str = "1") -> str:
    """nd.txt as s2amnd.exe writes it; stages not named held (exit, 0)."""
    lines = ["S|s2am-nd-v1"]
    for number, name in enumerate(neondiag.STAGES):
        default = ("break", "dead0000", []) if name == "break" else \
            ("fault", "dead0011", ["X|80000002|00011234|00000001", "Y|00011234|f4600acf|" + REGISTERS]) \
            if name == "q128-off8" else ("exit", "00000000", [])
        how, code, extra = stages.get(name, default)
        lines += [f"G|{number}|{name}", "M|exe|00010000", *extra]
        if number == 0:
            lines.append(f"D|debug|{debug}")
        lines.append(f"Q|{number}|{name}|{how}|{code}")
    if complete:
        lines.append("T|complete")
    return "".join(line + "\r\n" for line in lines)


class Script(unittest.TestCase):
    def test_job_kind_is_available(self):
        self.assertEqual(cli.JOB_KINDS["neon-diagnose"], "neondiag")
        self.assertIs(SCRIPTS["neondiag"], neon_diagnose_script)
        self.assertIn("s2amnd.exe", native.PROGRAMS)

    def test_script_runs_the_program_and_changes_nothing_else(self):
        script = neon_diagnose_script(Job(SERIAL, "neondiag"))
        mortscript.check(script)
        self.assertRegex(script, r'RunWait\("[^"]*" & "\\s2amnd\.exe", "[^"]*" & "\\nd\.txt"\)')
        self.assertIn('out & "\\nd.txt", TRUE)', script)
        for word in ("DelTree", "Rename", "RegWrite", "Kill"):
            self.assertNotIn(word, script.split("RunWait")[1].split("Copy(")[0])

    def test_an_old_result_is_removed_before_the_run(self):
        script = neon_diagnose_script(Job(SERIAL, "neondiag"))
        self.assertLess(script.index('Delete('), script.index("RunWait("))

    def test_stage_names_match_the_program(self):
        source = (native.SOURCES / "s2amnd.c").read_text()
        table = source.split("static const Stage stages[] = {")[1].split("};")[0]
        names = tuple(line.split('"')[1] for line in table.splitlines() if '{"' in line)
        self.assertEqual(names, neondiag.STAGES)


class Summary(unittest.TestCase):
    def read(self, text: str | None) -> list[str]:
        with tempfile.TemporaryDirectory() as folder:
            if text is not None:
                (Path(folder) / "nd.txt").write_bytes(text.encode("ascii"))
            return neondiag.summary(Path(folder))

    def test_everything_held(self):
        lines = self.read(report({}))
        self.assertEqual(lines[0], "16 of 16 stages held")
        self.assertIn("faulted, as it should", lines[1])
        self.assertIn("none of the tested causes", lines[-1])

    def test_illegal_instruction_when_the_unit_is_off(self):
        fault = ["X|c000001d|00011008|00000001", "Y|00011008|f3400150|" + REGISTERS]
        lines = self.read(report({"cold-dp": ("fault", "dead0001", fault),
                                  "xfer-ls": ("fault", "dead0006", fault)}))
        text = "\n".join(lines)
        self.assertIn("14 of 16 stages held", text)
        self.assertIn("cold-dp: illegal instruction at 0x00011008, instruction f3400150", text)
        self.assertIn("floating-point unit is not already", text)
        self.assertNotIn("aligned addresses", text)
        self.assertNotIn("none of the tested causes", text)

    def test_misaligned_32_bit_elements(self):
        fault = ["X|80000002|00011040|00000001|00000000|0002a001", "Y|00011040|f4e0080f|" + REGISTERS]
        text = "\n".join(self.read(report({"ld32-off1": ("fault", "dead0009", fault)})))
        self.assertIn("ld32-off1: misaligned data at 0x00011040, instruction f4e0080f, parameters 0x0 0x2a001", text)
        self.assertIn("aligned addresses", text)
        self.assertNotIn("floating-point unit", text)

    def test_wrong_value_and_timeout_are_not_passes(self):
        text = "\n".join(self.read(report({"dp-loop": ("exit", "00000102", []),
                                           "xfer-dp": ("timeout", "dead0005", [])})))
        self.assertIn("14 of 16 stages held", text)
        self.assertIn("dp-loop: ran to the end with a wrong value (exit code 0x102)", text)
        self.assertIn("xfer-dp: no answer (timeout)", text)

    def test_a_control_without_an_answer_proves_nothing(self):
        text = "\n".join(self.read(report({"q128-off8": ("silent", "ffffffff", [])})))
        self.assertNotIn("did NOT fault", text)
        self.assertIn("no answer (silent", text)

    def test_control_that_does_not_fault_is_said(self):
        text = "\n".join(self.read(report({"q128-off8": ("exit", "00000000", [])})))
        self.assertIn("did NOT fault", text)

    def test_without_debugging(self):
        text = "\n".join(self.read(report({"break": ("exit", "00000000", []),
                                           "cold-ls": ("exit", "c000001d", [])}, debug="0")))
        self.assertIn("only exit codes", text)
        self.assertIn("cold-ls: ran to the end with a wrong value (exit code 0xc000001d)", text)

    def test_unfinished_report(self):
        text = report({}, complete=False)
        cut = text[:text.index("Q|7|")]  # the car stopped while dp-loop ran
        lines = self.read(cut)
        self.assertIn("NOT complete: it stopped during 'dp-loop'", lines[0])
        self.assertNotIn("none of the tested causes", "\n".join(lines))

    def test_a_stage_that_does_not_end_stops_the_run(self):
        text = report({"xfer-dp": ("stuck", "ffffffff", [])}, complete=False)
        cut = text[:text.index("G|6|")] + "T|stopped\r\n"
        lines = self.read(cut)
        self.assertIn("NOT complete: 'xfer-dp' did not end when told to", lines[0])
        self.assertNotIn("floating-point unit", "\n".join(lines))
        self.assertIn("xfer-dp: no answer (stuck)", "\n".join(lines))

    def test_the_report_from_the_car_of_2026_11_17_proves_nothing_about_neon(self):
        lines = self.read("S|s2am-nd-v1\r\nG|0|break\r\nM|exe|00010000\r\nX|80000003|00012ed4|00000001\r\n"
                          "Y|00012ed4|e6000010|" + REGISTERS + "\r\nD|debug|1\r\nQ|0|break|break|dead0000\r\n"
                          "G|1|cold-dp\r\nQ|1|cold-dp|stuck|ffffffff\r\nT|stopped\r\n")
        text = "\n".join(lines)
        self.assertIn("0 of 16 stages held", text)
        self.assertNotIn("points at", text)

    def test_a_stage_the_watcher_lost_counts_by_its_run_without_it(self):
        text = report({"cold-dp": ("silent", "ffffffff", []), "xfer-ls": ("lost", "ffffffff", [])})
        text = text.replace("Q|1|cold-dp|silent|ffffffff\r\n", "Q|1|cold-dp|silent|ffffffff\r\nZ|1|cold-dp|exit|00000000\r\n")
        text = text.replace("Q|6|xfer-ls|lost|ffffffff\r\n", "Q|6|xfer-ls|lost|ffffffff\r\nZ|6|xfer-ls|exit|c000001d\r\n")
        out = "\n".join(self.read(text))
        self.assertIn("the watcher got no answer for 2 (lost, silent)", out)
        self.assertIn("15 of 16 stages held", out)
        self.assertIn("xfer-ls: ran to the end with a wrong value (exit code 0xc000001d)", out)
        self.assertIn("floating-point unit", out)

    def test_a_rerun_line_without_its_stage_is_damage(self):
        self.assertIn("NOT verified", self.read("S|s2am-nd-v1\r\nZ|1|cold-dp|exit|00000000\r\n")[0])

    def test_missing_foreign_and_damaged_reports(self):
        self.assertIn("NOT verified", self.read(None)[0])
        self.assertIn("NOT verified", self.read("hello\r\n")[0])
        self.assertIn("NOT verified", self.read("S|s2am-nd-v1\r\nX|zz|1|1\r\n")[0])
        self.assertIn("NOT verified", self.read("S|s2am-nd-v1\r\n" + "G|0|break\r\n" * 60000)[0])


BUILDS = Path.home() / ".cache/sync-redesign/ffmpeg-build/install"
FILES = {"avutil-54.dll": {"size": 1, "sha256": "", "marker_rva": 0x1ffb0, "image_size": 0x70000},
         "avcodec-56.dll": {"size": 1, "sha256": "", "marker_rva": 0x1088, "image_size": 0x340000},
         "avformat-56.dll": {"size": 1, "sha256": "", "marker_rva": 0x1088, "image_size": 0x40000}}
LOADED = ["L|avutil|6715ffb0", "L|avcodec|6f681088", "L|avformat|63601088", "B|open", "B|decode"]


class Decodes(unittest.TestCase):
    def read(self, text: str, params: dict) -> str:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "nd.txt").write_bytes(text.encode("ascii"))
            return "\n".join(neondiag.summary(Path(folder), params))

    def with_decodes(self, *decodes: tuple[str, str, str, list[str]]) -> str:
        text = report({}, complete=False)
        for number, (label, how, code, lines) in enumerate(decodes, len(neondiag.STAGES)):
            text += "".join(line + "\r\n" for line in
                            [f"G|{number}|decode-{label}", "M|exe|00010000", *lines,
                             f"Q|{number}|decode-{label}|{how}|{code}"])
        return text + "T|complete\r\n"

    def test_a_decode_that_ran_is_timed_and_checked(self):
        done = [*LOADED, "P|10", "R|frames|20|width|640|height|384|sum|0000beef|decode_ms|2500"]
        params = {"sets": {"neon": FILES}, "sums": ["00000000"] * 19 + ["0000beef"]}
        text = self.read(self.with_decodes(("neon", "exit", "00000000", done)), params)
        self.assertIn("decode 'neon': 20 frames 640x384 in 2500 ms (8.0 frames a second), the right picture", text)
        self.assertNotIn("none of the tested causes", text)
        params["sums"][19] = "00000001"
        self.assertIn("but NOT the right picture", self.read(self.with_decodes(("neon", "exit", "00000000", done)),
                                                             params))
        self.assertIn("picture sum 0000beef", self.read(self.with_decodes(("neon", "exit", "00000000", done)), {}))

    def test_a_fault_is_placed_in_its_file(self):
        fault = [*LOADED, "P|10", "P|20", "X|c0000005|6f690000|00000001|00000001|0002ffec",
                 "Y|6f690000|ed2d8b10|" + REGISTERS]
        text = self.read(self.with_decodes(("neon", "fault", "dead0012", fault)), {"sets": {"neon": FILES}})
        self.assertIn("decode 'neon': access violation at 0x6f690000 (in avcodec-56.dll at +0x10000), "
                      "instruction ed2d8b10, parameters 0x1 0x2ffec, after 20 frames", text)

    def test_a_fault_outside_the_files_and_one_before_any_frame(self):
        fault = [*LOADED, "X|c000001d|00020000|00000001", "Y|none|00000005"]
        text = self.read(self.with_decodes(("installed", "fault", "dead0012", fault)), {"sets": {"neon": FILES}})
        self.assertIn("decode 'installed': illegal instruction at 0x00020000, after fewer than 10 frames", text)

    def test_a_decode_that_could_not_start(self):
        text = self.read(self.with_decodes(("neon", "exit", "00000002", ["E|load-avcodec|126"])), {})
        self.assertIn("decode 'neon': exit (code 0x2), load-avcodec|126", text)


class Plan(unittest.TestCase):
    def test_nothing_asked_nothing_added(self):
        self.assertEqual(neondiag.plan([], None), ({}, {}, []))
        with self.assertRaisesRegex(ValueError, "need at least one"):
            neondiag.plan([], Path("x"))

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as folder:
            sample = Path(folder) / "s.h264"
            sample.write_bytes(b"\0\0\0\1")
            with self.assertRaisesRegex(ValueError, "--sample"):
                neondiag.plan([f"a={folder}"], None)
            for label in ("installed", "A", "", "toolonglabel", "a/b"):
                with self.subTest(label), self.assertRaisesRegex(ValueError, "label"):
                    neondiag.plan([f"{label}={folder}"], sample)
            with self.assertRaisesRegex(ValueError, "missing"):
                neondiag.plan([f"a={folder}"], sample)
            with self.assertRaisesRegex(ValueError, "at most"):
                neondiag.plan([f"s{i}={folder}" for i in range(5)], sample)

    @unittest.skipUnless((BUILDS / "ce-neon/bin/avcodec-56.dll").is_file(), "needs the decoder builds")
    def test_real_files(self):
        with tempfile.TemporaryDirectory() as folder:
            sample, reference = Path(folder) / "s.h264", Path(folder) / "r.yuv"
            sample.write_bytes(b"\0\0\0\1\x09")
            reference.write_bytes(bytes(range(96)) * 8)  # two frames of 16x16
            sets = [f"neon={BUILDS / 'ce-neon/bin'}", f"neon={BUILDS / 'ce-default/bin'}"]
            with self.assertRaisesRegex(ValueError, "label"):
                neondiag.plan(sets, sample)
            with self.assertRaisesRegex(ValueError, "--frame"):
                neondiag.plan(sets[:1], sample, reference)
            with self.assertRaisesRegex(ValueError, "whole number"):
                neondiag.plan(sets[:1], sample, reference, "10x11")
            params, extra, payload = neondiag.plan(sets[:1], sample, reference, "16x16")
        self.assertEqual(sorted(params["sets"]["neon"]), sorted(neondiag.DLLS))
        self.assertEqual(params["sets"]["neon"]["avcodec-56.dll"]["size"], 1443328)
        self.assertEqual(params["sums"], [f"{neondiag.fnv(bytes(range(96)) * 4):08x}",
                                          f"{neondiag.fnv(bytes(range(96)) * 8):08x}"])
        self.assertEqual(list(extra), ["sample.h264"])
        self.assertEqual(sorted(car for _, car in payload),
                         sorted(f"set-neon/{name}" for name in neondiag.DLLS))

    def test_script_checks_every_file_before_it_runs(self):
        job = Job(SERIAL, "neondiag", params={"sets": {"neon": FILES}})
        script = neon_diagnose_script(job)
        mortscript.check(script)
        before = script.split("RunWait(")[0]
        for name in neondiag.DLLS:
            self.assertIn(f'\\set-neon\\{name}") <> 1)', before)
        self.assertIn('\\sample.h264"))', before)
        self.assertEqual(before.count("payload-bad.txt"), 7)
        self.assertIn('If (ProcExists("AutoKit.exe"))', before)
        self.assertNotIn("ProcExists", neon_diagnose_script(Job(SERIAL, "neondiag")))
        with self.assertRaisesRegex(ValueError, "label"):
            neon_diagnose_script(Job(SERIAL, "neondiag", params={"sets": {"../x": FILES}}))
        with self.assertRaisesRegex(ValueError, "not a decoder file"):
            neon_diagnose_script(Job(SERIAL, "neondiag", params={"sets": {"a": {"evil.dll": {"size": 1}}}}))


class Loop(unittest.TestCase):
    """The job through the command line, on a fake car."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        for patcher in (mock.patch.dict(os.environ, {"S2AM_HOME": str(self.tmp / "home")}),
                        mock.patch.object(native, "binary", lambda name: b"MZ " + name.encode())):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.upstream = self.tmp / "syncextpack"
        runner = self.upstream / "FullPack" / "RemoveExtPack"
        runner.mkdir(parents=True)
        (runner / "MortScript.exe").write_bytes(b"MZ MortScript stand-in")
        (runner / "RemoveExtPack.exe").write_bytes(b"MZ MortRunner stand-in")
        self.car = FakeCar(self.tmp / "car", SERIAL)
        self.stick = self.tmp / "stick"
        self.stick.mkdir()

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def run_job(self, *args):
        work = self.tmp / "job"
        code, built = self.cli("job", "neon-diagnose", *args, "--serial", SERIAL, "--upstream",
                               str(self.upstream), "--no-pack", "--work", str(work))
        self.assertEqual(code, 0, built)
        job = Job.from_json((work / "job.json").read_text())
        (work / "install.bin").write_bytes(b"pack")
        code, out = self.cli("stick", "prepare", str(self.stick), "--job", str(work), "--any-path")
        self.assertEqual(code, 0, out)
        self.car.insert(self.stick, work, job)
        code, imported = self.cli("stick", "import", str(self.stick), "--any-path")
        return job, work, built, imported

    def test_stages_only(self):
        self.car.nd_lines = report({}).split("\r\n")[:-1]
        job, work, built, imported = self.run_job()
        self.assertIn("changes nothing on the car", built)
        self.assertNotIn("trial decodes", built)
        self.assertIn(f"{job.id}: applied", imported)
        self.assertIn("16 of 16 stages held", imported)
        self.assertEqual((work / "payload" / job.job_dir.lstrip("/") / "s2amnd.exe").read_bytes(), b"MZ s2amnd.exe")

    def test_a_car_where_the_program_does_not_run(self):
        self.car.native_runs = False
        job, work, built, imported = self.run_job()
        self.assertIn("NOT verified: s2amnd.exe wrote nothing", imported)

    @unittest.skipUnless((BUILDS / "ce-neon/bin/avcodec-56.dll").is_file(), "needs the decoder builds")
    def test_with_trial_decodes(self):
        sample = self.tmp / "s.h264"
        sample.write_bytes(b"\0\0\0\1\x09")
        self.car.nd_lines = (report({}, complete=False) + "G|18|decode-neon\r\n" + "".join(
            line + "\r\n" for line in ["L|avcodec|6f681088", "X|c000001d|6f682088|00000001",
                                        "Q|18|decode-neon|fault|dead0012", "T|complete"])).split("\r\n")[:-1]
        job, work, built, imported = self.run_job("--decode", f"neon={BUILDS / 'ce-neon/bin'}",
                                                  "--sample", str(sample))
        self.assertIn("trial decodes: AutoKit's own files and neon", built)
        home = work / "payload" / job.job_dir.lstrip("/")
        self.assertEqual(sorted(path.name for path in (home / "set-neon").iterdir()), sorted(neondiag.DLLS))
        self.assertEqual((home / "sample.h264").read_bytes(), sample.read_bytes())
        self.assertNotIn("set-neon", "".join(job.files))  # only the job folder's own files are listed
        self.assertIn("decode 'neon': illegal instruction at 0x6f682088 (in avcodec-56.dll at +0x2088)", imported)


if __name__ == "__main__":
    unittest.main()


class Where(unittest.TestCase):
    """logger --load --where: the load logger also samples where the busiest threads are."""

    def test_the_word_reaches_the_program_only_when_asked(self):
        plain = SCRIPTS["log"](Job(SERIAL, "log", params={"load": True, "seconds": 600}))
        asked = SCRIPTS["log"](Job(SERIAL, "log", params={"load": True, "where": True, "seconds": 600}))
        mortscript.check(asked)
        self.assertIn('"600 load " & logs', plain)
        self.assertIn('"600 load where " & logs', asked)

    def test_the_program_reads_the_word(self):
        source = (native.SOURCES / "s2amdrive.c").read_text()
        self.assertIn('"<seconds> load where <folder>"', source)
        self.assertIn("sample_where(now - last_load);", source)
