"""Pure MFN transition contract tests; no hardware or recovery qualification."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "clock_transition_model", Path(__file__).resolve().parents[1] / "tools/clock_transition_model.py")
model = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = model
SPEC.loader.exec_module(model)


class Transition(unittest.TestCase):
    def setUp(self):
        self.run = model.synthetic_rehearsal()
        self.base = self.run.baseline
        self.target = replace(self.base, mfn=2)

    def observed(self, now, state=None, mhz=600, **changes):
        return replace(model.Readback(now, state or self.base, mhz), **changes)

    def start(self):
        self.run.start(0, self.observed(0), journal_ready=True)
        self.assertEqual(self.run.pending.action, "stage_target_mfn")

    def stage(self):
        self.start()
        self.run.complete(10, self.run.pending.id, settled=True,
                          observed=self.observed(10, self.target))
        self.assertEqual(self.run.pending.action, "request_target_load")

    def activate(self):
        self.stage()
        self.run.complete(20, self.run.pending.id, settled=True,
                          observed=self.observed(20, self.target, 624))
        self.assertEqual(self.run.state, "active")

    def test_current_candidate_is_blocked_and_not_an_installable_job(self):
        spec = model.candidate_spec()
        self.assertEqual(spec["state"], "blocked")
        self.assertEqual(set(spec["unresolved"]), set(model.REQUIREMENTS))
        self.assertFalse(spec["deployable"])
        self.assertEqual(spec["candidate_nominal_mhz"], 624)
        self.assertEqual(spec["operations"], [])
        from s2am.job import Job
        with self.assertRaises(ValueError):
            Job.from_json(json.dumps(spec))

    def test_every_unknown_missing_or_unmet_prerequisite_refuses_before_staging(self):
        for name in model.REQUIREMENTS:
            for value in (None, "unknown", "unmet"):
                with self.subTest(name=name, value=value):
                    evidence = dict(self.run.evidence)
                    if value is None:
                        del evidence[name]
                    else:
                        evidence[name] = value
                    run = model.synthetic_rehearsal(evidence)
                    run.start(0, self.observed(0), journal_ready=True)
                    self.assertEqual(run.state, "refused")
                    self.assertEqual(run.operations, [])

    def test_invalid_preflight_journal_or_full_baseline_refuses(self):
        for observed, journal in ((self.observed(0), False),
                                  (self.observed(0, replace(self.base, bank="hfs")), True),
                                  (self.observed(0, load_pending=True), True),
                                  (self.observed(0, measured_mhz=None), True)):
            run = model.synthetic_rehearsal()
            run.start(0, observed, journal_ready=journal)
            self.assertEqual(run.state, "refused")
            self.assertEqual(run.operations, [])

    def test_target_then_restore_changes_only_owned_mfn_and_preserves_full_state(self):
        self.activate()
        self.run.restore(30, self.observed(30, self.target, 624), journal_ready=True)
        self.run.complete(40, self.run.pending.id, settled=True,
                          observed=self.observed(40, self.base, 624))
        self.run.complete(50, self.run.pending.id, settled=True, observed=self.observed(50))
        self.assertEqual(self.run.state, "restored")
        self.assertEqual([op.action for op in self.run.operations],
                         ["stage_target_mfn", "request_target_load",
                          "stage_baseline_mfn", "request_baseline_load"])
        self.assertEqual([op.owned_fields for op in self.run.operations],
                         [("active_mfn",), ("load_request",), ("active_mfn",), ("load_request",)])
        self.assertFalse(self.run.artifact()["deployable"])

    def test_wrong_order_duplicate_completion_and_replay_do_not_emit_operations(self):
        with self.assertRaises(ValueError):
            self.run.restore(0, self.observed(0), journal_ready=True)
        self.start()
        with self.assertRaises(ValueError):
            self.run.complete(1, "unissued-operation", settled=True, observed=self.observed(1))
        with self.assertRaises(ValueError):
            self.run.start(1, self.observed(1), journal_ready=True)
        self.run.complete(10, self.run.pending.id, settled=True,
                          observed=self.observed(10, self.target))
        with self.assertRaises(ValueError):
            self.run.complete(11, "operation-1", settled=True, observed=self.observed(11))
        self.assertEqual(len(self.run.operations), 2)

    def test_missing_ack_or_readback_cannot_release_pending_load_or_start_undo(self):
        for changes in ({"settled": False}, {"observed": None},
                        {"observed": self.observed(21, self.target, 624, load_pending=True)},
                        {"observed": self.observed(21, self.target, None)}):
            self.setUp()
            self.stage()
            pending = self.run.pending.id
            args = {"settled": True, "observed": self.observed(21, self.target, 624), **changes}
            self.run.complete(21, pending, **args)
            self.assertEqual(self.run.state, "unresolved")
            self.assertEqual(self.run.pending.id, pending)
            with self.assertRaises(ValueError):
                self.run.restore(22, self.observed(22, self.target, 624), journal_ready=True)
            self.assertEqual(len(self.run.operations), 2)

    def test_sticky_lock_flag_alone_never_establishes_target(self):
        self.stage()
        self.run.complete(20, self.run.pending.id, settled=True,
                          observed=self.observed(20, self.target, None, lock_flag=True))
        self.assertEqual(self.run.state, "unresolved")
        self.assertIsNotNone(self.run.pending)

    def test_not_locked_or_untyped_lock_flag_refuses_baseline_and_completion(self):
        for flag in (False, None, 1):
            with self.subTest(flag=flag):
                self.setUp()
                self.run.start(0, self.observed(0, lock_flag=flag), journal_ready=True)
                self.assertEqual(self.run.state, "refused")
                self.assertEqual(self.run.operations, [])
                self.setUp()
                self.stage()
                self.run.complete(20, self.run.pending.id, settled=True,
                                  observed=self.observed(20, self.target, 624, lock_flag=flag))
                self.assertEqual(self.run.state, "unresolved")
                self.assertIsNotNone(self.run.pending)

    def test_timeout_is_pending_until_observed_settlement_then_requires_explicit_restore(self):
        self.stage()
        operation = self.run.pending.id
        self.run.tick(110)
        self.assertEqual(self.run.state, "unresolved")
        self.assertEqual(len(self.run.operations), 2)
        self.run.complete(111, operation, settled=True, observed=self.observed(111, self.target, 624))
        self.assertEqual(self.run.state, "restore_required")
        self.assertIsNone(self.run.pending)
        self.assertEqual(len(self.run.operations), 2)
        self.run.restore(112, self.observed(112, self.target, 624), journal_ready=True)
        self.assertEqual(self.run.pending.action, "stage_baseline_mfn")

    def test_fault_after_staging_does_not_claim_unchanged_or_issue_load_request(self):
        self.start()
        self.run.fault(5, "journal-failed")
        self.run.complete(10, self.run.pending.id, settled=True,
                          observed=self.observed(10, self.target))
        self.assertEqual(self.run.state, "restore_required")
        self.assertEqual(len(self.run.operations), 1)
        self.assertEqual(self.run.last_observed.state.mfn, 2)
        self.run.restore(11, self.observed(11, self.target), journal_ready=True)
        self.assertEqual(self.run.pending.action, "stage_baseline_mfn")

    def test_bank_policy_or_other_state_change_keeps_recovery_unresolved(self):
        for change in ({"bank": "hfs"}, {"policy": "another-owner"}, {"mfd": 4},
                       {"ddr_source": "pll1"}, {"rail": "different-rail"}):
            self.setUp()
            self.stage()
            self.run.complete(20, self.run.pending.id, settled=True,
                              observed=self.observed(20, replace(self.target, **change), 624))
            self.assertEqual(self.run.state, "unresolved")
            self.assertEqual(len(self.run.operations), 2)
            with self.assertRaises(ValueError):
                self.run.restore(21, self.observed(21, self.target, 624), journal_ready=True)

    def test_stale_future_or_late_restore_observation_cannot_report_restored(self):
        for observed_ms, completed_at in ((0, 50), (51, 50), (140, 140)):
            self.setUp()
            self.activate()
            self.run.restore(30, self.observed(30, self.target, 624), journal_ready=True)
            self.run.complete(40, self.run.pending.id, settled=True,
                              observed=self.observed(40, self.base, 624))
            self.run.complete(completed_at, self.run.pending.id, settled=True,
                              observed=self.observed(observed_ms))
            self.assertEqual(self.run.state, "unresolved")

    def test_restoration_mismatch_requires_full_baseline_not_only_600_mhz(self):
        self.activate()
        self.run.restore(30, self.observed(30, self.target, 624), journal_ready=True)
        self.run.complete(40, self.run.pending.id, settled=True,
                          observed=self.observed(40, self.base, 624))
        self.run.complete(50, self.run.pending.id, settled=True,
                          observed=self.observed(50, replace(self.base, suspend="wrong-state")))
        self.assertEqual(self.run.state, "unresolved")

    def test_controller_loss_preserves_ambiguous_staging_without_retry(self):
        self.start()
        self.run.controller_lost(1)
        self.run.tick(1000)
        self.assertEqual(self.run.state, "unresolved")
        self.assertEqual(len(self.run.operations), 1)
        with self.assertRaises(ValueError):
            self.run.complete(1001, self.run.pending.id, settled=True,
                              observed=self.observed(1001, self.target))

    def test_exports_new_directory_with_blocked_spec_and_non_deployable_traces(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "model"
            model.write_examples(out)
            candidate = json.loads((out / "candidate-spec.json").read_text())
            self.assertEqual(candidate["state"], "blocked")
            traces = [json.loads(path.read_text()) for path in out.glob("trace-*.json")]
            self.assertGreaterEqual(len(traces), 4)
            self.assertTrue(all(trace["mode"] == "simulation_only" and not trace["deployable"]
                                for trace in traces))
            with self.assertRaises(FileExistsError):
                model.write_examples(out)


if __name__ == "__main__":
    unittest.main()
