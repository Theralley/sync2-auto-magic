"""Fault-injection checks for the inert clock-trial model, not hardware recovery tests."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from s2am.job import Job

SPEC = importlib.util.spec_from_file_location("clock_trial_model", Path(__file__).resolve().parents[1] / "tools/clock_trial_model.py")
model = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = model
SPEC.loader.exec_module(model)


class Trial(unittest.TestCase):
    def setUp(self):
        self.plan = model.example_plan()
        self.trial = model.Trial(self.plan)

    def sample(self, now=0, target=False, **changes):
        return replace(model.Sample(now, self.plan.target if target else self.plan.baseline, 40.0), **changes)

    def start(self):
        self.trial.start(0, self.sample(), "SIMULATION:" + self.plan.digest, journal_ready=True)
        self.assertEqual(self.trial.state, "applying")

    def activate(self):
        self.start()
        self.trial.complete(100, self.trial.pending, True, self.plan.target)
        self.assertEqual(self.trial.state, "active")

    def test_selects_existing_next_point_only_within_ceiling(self):
        points = [self.plan.baseline, replace(self.plan.target, opp="sim-700", mhz=700), self.plan.target]
        self.assertEqual(model.next_point(points, self.plan.baseline, 700), self.plan.target)
        with self.assertRaises(ValueError):
            model.next_point([self.plan.baseline], self.plan.baseline, 700)
        with self.assertRaises(ValueError):
            model.next_point([self.plan.baseline, replace(self.plan.target, mhz=800)], self.plan.baseline, 700)
        with self.assertRaises(ValueError):
            model.next_point([self.plan.baseline, self.plan.target, self.plan.target], self.plan.baseline, 700)

    def test_preflight_refuses_missing_binding_baseline_telemetry_or_journal(self):
        cases = [("wrong", self.sample(), True), ("", self.sample(), True),
                 ("valid", self.sample(target=True), True), ("valid", self.sample(temp_c=None), True),
                 ("valid", self.sample(temp_c=float("nan")), True), ("valid", self.sample(temp_c=float("inf")), True),
                 ("valid", self.sample(observed_ms=1), True), ("valid", self.sample(healthy=False), True),
                 ("valid", self.sample(), False)]
        for approval, sample, journal in cases:
            with self.subTest(approval=approval, sample=sample, journal=journal):
                trial = model.Trial(self.plan)
                trial.start(0, sample, "SIMULATION:" + self.plan.digest if approval == "valid" else approval,
                            journal_ready=journal)
                self.assertEqual(trial.state, "refused")
                self.assertEqual(trial.intents, [])

    def test_deadline_set_before_apply_and_restore_requires_full_readback(self):
        self.start()
        deadline = self.trial.deadline
        self.trial.complete(100, self.trial.pending, True, self.plan.target)
        self.assertEqual(self.trial.deadline, deadline)
        self.trial.tick(deadline)
        self.assertEqual(self.trial.state, "restoring")
        self.assertEqual([i["action"] for i in self.trial.intents], ["request_target", "restore_baseline"])
        self.trial.complete(deadline + 100, self.trial.pending, True,
                            replace(self.plan.baseline, policy="wrong-policy"))
        self.assertEqual(self.trial.state, "unresolved")

    def test_success_finishes_at_original_full_state_not_target(self):
        self.activate()
        self.trial.tick(self.trial.deadline)
        self.trial.complete(self.trial.deadline + 100, self.trial.pending, True, self.plan.baseline)
        self.assertEqual(self.trial.state, "restored")
        self.assertFalse(self.trial.artifact()["deployable"])

    def test_telemetry_faults_and_cancel_request_only_one_restore(self):
        for field, value in (("temp_c", 81.0), ("temp_c", 46.0), ("temp_c", None),
                             ("healthy", False), ("journal_ok", False), ("observed_ms", -2000),
                             ("state", self.plan.baseline)):
            with self.subTest(field=field, value=value):
                self.setUp()
                self.activate()
                self.trial.observe(200, self.sample(200, target=True, **{field:value}))
                self.assertEqual(self.trial.state, "restoring")
                self.trial.cancel(201)
                self.assertEqual(len(self.trial.intents), 2)

    def test_missing_samples_and_invalid_monotonic_time_restore(self):
        for now in (2000, 50, float("nan")):
            with self.subTest(now=now):
                self.setUp()
                self.activate()
                self.trial.tick(now)
                self.assertEqual(self.trial.state, "restoring")

    def test_timed_out_apply_is_unresolved_without_concurrent_undo(self):
        self.start()
        operation = self.trial.pending
        self.trial.tick(self.plan.call_timeout_ms)
        self.assertEqual(self.trial.state, "unresolved")
        self.assertEqual(len(self.trial.intents), 1)
        self.trial.cancel(self.plan.call_timeout_ms + 1)
        self.assertEqual(len(self.trial.intents), 1)
        self.trial.complete(self.plan.call_timeout_ms + 2, operation, True, self.plan.target)
        self.assertEqual(self.trial.state, "restoring")
        self.assertEqual(len(self.trial.intents), 2)

    def test_apply_error_or_wrong_state_requests_restore_after_quiescence(self):
        for ok, state in ((False, self.plan.target), (True, self.plan.baseline)):
            with self.subTest(ok=ok):
                self.setUp()
                self.start()
                self.trial.complete(100, self.trial.pending, ok, state)
                self.assertEqual(self.trial.state, "restoring")

    def test_fault_during_apply_is_latched_until_settlement(self):
        for changes in ({"temp_c": 81.0}, {"temp_c": None}, {"temp_c": float("nan")},
                        {"temp_c": float("inf")}, {"healthy": False}, {"journal_ok": False}):
            with self.subTest(changes=changes):
                self.setUp()
                self.start()
                operation = self.trial.pending
                self.trial.observe(200, self.sample(200, target=True, **changes))
                self.assertEqual(self.trial.state, "unresolved")
                self.assertEqual(len(self.trial.intents), 1)
                self.trial.complete(250, operation, True, self.plan.target)
                self.assertEqual(self.trial.state, "restoring")
                json.dumps(self.trial.artifact(), allow_nan=False)

    def test_missing_readback_cannot_release_another_command(self):
        self.start()
        operation = self.trial.pending
        self.trial.complete(100, operation, False, None)
        self.assertEqual(self.trial.state, "unresolved")
        self.assertEqual(len(self.trial.intents), 1)
        self.trial.complete(200, operation, False, self.plan.target)
        self.assertEqual(self.trial.state, "restoring")

    def test_fresh_sample_after_silence_cannot_hide_expired_freshness(self):
        self.activate()
        self.trial.observe(2000, self.sample(2000, target=True))
        self.assertEqual(self.trial.state, "restoring")

    def test_pending_apply_freshness_is_independent_of_call_timeout(self):
        self.plan = replace(self.plan, call_timeout_ms=3000)
        self.trial = model.Trial(self.plan)
        self.start()
        operation = self.trial.pending
        self.trial.observe(2000, self.sample(2000, target=True))
        self.assertEqual(self.trial.state, "unresolved")
        self.assertEqual(len(self.trial.intents), 1)
        self.trial.complete(2100, operation, True, self.plan.target)
        self.assertEqual(self.trial.state, "restoring")

    def test_late_restore_completion_keeps_timeout_unresolved(self):
        self.activate()
        self.trial.cancel(200)
        operation = self.trial.pending
        self.trial.tick(200 + self.plan.call_timeout_ms)
        self.trial.complete(201 + self.plan.call_timeout_ms, operation, True, self.plan.baseline)
        self.assertEqual(self.trial.state, "unresolved")

    def test_failed_or_timed_out_restore_is_never_success(self):
        self.activate()
        self.trial.cancel(200)
        self.trial.complete(250, self.trial.pending, False, self.plan.baseline)
        self.assertEqual(self.trial.state, "unresolved")
        self.setUp()
        self.activate()
        self.trial.cancel(200)
        self.trial.tick(200 + self.plan.call_timeout_ms)
        self.assertEqual(self.trial.state, "unresolved")
        self.assertEqual(len(self.trial.intents), 2)

    def test_replay_and_controller_loss_cannot_reapply(self):
        self.activate()
        with self.assertRaises(ValueError):
            self.trial.start(101, self.sample(), "SIMULATION:" + self.plan.digest, journal_ready=True)
        with self.assertRaises(ValueError):
            self.trial.complete(101, "operation-1", True, self.plan.target)
        self.trial.controller_lost(200)
        self.trial.tick(50000)
        self.assertEqual(self.trial.state, "unresolved")
        self.assertEqual(len(self.trial.intents), 1)

    def test_plan_change_invalidates_binding_and_export_is_not_a_car_job(self):
        changed = replace(self.plan, evidence_digest="2" * 64)
        trial = model.Trial(changed)
        trial.start(0, model.Sample(0, changed.baseline, 40.0), "SIMULATION:" + self.plan.digest, journal_ready=True)
        self.assertEqual(trial.state, "refused")
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "output"
            model.write_examples(destination)
            plan = json.loads((destination / "trial-plan.json").read_text())
            undo = json.loads((destination / "undo-plan.json").read_text())
            self.assertEqual(undo["bound_trial_digest"], plan["trial_digest"])
            self.assertFalse(plan["deployable"])
            with self.assertRaises(ValueError):
                Job.from_json(json.dumps(plan))
            with self.assertRaises(FileExistsError):
                model.write_examples(destination)


if __name__ == "__main__":
    unittest.main()
