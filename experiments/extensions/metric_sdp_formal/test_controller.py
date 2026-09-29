"""Controller-only author checks using synthetic JSON and mocked compute.

No graph constructor, SDP model, solver, watchdog subprocess or study job runs.
Synthetic fixtures are retained under controller-author-attempts.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import uuid

from experiments.extensions.metric_sdp import run_pilot
from . import run_case, run_study

HERE = Path(__file__).resolve().parent
ARTIFACTS = Path(os.environ.get(
    "METRIC_SDP_CONTROLLER_TEST_ARTIFACT_DIR",
    str(HERE / "controller-author-attempts" / "fixtures")))


def synthetic_config():
    return {
        "source_version": "synthetic_controller_metadata_no_scientific_execution",
        "cases": [
            {"case_id": f"synthetic-{index:03d}", "stratum": "controlled",
             "family": "never_constructed", "parameters": {}, "gamma": "1",
             "original_role": "synthetic_metadata"}
            for index in range(43)
        ],
        "arms": ["U", "S", "D", "SD", "SW"],
        "solver": {"backend": "direct"},
        "formal": {"jobs": 215, "wall_seconds": 300, "rss_bytes": 6 * 1024 ** 3},
        "pilot": {"wall_seconds": 180, "rss_bytes": 6 * 1024 ** 3},
        "watchdog": {"sampling_seconds": 0.25, "initialization_limit_seconds": 60,
                     "terminate_then_kill_seconds": 2},
    }


def monitoring(exit_code=0, reason=None, rss=1024):
    return {"exit_code": exit_code, "limit_reason": reason,
            "monitored_peak_RSS_bytes": rss, "monitored_peak_RSS_GiB": rss / 1024 ** 3,
            "process_wall_seconds_including_import_input_output": 1.0}


class ControllerAuthorChecks(unittest.TestCase):
    def setUp(self):
        self.directory = ARTIFACTS / (self._testMethodName + "-" + uuid.uuid4().hex[:10])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.config = synthetic_config()
        self.config_path = self.directory / "synthetic-config.json"
        self.freeze_path = self.directory / "synthetic-freeze.json"
        self.frozen = {"status": "synthetic_not_execution_approval"}
        self.config_path.write_text(json.dumps(self.config))
        self.freeze_path.write_text(json.dumps(self.frozen))
        (self.directory / "engineering-scope.json").write_text(json.dumps({
            "scientific_measurement": False,
            "scope": "mock-only author controller engineering; no scientific execution",
        }))

    def arguments(self, output, *, worker=False, case_id="synthetic-000", arm="U"):
        args = ["--config", str(self.config_path), "--freeze", str(self.freeze_path),
                "--output", str(output)]
        return args + ["--case", case_id, "--arm", arm] if worker else args

    def read(self, path):
        return json.loads(path.read_text())

    def runtime_result(self, case_id="synthetic-000", arm="U", backend="direct",
                       status="verified_target", seconds=1.0):
        return {"case_id": case_id, "arm": arm, "backend": backend, "status": status,
                "full_compute_seconds": seconds, "scientific_measurement": False}

    def worker_call(self, output, **kwargs):
        with redirect_stdout(io.StringIO()):
            return run_case.main(self.arguments(output, worker=True, **kwargs))

    def study_call(self, output):
        with redirect_stdout(io.StringIO()):
            return run_study.main(self.arguments(output))

    def scripted_supervisor(self, statuses=None, fatal_index=None, mutate_freeze=False):
        calls = []
        def fake(command, job_dir, overlay, log):
            self.assertEqual(overlay["pilot"], self.config["formal"])
            self.assertEqual(overlay["watchdog"], self.config["watchdog"])
            self.assertNotIn("--backend", command)
            self.assertEqual(command[1:3], [
                "-m", "experiments.extensions.metric_sdp_formal.run_case"])
            index = len(calls)
            calls.append(command)
            job_dir.mkdir(parents=True, exist_ok=False)
            log.write(b"synthetic mocked controller log\n")
            case_id = command[command.index("--case") + 1]
            arm = command[command.index("--arm") + 1]
            if fatal_index == index:
                run_case.write_once(job_dir / "failure.json", {
                    "status": "worker_exception", "fatal_source_or_exactness": True,
                    "case_id": case_id, "arm": arm,
                    "exception_type": "ArithmeticError", "message": "synthetic exactness failure",
                })
                return monitoring(exit_code=2)
            status = (statuses or {}).get(index, "verified_target")
            result = self.runtime_result(case_id, arm, status=status)
            result.update(config_sha256=run_case.sha256(self.config_path),
                          freeze_sha256=run_case.sha256(self.freeze_path))
            run_case.write_once(job_dir / "result.json", result)
            if mutate_freeze and index == 0:
                self.freeze_path.write_text(json.dumps({
                    "status": "changed_synthetic_source_version"}))
            return monitoring(reason="full_wall_limit" if status == "full_wall_limit" else None)
        return fake, calls

    def test_all_215_jobs_once_and_cyclic_rotation(self):
        jobs = run_study.formal_schedule(self.config)
        self.assertEqual(len(jobs), 215)
        self.assertEqual(len({(j["case_id"], j["arm"]) for j in jobs}), 215)
        self.assertEqual([j["arm"] for j in jobs[:5]], ["U", "S", "D", "SD", "SW"])
        self.assertEqual([j["arm"] for j in jobs[5:10]], ["S", "D", "SD", "SW", "U"])
        for index in range(43):
            group = jobs[5 * index:5 * (index + 1)]
            self.assertEqual({j["arm"] for j in group}, set(run_case.ARMS))
            self.assertEqual({j["case_index"] for j in group}, {index})

    def test_unchanged_watchdog_and_formal_limits(self):
        self.assertIs(run_study.supervise, run_pilot.supervise)
        overlay = run_study.watchdog_overlay(self.config)
        self.assertEqual(overlay["pilot"]["wall_seconds"], 300)
        self.assertEqual(self.config["pilot"]["wall_seconds"], 180)
        for change in (
                lambda c: c["formal"].update(wall_seconds=180),
                lambda c: c["formal"].update(jobs=214),
                lambda c: c.update(cases=c["cases"][:-1]),
                lambda c: c["solver"].update(backend=None)):
            altered = deepcopy(self.config)
            change(altered)
            with self.assertRaises(ValueError):
                run_case.validate_inventory(altered)

    def test_worker_eligibility_before_any_loader(self):
        output = self.directory / "worker"
        with patch.object(run_case, "validate", return_value=(self.config, self.frozen)), \
                patch.object(run_case, "load_family") as family, \
                patch.object(run_case, "load_development") as development, \
                patch.object(run_case, "run_arm") as compute:
            self.assertEqual(self.worker_call(output, case_id="outside-inventory"), 2)
            family.assert_not_called()
            development.assert_not_called()
            compute.assert_not_called()
        failure = self.read(output / "failure.json")
        self.assertEqual(failure["phase"], "case_eligibility")
        self.assertTrue(failure["fatal_source_or_exactness"])
        self.assertIsNone(failure["elapsed_compute_seconds"])

    def test_worker_controlled_input_timer_backend_and_proof(self):
        output = self.directory / "worker"
        order = []
        graph = object()
        def load(*args, **kwargs):
            self.assertEqual(kwargs, {"include_oracle_blocks": False})
            self.assertFalse((output / "timer-start.json").exists())
            order.append("input")
            return graph, {"synthetic_only": True}
        proof = Mock()
        proof.to_dict.return_value = {"synthetic_exact_proof": True}
        def compute(graph_arg, case, arm, backend, config, directory, **kwargs):
            self.assertIs(graph_arg, graph)
            self.assertEqual((arm, backend), ("SW", "direct"))
            self.assertEqual(kwargs["wall_seconds"], 300)
            self.assertEqual(kwargs["started_at"],
                             self.read(output / "timer-start.json")["perf_counter"])
            self.assertTrue((output / "input.json").exists())
            order.append("compute")
            return self.runtime_result(arm="SW"), [{"interval": proof}]
        with patch.object(run_case, "validate", return_value=(self.config, self.frozen)), \
                patch.object(run_case, "load_family", side_effect=load), \
                patch.object(run_case, "load_development") as development, \
                patch.object(run_case, "run_arm", side_effect=compute):
            self.assertEqual(self.worker_call(output, arm="SW"), 0)
            development.assert_not_called()
        self.assertEqual(order, ["input", "compute"])
        self.assertTrue(self.read(output / "component-000-proof.json")["synthetic_exact_proof"])
        result = self.read(output / "result.json")
        self.assertEqual(result["config_sha256"], run_case.sha256(self.config_path))
        self.assertEqual(result["freeze_sha256"], run_case.sha256(self.freeze_path))
        self.assertTrue((output / "compute-finished.json").exists())

    def test_worker_development_loading_and_exclusive_output(self):
        self.config["cases"][0] = {"case_id": "synthetic-000", "stratum": "development",
                                  "dataset": "never_loaded", "gamma": "1"}
        output = self.directory / "worker"
        with patch.object(run_case, "validate", return_value=(self.config, self.frozen)), \
                patch.object(run_case, "load_family") as family, \
                patch.object(run_case, "load_development",
                             return_value=(object(), {"synthetic_only": True})) as development, \
                patch.object(run_case, "run_arm",
                             return_value=(self.runtime_result(arm="SD"), [])) as compute:
            self.assertEqual(self.worker_call(output, arm="SD"), 0)
            family.assert_not_called()
            development.assert_called_once_with("never_loaded")
            before = (output / "result.json").read_bytes()
            with self.assertRaises(FileExistsError):
                self.worker_call(output, arm="SD")
            self.assertEqual(compute.call_count, 1)
            self.assertEqual((output / "result.json").read_bytes(), before)

    def test_worker_source_oserror_is_fatal_before_timer(self):
        output = self.directory / "worker"
        with patch.object(run_case, "validate", side_effect=FileNotFoundError("synthetic source")), \
                patch.object(run_case, "load_family") as family:
            self.assertEqual(self.worker_call(output), 2)
            family.assert_not_called()
        self.assertTrue(self.read(output / "failure.json")["fatal_source_or_exactness"])
        self.assertFalse((output / "timer-start.json").exists())

    def test_worker_ordinary_and_exactness_failures_retained(self):
        for error, expected in ((RuntimeError("synthetic ordinary"), 1),
                                (ArithmeticError("synthetic exactness"), 2)):
            output = self.directory / f"worker-{expected}"
            with patch.object(run_case, "validate", return_value=(self.config, self.frozen)), \
                    patch.object(run_case, "load_family", return_value=(object(), {})), \
                    patch.object(run_case, "run_arm", side_effect=error):
                self.assertEqual(self.worker_call(output), expected)
            failure = self.read(output / "failure.json")
            self.assertEqual(failure["fatal_source_or_exactness"], expected == 2)
            self.assertTrue((output / "timer-start.json").exists())
            self.assertFalse((output / "result.json").exists())

    def test_parent_full_mock_schedule_retains_incomplete_denominator(self):
        output = self.directory / "study"
        fake, calls = self.scripted_supervisor({0: "full_wall_limit"})
        with patch.object(run_study, "validate",
                          return_value=(self.config, self.frozen)) as validate, \
                patch.object(run_study, "supervise", side_effect=fake):
            self.assertEqual(self.study_call(output), 0)
        self.assertEqual(len(calls), 215)
        self.assertEqual(validate.call_count, 216)
        completed = self.read(output / "study-completed.json")
        self.assertEqual(completed["summary"]["planned_jobs"], 215)
        self.assertEqual(completed["summary"]["credited_verified_target_jobs"], 214)
        self.assertEqual(completed["summary"]["unexecuted_job_count"], 0)
        self.assertFalse(completed["summary"]["runtime_ratios_computed"])
        self.assertFalse(completed["C001_or_venue_judgment"])
        self.assertTrue((output / "job-000.log").exists())
        self.assertTrue((output / "job-214-closeout.json").exists())

    def test_parent_exactness_halt_keeps_all_unexecuted_jobs(self):
        output = self.directory / "study"
        fake, calls = self.scripted_supervisor(fatal_index=2)
        with patch.object(run_study, "validate", return_value=(self.config, self.frozen)), \
                patch.object(run_study, "supervise", side_effect=fake):
            self.assertEqual(self.study_call(output), 2)
        halted = self.read(output / "study-halted.json")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(halted["retained_entries"]), 3)
        self.assertEqual(len(halted["unexecuted_jobs"]), 212)
        self.assertEqual(halted["summary"]["planned_jobs"], 215)
        self.assertEqual(sum(v["planned"] for v in halted["summary"]["per_arm"].values()), 215)
        self.assertEqual(halted["reason"], "source_or_exactness_failure")

    def test_parent_predispatch_failure_keeps_current_job_unexecuted(self):
        output = self.directory / "study"
        fake, calls = self.scripted_supervisor()
        with patch.object(run_study, "validate", side_effect=[
                (self.config, self.frozen), (self.config, self.frozen),
                ValueError("synthetic source mismatch")]), \
                patch.object(run_study, "supervise", side_effect=fake):
            self.assertEqual(self.study_call(output), 2)
        halted = self.read(output / "study-halted.json")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(halted["unexecuted_jobs"]), 214)
        self.assertEqual(halted["unexecuted_jobs"][0]["arm"], "S")
        self.assertFalse((output / "job-001.log").exists())

    def test_parent_initial_failure_retains_untrusted_full_denominator(self):
        output = self.directory / "study"
        with patch.object(run_study, "validate", side_effect=ValueError("synthetic no freeze")), \
                patch.object(run_study, "supervise") as supervise:
            self.assertEqual(self.study_call(output), 2)
            supervise.assert_not_called()
        halted = self.read(output / "study-halted.json")
        self.assertEqual(len(halted["unexecuted_jobs"]), 215)
        self.assertTrue(halted["detail"]["schedule_from_unvalidated_config"])
        self.assertEqual(halted["detail"]["fixed_unexecuted_denominator"], 215)

    def test_parent_freeze_identity_mutation_halts_even_with_mock_validate(self):
        output = self.directory / "study"
        fake, calls = self.scripted_supervisor(mutate_freeze=True)
        with patch.object(run_study, "validate", return_value=(self.config, self.frozen)), \
                patch.object(run_study, "supervise", side_effect=fake):
            self.assertEqual(self.study_call(output), 2)
        halted = self.read(output / "study-halted.json")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(halted["unexecuted_jobs"]), 214)
        self.assertIn("changed", halted["detail"]["message"])

    def test_initial_invalid_config_keeps_fixed_blocked_counts_and_unknown_ids(self):
        self.config_path.write_text("{synthetic malformed configuration")
        output = self.directory / "study"
        with patch.object(run_study, "validate", side_effect=ValueError("synthetic malformed")), \
                patch.object(run_study, "supervise") as supervise:
            self.assertEqual(self.study_call(output), 2)
            supervise.assert_not_called()
        halted = self.read(output / "study-halted.json")
        self.assertIsNone(halted["unexecuted_jobs"])
        self.assertFalse(halted["unexecuted_job_identities_known"])
        self.assertEqual(halted["summary"]["unexecuted_job_count"], 215)
        self.assertFalse(halted["summary"]["detailed_schedule_known"])
        for arm in run_case.ARMS:
            self.assertEqual(halted["summary"]["per_arm"][arm]["planned"], 43)
            self.assertEqual(halted["summary"]["per_arm"][arm]["unexecuted"], 43)

    def test_closeout_both_budgets_identity_and_nonfinite_time(self):
        job_dir = self.directory / "synthetic-job"
        job_dir.mkdir()
        job = run_study.formal_schedule(self.config)[0]
        digests = {"config": run_case.sha256(self.config_path),
                   "freeze": run_case.sha256(self.freeze_path)}
        result = self.runtime_result()
        result.update(config_sha256=digests["config"], freeze_sha256=digests["freeze"])
        path = job_dir / "result.json"
        path.write_text(json.dumps(result))
        credited, fatal = run_study.closeout(
            job, 0, monitoring(), job_dir, self.config, digests)
        self.assertTrue(credited["credited_verified_target"])
        self.assertFalse(fatal)
        rss_entry, _ = run_study.closeout(
            job, 0, monitoring(rss=self.config["formal"]["rss_bytes"] + 1),
            job_dir, self.config, digests)
        self.assertFalse(rss_entry["credited_verified_target"])
        result["full_compute_seconds"] = 301
        path.write_text(json.dumps(result))
        time_entry, _ = run_study.closeout(
            job, 0, monitoring(), job_dir, self.config, digests)
        self.assertFalse(time_entry["credited_verified_target"])
        for altered in (dict(result, full_compute_seconds=float("nan")),
                        dict(result, arm="S")):
            path.write_text(json.dumps(altered))
            with self.assertRaises(ArithmeticError):
                run_study.closeout(job, 0, monitoring(), job_dir, self.config, digests)

    def test_missing_result_not_credited_and_malformed_record_halts(self):
        job = run_study.formal_schedule(self.config)[0]
        directory = self.directory / "empty-job"
        directory.mkdir()
        digests = {"config": run_case.sha256(self.config_path),
                   "freeze": run_case.sha256(self.freeze_path)}
        entry, fatal = run_study.closeout(
            job, 0, monitoring(), directory, self.config, digests)
        self.assertEqual(entry["status"], "missing_final_result")
        self.assertFalse(entry["credited_verified_target"])
        self.assertFalse(fatal)
        output = self.directory / "study"
        def malformed(command, job_dir, overlay, log):
            job_dir.mkdir()
            (job_dir / "result.json").write_text("{incomplete")
            return monitoring()
        with patch.object(run_study, "validate", return_value=(self.config, self.frozen)), \
                patch.object(run_study, "supervise", side_effect=malformed):
            self.assertEqual(self.study_call(output), 2)
        halted = self.read(output / "study-halted.json")
        self.assertEqual(halted["retained_entries"][0]["status"],
                         "controller_record_validation_failure")
        self.assertEqual(len(halted["unexecuted_jobs"]), 214)


if __name__ == "__main__":
    unittest.main()
