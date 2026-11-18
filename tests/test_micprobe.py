import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s2am import micprobe, mortscript, native  # noqa: E402
from s2am.job import MIC_WAIT, Job, mic_probe_script  # noqa: E402

SERIAL = "XV31M13H"
REPORT = "\r\n".join([
    "s2am-mic-v1",
    "wave in|devices 2",
    "in|device 0|result 0|formats 4095|channels 2|name Audio Input",
    "in|device 1|result 0|formats 0|channels 1|name ",
    "wave out|devices 1",
    "out|device 0|result 0|formats 4095|channels 2|name Audio Output",
    "mixers|devices 0",
    "open|device 99|rate 16000|channels 1", "opened|result 0", "started|result 0",
    "stopping|waited ms 3100|done 1",
    "heard|device 99|rate 16000|channels 1|bytes 96000|of 96000|first data ms 200|peak 12000|average 900"
    "|samples not zero 47000|samples above 500 20000",
    "closed|result 0",
    "open|device 99|rate 8000|channels 1", "opened|result 32",
    "open|device 0|rate 16000|channels 1", "opened|result 0", "started|result 0",
    "stopping|waited ms 5000|done 0",
    "heard|device 0|rate 16000|channels 1|bytes 0|of 96000|first data ms 0|peak 0|average 0"
    "|samples not zero 0|samples above 500 0",
    "closed|result 0",
    "open|device 1|rate 16000|channels 1", "opened|result 0", "started|result 0",
    "stopping|waited ms 3000|done 1",
    "heard|device 1|rate 16000|channels 1|bytes 96000|of 96000|first data ms 100|peak 3|average 0"
    "|samples not zero 12|samples above 500 0",
    "closed|result 0",
    "end", ""])


class Summary(unittest.TestCase):
    def report(self, text):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and None or folder.rmdir())
        if text is not None:
            (folder / "mic.txt").write_text(text)
        return folder

    def test_tells_sound_from_silence_from_nothing_and_from_refused(self):
        lines = micprobe.summary(self.report(REPORT))
        self.assertEqual(lines[0], "microphone probe: 2 recording device(s) (Audio Input, unnamed)")
        self.assertIn("  the default device at 16000 Hz: sound (peak 12000 of 32767, average 900)", lines)
        self.assertIn("  device 0 at 16000 Hz: opened, but no sound data arrived", lines)
        self.assertIn("  device 1 at 16000 Hz: data arrived, but it is silence (peak 3 of 32767)", lines)
        self.assertFalse([line for line in lines if "would not open" in line])  # it opened at 16000
        self.assertFalse([line for line in lines if "NOT complete" in line])

    def test_a_report_that_stops_early_says_so(self):
        cut = REPORT[:REPORT.index("open|device 0")]
        lines = micprobe.summary(self.report(cut))
        self.assertIn("NOT complete", lines[-1])
        self.assertEqual(len(micprobe.parse(cut)["heard"]), 1)

    def test_a_line_cut_anywhere_never_stops_the_import(self):
        whole = len(micprobe.summary(self.report(REPORT)))
        for end in range(len(REPORT)):
            lines = micprobe.summary(self.report(REPORT[:end]))
            self.assertTrue(lines)
            if end < REPORT.rindex("end"):
                self.assertTrue("NOT complete" in lines[-1] or "not a report" in lines[0], end)
            self.assertLessEqual(len(lines), whole + 1)

    def test_a_recording_that_would_not_start_is_not_called_silence(self):
        text = REPORT.replace("open|device 0|rate 16000|channels 1\r\nopened|result 0\r\nstarted|result 0\r\n"
                              "stopping|waited ms 5000", "open|device 0|rate 16000|channels 1\r\nopened|result 0"
                              "\r\nstarted|result 11\r\nstopping|waited ms 0")
        self.assertNotEqual(text, REPORT)
        lines = micprobe.summary(self.report(text))
        self.assertIn("  device 0 at 16000 Hz: opened, but recording would not start (error 11)", lines)
        self.assertFalse([line for line in lines if "device 0" in line and "no sound data" in line])
        abandoned = REPORT.replace("heard|device 1|", "abandoned|result 33\r\nignored|device 1|")
        lines = micprobe.summary(self.report(abandoned[:abandoned.index("ignored")] + "end\r\n"))
        self.assertIn("  device 1 at 16000 Hz: recorded, but the driver would not give the buffers back "
                      "(error 33)", lines)

    def test_no_report_or_another_version(self):
        self.assertIn("did not run", micprobe.summary(self.report(None))[0])
        self.assertIn("not a report", micprobe.summary(self.report("something else\r\n"))[0])

    def test_no_devices(self):
        lines = micprobe.summary(self.report("s2am-mic-v1\r\nwave in|devices 0\r\nwave out|devices 1\r\nend\r\n"))
        self.assertEqual(lines, ["microphone probe: 0 recording device(s)"])


