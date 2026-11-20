"""Small CLI summary checks; mock only the parser boundary."""
import contextlib
import io
import json
import unittest
from unittest import mock
from tools import load_observer_report as report


class Report(unittest.TestCase):
    def test_reports_latency_separately_from_accounted_self_cpu(self):
        capture={"qpf":8000000,"rounds":[{"collection_latency_qpc":8000}],
                 "self_intervals":[{"invalid":False,"implausible":False,"share_upper_pct":2.0}],
                 "observed_intervals":[],"partial":{"times_fail":1}}
        out=io.StringIO()
        with mock.patch.object(report,"read_result",return_value=capture),contextlib.redirect_stdout(out):
            self.assertEqual(report.main(["LOAD.CSV"]),0)
        result=json.loads(out.getvalue())
        self.assertEqual(result["max_collection_elapsed_ms"],1)
        self.assertEqual(result["max_sampler_accounted_cpu_upper_pct"],2)
        self.assertFalse(result["write_authorized"])
        self.assertEqual(result["partial"]["times_fail"],1)

    def test_unknown_self_cpu_is_not_reported_as_zero(self):
        capture={"qpf":1,"rounds":[],"self_intervals":[],"observed_intervals":[],"partial":{}}
        out=io.StringIO()
        with mock.patch.object(report,"read_result",return_value=capture),contextlib.redirect_stdout(out):
            self.assertEqual(report.main(["LOAD.CSV"]),0)
        self.assertIsNone(json.loads(out.getvalue())["max_sampler_accounted_cpu_upper_pct"])

    def test_invalid_capture_is_clear_failure(self):
        err=io.StringIO()
        with mock.patch.object(report,"read_result",side_effect=ValueError("incomplete")),contextlib.redirect_stderr(err):
            self.assertEqual(report.main(["LOAD.CSV"]),1)
        self.assertIn("incomplete",err.getvalue())
