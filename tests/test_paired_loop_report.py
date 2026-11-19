"""Offline checks for the paired timing report; no hardware clock claims."""
import tempfile
import unittest
from pathlib import Path

from tools.paired_loop_report import analyze, read_result


def capture(effects=(5,) * 8, extra=None, start=101):
    lines = ["S2AM-PAIR,1", "qpf,1000000"]
    for block, effect in enumerate(effects):
        n = 16384 if block < 4 else 32768
        widths = (32, 64, 64, 32) if block % 2 == 0 else (64, 32, 32, 64)
        for slot, width in enumerate(widths):
            # Fixed overhead + linear drift in slot; ABBA should cancel both.
            ticks = n * (8 + (effect if width == 64 else 0)) + 25 + 3 * slot
            ticks += (extra or {}).get((block, slot), 0)
            end = start + ticks
            lines.append(f"sample,{block},{slot},{n},{width},{start},{end}")
            start = end + 17
    lines.append("complete,32")
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


class PairedLoopReport(unittest.TestCase):
    def test_coherent_proxy_cancels_overhead_and_linear_drift(self):
        result = analyze(capture(start=2**63))
        self.assertEqual([b["extra_ticks_per_round"] for b in result["blocks"]], [5] * 8)
        self.assertEqual((result["order_delta"], result["size_delta"]), (0, 0))
        self.assertEqual(result["status"], "coherent")
        self.assertIs(result["qualified"], False)

    def test_read_only_published_file(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder) / "RESULT.TMP"
            tmp.write_bytes(capture())
            with self.assertRaises(ValueError):
                read_result(tmp)
            final = tmp.rename(tmp.with_name("RESULT.CSV"))
            self.assertEqual(read_result(final)["status"], "coherent")

    def test_order_dependence_is_noisy(self):
        result = analyze(capture((5, 7) * 4))
        self.assertEqual((result["order_delta"], result["size_delta"]), (2, 0))
        self.assertEqual(result["status"], "noisy")

    def test_size_dependence_is_noisy(self):
        result = analyze(capture((5,) * 4 + (7,) * 4))
        self.assertEqual((result["order_delta"], result["size_delta"]), (0, 2))
        self.assertEqual(result["status"], "noisy")

    def test_slow_single_window_is_not_discarded(self):
        result = analyze(capture(extra={(6, 1): 2 * 32768 * 20}))
        effects = [b["extra_ticks_per_round"] for b in result["blocks"]]
        self.assertEqual(effects, [5, 5, 5, 5, 5, 5, 25, 5])
        self.assertEqual(result["status"], "noisy")

    def test_nonpositive_effect_is_not_evidence(self):
        for effect in (0, -3):
            with self.subTest(effect=effect):
                result = analyze(capture((5,) * 7 + (effect,)))
                self.assertEqual(result["status"], "nonpositive")
                self.assertIs(result["qualified"], False)

    def test_incomplete_extra_or_non_ascii_records_are_rejected(self):
        body = capture()
        for bad in (body[:-14], body.replace(b"complete,32", b"complete,31"),
                    body + b"ignored\r\n", body.replace(b"\r\n", b"\n"),
                    body.replace(b"S2AM-PAIR,1", b"S2AM-PAIR,2"), b"\xff" + body):
            with self.subTest(tail=bad[-32:]), self.assertRaises(ValueError):
                analyze(bad)

    def test_tampered_schedule_is_rejected(self):
        body = capture()
        old = b"sample,0,0,16384,32,"
        for replacement in (b"sample,1,0,16384,32,", b"sample,0,1,16384,32,",
                            b"sample,0,0,32768,32,", b"sample,0,0,16384,64,"):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                analyze(body.replace(old, replacement, 1))

    def test_invalid_timer_fields_are_rejected(self):
        body = capture()
        old = b"sample,0,0,16384,32,101,131198"
        self.assertIn(old, body)
        for before, after in ((0, 131198), (101, 101), (101, 99), (-1, 131198),
                              (101, 2**64), (101, 131216)):
            new = f"sample,0,0,16384,32,{before},{after}".encode("ascii")
            with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                analyze(body.replace(old, new, 1))

    def test_frequency_requires_positive_unsigned_integer(self):
        body = capture()
        for bad in (b"0", b"-1", b"1.5", str(2**64).encode()):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                analyze(body.replace(b"qpf,1000000", b"qpf," + bad))