V2 = "\r\n".join([
    "s2am-mic-v2", "wave in|devices 3",
    "in|device 0|result 0|formats 4095|channels 2|name WAV0",
    "in|device 1|result 0|formats 4095|channels 2|name WAV1",
    "in|device 2|result 0|formats 4095|channels 2|name WAV2",
    "wave out|devices 1", "out|device 0|result 0|formats 4095|channels 2|name WAV0",
    "mixers|devices 1", "mixer|device 0|result 0|destinations 1|name MIX_CS42448", "mixer open|result 0",
    "line|destination 0|result 0|id 7|type 7|sources 1|controls 1|name Record",
    "control|line 7|id 3|type 536936450|read 0|value 1|min 0|max 1|name Mic Mute",
    "source|destination 0|source 0|result 0|id 9|type 4099|controls 0|name Microphone",
    "mixer closed|result 0",
    "open|device 0|rate 16000|channels 1", "opened|result 0", "queued|device 0|result 0",
    "open|device 1|rate 16000|channels 1", "opened|result 4",
    "open|device 1|rate 8000|channels 1", "opened|result 4",
    "open|device 1|rate 44100|channels 2", "opened|result 4",
    "open|device 1|rate 48000|channels 2", "opened|result 4",
    "open|device 2|rate 16000|channels 1", "opened|result 32",
    "open|device 2|rate 8000|channels 1", "opened|result 0", "queued|device 2|result 0",
    "listening|device 0|result 0", "listening|device 2|result 0",
    "tick|second 1|0:0|2:0", "tick|second 2|0:0|2:8000",
    "heard|device 0|rate 16000|channels 1|bytes 0|of 640000|first second 0|peak 0|average 0"
    "|samples not zero 0|samples above 500 0",
    "closed|device 0|result 0",
    "heard|device 2|rate 8000|channels 1|bytes 152000|of 320000|first second 2|peak 9000|average 700"
    "|samples not zero 70000|samples above 500 30000",
    "closed|device 2|result 0",
    "end", ""])


class Listening(unittest.TestCase):
    def report(self, text):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and None or folder.rmdir())
        (folder / "mic.txt").write_text(text)
        return folder

    def test_says_which_device_carried_sound_and_from_when_and_which_is_busy(self):
        lines = micprobe.summary(self.report(V2))
        self.assertEqual(lines, [
            "microphone probe: 3 recording device(s) (WAV0, WAV1, WAV2)",
            "  device 0 at 16000 Hz: opened, but no sound data arrived",
            "  device 2 at 8000 Hz: sound (peak 9000 of 32767, average 700), from second 2",
            "  device 1: would not open in any format (in use by another program)",
            "  mixer: 1 control value(s) read; see mic.txt"])

    def test_a_device_that_would_not_start_and_a_cut_report(self):
        lines = micprobe.summary(self.report(V2.replace("listening|device 0|result 0", "listening|device 0|result 11")))
        self.assertIn("  device 0: opened, but recording would not start (error 11)", lines)
        for end in range(len(V2)):
            self.assertTrue(micprobe.summary(self.report(V2[:end])))

    def test_no_contradictions_between_queueing_starting_and_what_was_heard(self):
        partial = V2.replace("queued|device 2|result 0", "queued|device 2|result 7")
        lines = micprobe.summary(self.report(partial))
        self.assertIn("  device 2 at 8000 Hz: sound (peak 9000 of 32767, average 700), from second 2", lines)
        self.assertIn("  device 2: opened, but not all of its buffers could be queued (error 7)", lines)
        self.assertFalse([line for line in lines if "would not start" in line])
        unstarted = micprobe.summary(self.report(V2.replace("listening|device 0|result 0",
                                                            "listening|device 0|result 11")))
        self.assertFalse([line for line in unstarted if "device 0" in line and "no sound data" in line])
        cut = V2[:V2.index("listening|device 0")]  # ended before anything was heard
        lines = micprobe.summary(self.report(cut))
        self.assertFalse([line for line in lines if "device 2" in line and "would not open" in line])
        self.assertIn("  device 1: would not open in any format (in use by another program)", lines)
        unread = V2.replace("|read 0|value 1|", "|read 8|value 0|")
        self.assertFalse([line for line in micprobe.summary(self.report(unread)) if "mixer:" in line])

    def test_the_probe_listens_on_every_device_before_it_closes_any(self):
        source = (native.SOURCES / "s2ammic.c").read_text()
        body = source[source.index("static void listen_all(void)"):]
        self.assertLess(body.index("ear_open(i);"), body.index("waveInStart("))
        self.assertLess(body.index("waveInStart("), body.index("Sleep(1000);"))
        self.assertLess(body.index("Sleep(1000);"), body.index("ear_close(&ears[e]);"))
        self.assertIn("#define MAX_DEVICES 16", source)


class Script(unittest.TestCase):
    def test_runs_the_probe_and_waits_for_it_and_changes_nothing(self):
        script = mic_probe_script(Job(SERIAL, "mic"))
        mortscript.check(script)
        self.assertIn('\\s2ammic.exe", out)', script)
        self.assertLess(script.index("s2ammic.exe"), script.index(f"While (n < {MIC_WAIT})"))
        self.assertIn('If (FileExists(out & "\\mic-done.txt"))', script)
        for word in ("Delete(", "RegWrite", "Copy("):
            self.assertNotIn(word, script.split("s2ammic.exe\", out)")[1].split("mic-killed.txt")[0])
        self.assertLess(script.index("EndWhile"), script.index('If (ProcExists("s2ammic.exe"))'))
        self.assertLess(script.index('If (ProcExists("s2ammic.exe"))'), script.index('Kill("s2ammic.exe")'))

    def test_the_probe_is_a_known_program_and_only_writes_into_its_report_folder(self):
        self.assertEqual(native.PROGRAMS["s2ammic.exe"], "s2ammic.c")
        source = (native.SOURCES / "s2ammic.c").read_text()
        self.assertEqual(source.count("CreateFileW("), 1)  # every file goes through create(): folder + name
        self.assertNotIn("waveOutOpen", source)
        self.assertNotIn("mixerSetControlDetails", source)
        self.assertNotIn("RegSet", source)
        for writer in ("mixerSetControlDetails", "waveOutOpen", "waveInMessage", "SetProperty"):
            self.assertNotIn(writer, source)
        self.assertIn("TerminateProcess(GetCurrentProcess(), 4);", source)  # its own limit
        abandon = source[source.index('put("abandoned");'):]
        self.assertLess(abandon.index("return;"), abandon.index("LocalFree(ear->data);"))  # never freed there


if __name__ == "__main__":
    unittest.main()
