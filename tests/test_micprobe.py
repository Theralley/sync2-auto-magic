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


V3 = "\r\n".join([
    "s2am-mic-v3", "route test|set property 1",
    "open|device 0|rate 16000|channels 1", "opened|result 0", "queued|device 0|result 0",
    "listening|device 0|result 0",
    "phase|seconds 3|bytes 0|buffers left 60|name as autokit finds it",
    "route|number 1|request 0|source 32771|sink 0|step connect while sync holds it", "routed|number 1|result 4",
    "phase|seconds 2|bytes 0|buffers left 60|name after asking while sync holds it",
    "route|number 2|request 1|source 0|sink 4|step take sync's route away", "routed|number 2|result 0",
    "route|number 3|request 0|source 32771|sink 0|step connect the microphone", "routed|number 3|result 0",
    "phase|seconds 6|bytes 192000|buffers left 48|name microphone borrowed",
    "route|number 4|request 1|source 0|sink 0|step take ours away", "routed|number 4|result 0",
    "route|number 5|request 0|source 36864|sink 4|step give sync its microphone back", "routed|number 5|result 0",
    "route|number 6|request 6|source 32771|sink 0|step put the table entry for device 0 back",
    "routed|number 6|result 0",
    "phase|seconds 2|bytes 0|buffers left 48|name after giving it back",
    "heard|device 0|rate 16000|channels 1|bytes 192000|of 960000|first second 0|peak 14000|average 800"
    "|samples not zero 90000|samples above 500 40000",
    "closed|device 0|result 0", "end", ""])


