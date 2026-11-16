import tempfile
import unittest
from pathlib import Path

from s2am import clock_snapshot as clock


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "clock.txt"
        self.child = {"status": "exited", "error": 0, "wait": 0,
                      "exit_valid": True, "exit": 0, "marker": True}

    def report(self):
        rows = ["S|s2am-clock-v1"]
        for pass_id, block, offset in clock.EXPECTED:
            value = {20: 0x24239180, 24: 0x2042}.get(offset, 0) if block.startswith("ccm") else 0
            rows.append(f"R|{pass_id}|{block}|{offset}|{value}")
        rows.append("T|complete")
        self.path.write_text("\n".join(rows))

    def test_exact_stable_snapshot_and_ddr_route(self):
        self.report()
        result = clock.analyze(self.path, self.child)
        self.assertTrue(result["complete"])
        self.assertTrue(result["stable"])
        self.assertEqual(result["ddr_source"], "AXI_A")
        self.assertNotIn("ddr_mhz", result)

    def test_timeout_and_nonzero_exit_cannot_be_complete(self):
        self.report()
        self.child["status"] = "timeout"
        self.assertFalse(clock.analyze(self.path, self.child)["complete"])
        self.child["status"] = "exited"
        self.child["exit"] = 1
        self.assertFalse(clock.analyze(self.path, self.child)["complete"])

    def test_changed_bracket_is_not_stable(self):
        self.report()
        self.path.write_text(self.path.read_text().replace("R|2|ccm-after|16|0", "R|2|ccm-after|16|1"))
        result = clock.analyze(self.path, self.child)
        self.assertTrue(result["complete"])
        self.assertFalse(result["stable"])
        self.assertNotIn("ddr_source", result)

    def test_missing_extra_and_duplicate_registers_fail(self):
        for edit in (lambda s:s.replace("R|1|pll1|0|0\n", ""),
                     lambda s:s.replace("T|complete", "R|1|pll1|0|0\nT|complete"),
                     lambda s:s.replace("T|complete", "R|1|pll1|4096|0\nT|complete")):
            self.report()
            self.path.write_text(edit(self.path.read_text()))
            self.assertFalse(clock.analyze(self.path, self.child)["complete"])

    def test_error_busy_and_incomplete_not_frequency_results(self):
        self.report()
        self.path.write_text(self.path.read_text().replace("T|complete", "E|map|0\nT|complete"))
        self.assertFalse(clock.analyze(self.path, self.child)["complete"])
        self.report()
        self.path.write_text(self.path.read_text().replace("|72|0", "|72|1"))
        self.assertFalse(clock.analyze(self.path, self.child)["stable"])
