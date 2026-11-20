"""Focused contract tests for the S2AM-LOAD,1 raw load observer host parser.

The wire format and interpretation rules are frozen in docs/LOAD-OBSERVER-V1.md
(lead-owned). These tests build bounded synthetic journals; no device, build or
car run is involved. The parser must report observed CPU-time distribution and
coverage only -- never physical MHz, decoder identity or a causal bottleneck claim.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

from s2am import load_observer as lo

QPF = 10_000_000
SELF_PID = 100
SELF_TID = 101


def default_round(seq):
    begin = 1_000_000_000 + seq * 1_000_000_000
    end = begin + 500_000_000
    return {
        "seq": seq, "begin": begin, "end": end,
        "thread_enum_error": 0, "thread_truncated": 0,
        "process_enum_error": 0, "process_truncated": 0,
        "self": {"creation": 5000, "kernel": 1_000_000 + seq * 100_000,
                 "user": 2_000_000 + seq * 200_000,
                 "before": begin + 10_000_000, "after": begin + 20_000_000,
                 "status": "ok", "error": 0},
        "idle": {"ok": 1, "before": begin + 30_000_000, "after": begin + 40_000_000,
                 "value": 1000 + seq * 100, "error": 0},
        "processes": [(200, "AutoKit.exe")],
        "threads": [{"pid": 200, "tid": 201, "creation": 9000,
                     "kernel": 10_000_000 + seq * 1_000_000,
                     "user": 20_000_000 + seq * 2_000_000,
                     "before": begin + 50_000_000, "after": begin + 60_000_000,
                     "base": 8, "delta": 0, "status": "ok", "error": 0}],
    }


def default_rounds():
    return [default_round(seq) for seq in range(60)]


def _endround(threads):
    counts = {"ok": 0, "open_fail": 0, "times_fail": 0, "no_creation": 0}
    for thread in threads:
        counts[thread["status"]] += 1
    return {"attempted": len(threads), **counts}


def serialize_round(round_):
    seq = round_["seq"]
    lines = [
        f"round,{seq},{round_['begin']},{round_['end']},"
        f"{round_['thread_enum_error']},{round_['thread_truncated']},"
        f"{round_['process_enum_error']},{round_['process_truncated']}",
    ]
    self_ = round_["self"]
    lines.append(
        f"self,{seq},{self_['creation']},{self_['kernel']},{self_['user']},"
        f"{self_['before']},{self_['after']},{self_['status']},{self_['error']}")
    idle = round_["idle"]
    lines.append(
        f"idle,{seq},{idle['ok']},{idle['before']},{idle['after']},"
        f"{idle['value']},{idle['error']}")
    for pid, basename in round_["processes"]:
        lines.append(f"process,{seq},{pid},{basename}")
    for thread in round_["threads"]:
        lines.append(
            f"thread,{seq},{thread['pid']},{thread['tid']},{thread['creation']},"
            f"{thread['kernel']},{thread['user']},{thread['before']},{thread['after']},"
            f"{thread['base']},{thread['delta']},{thread['status']},{thread['error']}")
    end = round_.get("endround", _endround(round_["threads"]))
    lines.append(
        f"endround,{seq},{end['attempted']},{end['ok']},{end['open_fail']},"
        f"{end['times_fail']},{end['no_creation']}")
    return lines


def build(rounds=None, *, qpf=QPF, self_pid=SELF_PID, self_tid=SELF_TID,
          complete=60, header="S2AM-LOAD,1", meta=None, end_qpf=None):
    rounds = default_rounds() if rounds is None else rounds
    if meta is None:
        meta = f"meta,60,5000,512,256,{self_pid},{self_tid}"
    lines = [header, meta, f"frequency,start,{qpf}"]
    for round_ in rounds:
        lines.extend(serialize_round(round_))
    lines.append(f"frequency,end,{qpf if end_qpf is None else end_qpf}")
    lines.append(f"complete,{complete}")
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


class ParsingTests(unittest.TestCase):
    def test_valid_journal_parses(self):
        result = lo.analyze(build())
        self.assertTrue(result["complete"])
        self.assertEqual(result["qpf"], QPF)
        self.assertEqual(len(result["rounds"]), 60)

    def test_summary_flags_always_false(self):
        result = lo.analyze(build())
        for flag in ("qualified", "settled", "cpu_rate_qualified", "write_authorized"):
            self.assertFalse(result[flag])

    def test_non_ascii_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(build().replace(b"AutoKit.exe", b"\xffutoKit.exe"))

    def test_oversized_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(b"S2AM-LOAD,1\r\n" + b"x" * (8 * 1024 * 1024))

    def test_missing_final_crlf_rejected(self):
        body = build()
        with self.assertRaises(ValueError):
            lo.analyze(body[:-2])

    def test_bare_lf_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(build().replace(b"\r\n", b"\n"))

    def test_wrong_header_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(build(header="S2AM-LOAD,2"))

    def test_meta_constants_enforced(self):
        with self.assertRaises(ValueError):
            lo.analyze(build(meta=f"meta,60,5000,512,255,{SELF_PID},{SELF_TID}"))

    def test_meta_zero_self_id_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(build(meta=f"meta,60,5000,512,256,0,{SELF_TID}"))

    def test_qpf_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(build(qpf=0))
        with self.assertRaises(ValueError):
            lo.analyze(build(qpf=1_000_000_001))

    def test_qpf_start_end_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(build(end_qpf=QPF + 1))

    def test_complete_must_equal_rounds(self):
        with self.assertRaises(ValueError):
            lo.analyze(build(complete=59))

    def test_missing_round_rejected(self):
        rounds = default_rounds()
        del rounds[30]
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_reordered_rows_rejected(self):
        rounds = default_rounds()
        # idle before self violates the exact order
        round_ = rounds[0]
        lines = serialize_round(round_)
        body = build(rounds)
        swapped = body.replace(
            (lines[1] + "\r\n" + lines[2]).encode(),
            (lines[2] + "\r\n" + lines[1]).encode())
        with self.assertRaises(ValueError):
            lo.analyze(swapped)

    def test_extra_row_rejected(self):
        body = build()
        with self.assertRaises(ValueError):
            lo.analyze(body.replace(b"complete,60\r\n", b"extra,1\r\ncomplete,60\r\n"))

    def test_round_end_before_begin_rejected(self):
        rounds = default_rounds()
        rounds[0]["end"] = rounds[0]["begin"] - 1
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_successive_round_overlap_rejected(self):
        rounds = default_rounds()
        rounds[1]["begin"] = rounds[0]["end"]
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_thread_bracket_outside_round_rejected(self):
        rounds = default_rounds()
        rounds[0]["threads"][0]["after"] = rounds[0]["end"] + 1
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_ok_thread_zero_bracket_rejected(self):
        rounds = default_rounds()
        rounds[0]["threads"][0]["before"] = 0
        rounds[0]["threads"][0]["after"] = 0
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_ok_status_requires_nonzero_creation_and_zero_error(self):
        rounds = default_rounds()
        rounds[0]["threads"][0]["creation"] = 0
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))
        rounds = default_rounds()
        rounds[0]["threads"][0]["error"] = 5
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_no_creation_requires_zero_creation(self):
        rounds = default_rounds()
        thread = rounds[0]["threads"][0]
        thread["status"] = "no_creation"
        thread["creation"] = 9000
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_open_fail_requires_zero_counters(self):
        rounds = default_rounds()
        thread = rounds[0]["threads"][0]
        thread["status"] = "open_fail"
        thread["creation"] = 0
        thread["kernel"] = 1  # failures require zero creation/kernel/user
        # brackets stay valid: native brackets the whole failed read attempt
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_failed_row_zero_bracket_rejected(self):
        rounds = default_rounds()
        thread = rounds[0]["threads"][0]
        thread["status"] = "open_fail"
        thread["creation"] = 0
        thread["kernel"] = 0
        thread["user"] = 0
        thread["before"] = 0
        thread["after"] = 0
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_failed_row_valid_bracket_parses(self):
        rounds = default_rounds()
        thread = rounds[0]["threads"][0]
        thread["status"] = "times_fail"
        thread["creation"] = 0
        thread["kernel"] = 0
        thread["user"] = 0
        thread["error"] = 0  # OEM call may fail without setting an error
        result = lo.analyze(build(rounds))
        self.assertTrue(result["complete"])
        self.assertEqual(result["rounds"][0]["times_fail"], 1)

    def test_endround_counts_must_match(self):
        rounds = default_rounds()
        rounds[0]["endround"] = {"attempted": 1, "ok": 0, "open_fail": 1,
                                 "times_fail": 0, "no_creation": 0}
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_duplicate_tid_per_round_rejected(self):
        rounds = default_rounds()
        duplicate = copy.deepcopy(rounds[0]["threads"][0])
        rounds[0]["threads"].append(duplicate)
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_thread_cap_enforced(self):
        rounds = default_rounds()
        template = rounds[0]["threads"][0]
        rounds[0]["threads"] = [
            {**template, "tid": 1000 + i} for i in range(513)]
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_invalid_basename_rejected(self):
        rounds = default_rounds()
        rounds[0]["processes"] = [(200, "bad/name.exe")]
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_idle_ok_sentinel_rejected(self):
        rounds = default_rounds()
        rounds[0]["idle"]["value"] = 0xFFFFFFFF
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_idle_ok_requires_zero_error(self):
        rounds = default_rounds()
        rounds[0]["idle"]["error"] = 127
        with self.assertRaises(ValueError):
            lo.analyze(build(rounds))

    def test_non_canonical_number_rejected(self):
        body = build()
        with self.assertRaises(ValueError):
            lo.analyze(body.replace(b"thread,0,200,201", b"thread,0,0200,201"))

    def test_line_length_cap(self):
        rounds = default_rounds()
        rounds[0]["processes"] = [(200, "A" * 63)]
        # a valid 63-char basename is fine; an over-long line is not
        lo.analyze(build(rounds))
        body = build()
        long_line = b"process,0,200," + b"A" * 300 + b"\r\n"
        with self.assertRaises(ValueError):
            lo.analyze(body.replace(b"process,0,200,AutoKit.exe\r\n", long_line))


class ReadResultTests(unittest.TestCase):
    def test_read_result_accepts_load_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "LOAD.CSV"
            path.write_bytes(build())
            result = lo.read_result(path)
            self.assertTrue(result["complete"])

    def test_read_result_rejects_other_basename(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "OTHER.CSV"
            path.write_bytes(build())
            with self.assertRaises(ValueError):
                lo.read_result(path)


class InterpretationTests(unittest.TestCase):
    def test_adjacent_ok_delta_and_share_bounds(self):
        result = lo.analyze(build())
        intervals = [i for i in result["observed_intervals"]
                     if i["pid"] == 200 and i["tid"] == 201]
        self.assertEqual(len(intervals), 59)
        first = intervals[0]
        self.assertEqual(first["from_seq"], 0)
        self.assertEqual(first["to_seq"], 1)
        self.assertEqual(first["kernel_delta"], 1_000_000)
        self.assertEqual(first["user_delta"], 2_000_000)
        self.assertEqual(first["min_gap"], 990_000_000)
        self.assertEqual(first["max_gap"], 1_010_000_000)
        total = 3_000_000
        lower = Fraction(total * QPF * 100, 10_000_000 * first["max_gap"])
        upper = Fraction(total * QPF * 100, 10_000_000 * first["min_gap"])
        self.assertAlmostEqual(first["share_lower_pct"], float(lower), places=6)
        self.assertAlmostEqual(first["share_upper_pct"], float(upper), places=6)
        self.assertFalse(first["implausible"])

    def test_new_identity_baseline_only(self):
        rounds = default_rounds()
        # identity appears first at round 30 -> no interval before 30->31
        for seq in range(30):
            rounds[seq]["threads"] = []
        result = lo.analyze(build(rounds))
        intervals = [i for i in result["observed_intervals"] if i["tid"] == 201]
        self.assertEqual(len(intervals), 29)
        self.assertEqual(intervals[0]["from_seq"], 30)

    def test_missing_round_breaks_chain(self):
        rounds = default_rounds()
        rounds[30]["threads"] = []
        result = lo.analyze(build(rounds))
        intervals = [i for i in result["observed_intervals"] if i["tid"] == 201]
        pairs = {(i["from_seq"], i["to_seq"]) for i in intervals}
        self.assertNotIn((29, 30), pairs)
        self.assertNotIn((30, 31), pairs)
        self.assertIn((28, 29), pairs)
        self.assertIn((31, 32), pairs)

    def test_no_creation_breaks_chain(self):
        rounds = default_rounds()
        thread = rounds[30]["threads"][0]
        thread["status"] = "no_creation"
        thread["creation"] = 0
        result = lo.analyze(build(rounds))
        pairs = {(i["from_seq"], i["to_seq"])
                 for i in result["observed_intervals"] if i["tid"] == 201}
        self.assertNotIn((29, 30), pairs)
        self.assertNotIn((30, 31), pairs)

    def test_counter_regression_invalid_no_wrap(self):
        rounds = default_rounds()
        rounds[30]["threads"][0]["kernel"] = 1  # regression vs round 29
        result = lo.analyze(build(rounds))
        bad = [i for i in result["observed_intervals"]
               if i["tid"] == 201 and i["from_seq"] == 29]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0]["invalid"])
        self.assertIsNone(bad[0]["kernel_delta"])

    def test_tid_reuse_different_creation_separate(self):
        rounds = default_rounds()
        # round 30 reuses tid 201 with a new creation time
        rounds[30]["threads"][0]["creation"] = 99999
        rounds[30]["threads"][0]["kernel"] = 10_000_000
        rounds[30]["threads"][0]["user"] = 20_000_000
        result = lo.analyze(build(rounds))
        pairs = {(i["from_seq"], i["to_seq"])
                 for i in result["observed_intervals"] if i["tid"] == 201}
        self.assertNotIn((29, 30), pairs)
        self.assertNotIn((30, 31), pairs)  # creation changed again at 31? no: 31 has 9000
        # 30 (creation 99999) -> 31 (creation 9000) is a different identity, no chain
        self.assertIn((31, 32), pairs)

    def test_implausible_lower_bound_flagged_not_clamped(self):
        rounds = default_rounds()
        # huge CPU delta over a tiny gap -> lower bound > 100
        rounds[1]["threads"][0]["kernel"] = 10_000_000 + 10**12
        result = lo.analyze(build(rounds))
        first = [i for i in result["observed_intervals"]
                 if i["tid"] == 201 and i["from_seq"] == 0][0]
        self.assertTrue(first["implausible"])
        self.assertGreater(first["share_lower_pct"], 100.0)

    def test_idle_normal_fraction(self):
        result = lo.analyze(build())
        idle = result["idle_intervals"][0]
        self.assertEqual(idle["from_seq"], 0)
        self.assertFalse(idle["unknown"])
        # value delta 100 ms, gaps 990e6..1010e6 ticks, qpf 1e7
        lower = Fraction(100 * QPF, 1000 * idle["max_gap"])
        upper = Fraction(100 * QPF, 1000 * idle["min_gap"])
        self.assertAlmostEqual(idle["fraction_lower"], float(lower), places=9)
        self.assertAlmostEqual(idle["fraction_upper"], float(upper), places=9)

    def test_idle_regression_unknown(self):
        rounds = default_rounds()
        rounds[30]["idle"]["value"] = 1  # regression
        result = lo.analyze(build(rounds))
        bad = [i for i in result["idle_intervals"] if i["from_seq"] == 29][0]
        self.assertTrue(bad["unknown"])

    def test_idle_implausible_unknown(self):
        rounds = default_rounds()
        rounds[1]["idle"]["value"] = 1000 + 10**9  # delta*qpf > 1000*max_gap
        result = lo.analyze(build(rounds))
        bad = [i for i in result["idle_intervals"] if i["from_seq"] == 0][0]
        self.assertTrue(bad["unknown"])

    def test_self_cpu_separate_from_collection_latency(self):
        result = lo.analyze(build())
        self.assertEqual(len(result["self_intervals"]), 59)
        self.assertEqual(result["self_intervals"][0]["kernel_delta"], 100_000)
        latency = result["rounds"][0]["collection_latency_qpc"]
        self.assertEqual(latency, 500_000_000)
        self.assertNotEqual(latency, result["self_intervals"][0]["min_gap"])

    def test_no_process_share_totals(self):
        result = lo.analyze(build())
        self.assertNotIn("process_totals", result)
        for interval in result["observed_intervals"]:
            self.assertNotIn("process_share_pct", interval)

    def test_partial_counts_preserved(self):
        rounds = default_rounds()
        thread = rounds[5]["threads"][0]
        thread["status"] = "open_fail"
        thread["creation"] = 0
        thread["kernel"] = 0
        thread["user"] = 0
        # valid contained brackets retained even for a failed read attempt
        rounds[5]["thread_truncated"] = 1
        result = lo.analyze(build(rounds))
        self.assertEqual(result["rounds"][5]["open_fail"], 1)
        self.assertEqual(result["rounds"][5]["thread_truncated"], 1)
        self.assertEqual(result["partial"]["open_fail"], 1)


class TruncationTests(unittest.TestCase):
    def test_header_only_rejected(self):
        with self.assertRaises(ValueError):
            lo.analyze(b"S2AM-LOAD,1\r\n")

    def test_every_line_boundary_truncation_rejected(self):
        lines = build().decode("ascii")[:-2].split("\r\n")
        for keep in range(1, len(lines)):
            body = ("\r\n".join(lines[:keep]) + "\r\n").encode("ascii")
            with self.assertRaises(ValueError, msg=f"prefix kept {keep} lines"):
                lo.analyze(body)


class ProcessMappingTests(unittest.TestCase):
    def test_no_global_latest_process_map(self):
        result = lo.analyze(build())
        self.assertNotIn("processes", result)
        self.assertEqual(result["rounds"][0]["processes"], {200: "AutoKit.exe"})

    def test_pid_reuse_basenames_stay_per_round(self):
        rounds = default_rounds()
        rounds[30]["processes"] = [(200, "Other.exe")]
        result = lo.analyze(build(rounds))
        self.assertEqual(result["rounds"][0]["processes"][200], "AutoKit.exe")
        self.assertEqual(result["rounds"][30]["processes"][200], "Other.exe")


if __name__ == "__main__":
    unittest.main()