class Route(unittest.TestCase):
    def report(self, text):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and None or folder.rmdir())
        (folder / "mic.txt").write_text(text)
        return folder

    def test_says_each_answer_what_arrived_and_that_sync_got_it_back(self):
        self.assertEqual(micprobe.summary(self.report(V3)), [
            "microphone route test:",
            "  connect while sync holds it: refused (error 4)",
            "  take sync's route away: ok",
            "  connect the microphone: ok",
            "  take ours away: ok",
            "  give sync its microphone back: ok",
            "  put the table entry for device 0 back: ok",
            "  as autokit finds it, 3 s: 0 bytes (nothing)",
            "  after asking while sync holds it, 2 s: 0 bytes (nothing)",
            "  microphone borrowed, 6 s: 192000 bytes",
            "  after giving it back, 2 s: 0 bytes (nothing)",
            "  recording: peak 14000 of 32767, average 800",
            "  SYNC's microphone route was put back; restart SYNC anyway to be sure"])

    def test_a_way_back_that_failed_or_never_ran_is_said_loudly(self):
        refused = V3.replace("routed|number 5|result 0", "routed|number 5|result 4")
        self.assertIn("  SYNC did NOT get its microphone back: restart SYNC", micprobe.summary(self.report(refused)))
        cut = V3[:V3.index("route|number 4")]
        lines = micprobe.summary(self.report(cut))
        self.assertIn("  SYNC did NOT get its microphone back: restart SYNC", lines)
        self.assertIn("NOT complete", lines[-1])
        before = micprobe.summary(self.report(V3[:V3.index("route|number 2")]))
        self.assertFalse([line for line in before if "microphone back" in line])  # nothing was taken yet
        for end in range(len(V3)):
            self.assertTrue(micprobe.summary(self.report(V3[:end])))

    def test_an_answer_belongs_to_the_request_with_its_number(self):
        mixed = V3.replace("routed|number 5|result 0", "routed|number 4|result 0\r\nrouted|number 5|result 4")
        lines = micprobe.summary(self.report(mixed))
        self.assertIn("  give sync its microphone back: refused (error 4)", lines)
        self.assertIn("  SYNC did NOT get its microphone back: restart SYNC", lines)
        unanswered = V3.replace("routed|number 5|result 0\r\n", "")
        self.assertIn("  give sync its microphone back: no answer (the probe stopped there)",
                      micprobe.summary(self.report(unanswered)))

    def test_says_when_it_could_not_run_and_when_the_buffers_ran_out(self):
        cut = micprobe.summary(self.report("s2am-mic-v3\r\nroute test|set property"))
        self.assertFalse([line for line in cut if "no waveInSetProperty" in line])
        lines = micprobe.summary(self.report("s2am-mic-v3\r\nroute test|set property 0\r\nend\r\n"))
        self.assertIn("could not run: this SYNC has no waveInSetProperty", lines[1])
        closed = "s2am-mic-v3\r\nroute test|set property 1\r\nopen|device 0|rate 16000|channels 1\r\n" \
                 "opened|result 4\r\nend\r\n"
        self.assertIn("could not run: recording device 0 did not open", micprobe.summary(self.report(closed))[1])
        spent = V3.replace("bytes 0|buffers left 48|name after giving it back",
                           "bytes 0|buffers left 0|name after giving it back")
        self.assertIn("  after giving it back, 2 s: 0 bytes (nothing) (its buffers were used up: says nothing "
                      "about later sound)", micprobe.summary(self.report(spent)))

    def test_the_router_is_only_asked_inside_the_lock_and_given_back_on_every_way_out(self):
        source = (native.SOURCES / "s2ammic.c").read_text()
        calls = source.count("route(")  # the definition, three in give_back, one in step
        self.assertEqual(calls, 5)
        step = source[source.index("static BOOL step("):source.index("static DWORD ear_bytes")]
        self.assertLess(step.index("EnterCriticalSection(&router);"), step.index("went = !stopping;"))
        self.assertLess(step.index("touched = TRUE;"), step.index("route(name, what, source, sink);"))
        self.assertLess(step.index("borrowed = TRUE;"), step.index("route(name, what, source, sink);"))
        self.assertLess(step.index("route(name, what, source, sink);"), step.index("LeaveCriticalSection(&router);"))
        test = source[source.index("static void route_test(void)"):source.index("/* The probe's own limit")]
        tail = test[test.index("phase(\"other form borrowed\", 5);"):]
        self.assertLess(tail.index("EnterCriticalSection(&router);"), tail.index("give_back();"))
        self.assertLess(tail.index("give_back();"), tail.index("ear_close(&ears[0]);"))
        limit = source[source.index("static DWORD WINAPI limit("):source.index("static void list_devices")]
        self.assertLess(limit.index("TryEnterCriticalSection(&router)"), limit.index("stopping = TRUE;"))
        self.assertLess(limit.index("stopping = TRUE;"), limit.index("give_back();"))
        self.assertLess(limit.index("give_back();"), limit.index("TerminateProcess("))
        self.assertNotIn("LeaveCriticalSection", limit)  # it ends the process holding the router
        give = source[source.index("static void give_back(void)"):source.index("/* One step of the test")]
        self.assertLess(give.index("ROUTE_DISCONNECT, 0, STREAM_AUTOKIT"),
                        give.index("ROUTE_CONNECT, LINE_MIC_SYNC, STREAM_SYNC"))
        self.assertLess(give.index("ROUTE_CONNECT, LINE_MIC_SYNC, STREAM_SYNC"),
                        give.index("ROUTE_REMEMBER, LINE_MIC, STREAM_AUTOKIT"))
        self.assertLess(give.index("ROUTE_REMEMBER, LINE_MIC, STREAM_AUTOKIT"),
                        give.index("borrowed = touched = FALSE;"))
        self.assertIn("if (!touched)\n        return;", give)  # also after only the first, refused connect
        self.assertIn("if (borrowed)\n        route(\"give sync its microphone back\"", give)
        self.assertIn("for (h = 0; h < ear->queued; h++)", source)
        self.assertEqual(source.count("b8ed20d3"), 1)

    def test_the_job_passes_the_mode_and_says_it_is_not_read_only(self):
        script = mic_probe_script(Job(SERIAL, "mic", params={"route": True}))
        mortscript.check(script)
        self.assertIn('\\s2ammic.exe", "route|" & out)', script)
        self.assertNotIn("route|", mic_probe_script(Job(SERIAL, "mic")))
        with self.assertRaises(ValueError):
            mic_probe_script(Job(SERIAL, "mic", params={"route": "yes"}))


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
        for writer in ("mixerSetControlDetails", "waveOutOpen", "waveInMessage"):
            self.assertNotIn(writer, source)
        listening = source[:source.index("the route test:")]  # everything but the route test
        self.assertNotIn("SetProperty", listening)
        self.assertIn("if (routing) {\n        route_test();", source)
        self.assertIn("TerminateProcess(GetCurrentProcess(), 4);", source)  # its own limit
        abandon = source[source.index('put("abandoned");'):]
        self.assertLess(abandon.index("return;"), abandon.index("LocalFree(ear->data);"))  # never freed there


if __name__ == "__main__":
    unittest.main()
