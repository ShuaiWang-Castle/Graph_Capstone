"""Two metadata-only contract fixtures; no CSR decoding, graphs or solver.

Synthetic approvals exercise the parser contract, not mathematical proof.
Every mock project/attempt remains under this assigned namespace.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
import uuid

from . import collect as c


HERE = Path(__file__).resolve().parent


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(c.json_bytes(value))


class MockProject:
    def __init__(self):
        self.root = HERE / "author-attempt-fixtures" / uuid.uuid4().hex[:12]
        self.root.mkdir(parents=True)
        self.contract = c.read_json(HERE / "fixed-contract.json")
        self.config = self.root / self.contract["config_path"]
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes((c.ROOT / self.contract["config_path"]).read_bytes())
        for path in c.RUNTIME_PATHS:
            dest = self.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((c.ROOT / path).read_bytes())
        required = {}
        for path in (*c.SOURCES, c.CONTRACT, c.OPERATOR):
            dest = self.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((c.ROOT / path).read_bytes())
            required[path] = c.sha256(dest)
        packet = {"schema": "metric-sdp-formal-prospective-analysis-manifest-v1",
                  "scientific_execution_performed": False,
                  "config_sha256": c.sha256(self.config),
                  "collector_source_sha256": c.source_sha256(),
                  "required_artifact_sha256": required}
        save(self.root / c.PACKET, packet)
        required[c.PACKET] = c.sha256(self.root / c.PACKET)
        self.freeze = self.root / "mock-freeze.json"
        save(self.freeze, {"status": "frozen_for_once_43x5_metric_sdp_comparison",
              "formal_execution_approved": True, "configuration_freeze_blockers": [],
              "config_sha256": c.sha256(self.config),
              "runtime_source_sha256": {p: c.sha256(self.root / p) for p in c.RUNTIME_PATHS},
              "required_artifact_sha256": required, "environment": {"synthetic_metadata_only": True},
              "planned_scientific_output": "mock-run"})
        self.run = self.root / "mock-run"
        self.run.mkdir()
        self.jobs = c.fixed_schedule(self.contract)
        save(self.run / "study-started.json", {"jobs": self.jobs, "planned_jobs": 215,
             "config_sha256": c.sha256(self.config), "freeze_sha256": c.sha256(self.freeze)})

    def collect(self, audit=None):
        return c.collect(self.root, self.config, self.freeze, self.run,
             expected_config_sha256=c.sha256(self.config), expected_freeze_sha256=c.sha256(self.freeze),
             exactness_audit=audit, expected_exactness_audit_sha256=c.sha256(audit) if audit else None)

    def completed_metadata(self):
        entries = []
        for index, job in enumerate(self.jobs):
            (self.run / f"job-{index:03d}.log").write_text("synthetic metadata fixture; no worker executed\n")
            entry = {**job, "index": index, "status": "synthetic_unresolved",
                     "credited_verified_target": False, "full_compute_seconds": None,
                     "exit_code": 1, "monitored_peak_RSS_bytes": 1,
                     "limit_reason": None, "process_wall_seconds_including_import_input_output": 3,
                     "result_sha256": None, "failure_sha256": None, "failure": None}
            if job["case_index"] == 0 and job["arm"] in {"S", "SD", "SW"}:
                directory = self.run / f"job-{index:03d}-{job['case_id']}-{job['arm']}"
                directory.mkdir()
                case = self.contract["cases"][0]
                save(directory / "input.json", {"case": case, "arm": job["arm"], "backend": job["backend"],
                     "config_sha256": c.sha256(self.config), "freeze_sha256": c.sha256(self.freeze),
                     "metadata": {"synthetic_metadata_only": True}})
                (directory / "original-adjacency.npz").write_bytes(b"synthetic placeholder; never decoded as a graph")
                bank = {"blocks": [], "discovery_labels": [0, 1]}
                original = {"case_id": case["case_id"], "arm": job["arm"], "backend": job["backend"],
                    "original_n": 2, "gamma_exact": case["gamma"], "S_exact": "2", "degrees_exact": ["1", "1"],
                    "original_fingerprint": "synthetic-fingerprint", "original_csr_sha256": c.sha256(directory / "original-adjacency.npz"),
                    "bank": bank, "bank_sha256": c.canonical_hash(bank), "incumbent_Q_exact": "0",
                    "stage": "before_any_composition"}
                save(directory / "original-preparation.json", original)
                pre = {k: v for k, v in original.items() if k not in {"degrees_exact", "stage"}}
                pre.update(quotient_n=2, membership=[0, 1], status="in_progress", components=[],
                    composition_checkpoint_files=[], composition={"operations": [], "metadata": {
                        "phases": [{"fixed_point": True}], "progress_callback_seconds": 0,
                        "stage_seconds": {"progress_callback": 0}}})
                save(directory / "preprocessing.json", pre)
                full = {"S": 2, "SD": 1, "SW": 0}[job["arm"]]
                result = {**pre, "config_sha256": c.sha256(self.config), "freeze_sha256": c.sha256(self.freeze),
                    "status": "verified_target", "full_compute_seconds": full,
                    "stage_seconds": {"safe_composition": 0}, "accounted_stage_seconds": 0,
                    "unassigned_compute_seconds": full, "lower_exact": "1/2", "upper_exact": "1/2", "width_exact": "0",
                    "components": [{"index": 0, "analytic": True, "lower_exact": "1/4", "upper_exact": "1/4"},
                                   {"index": 1, "analytic": True, "lower_exact": "1/4", "upper_exact": "1/4"}]}
                save(directory / "result.json", result)
                save(directory / "timer-start.json", {"wall_seconds": 300})
                save(directory / "compute-finished.json", {"status": "verified_target", "full_compute_seconds": full})
                entry.update(status="verified_target", credited_verified_target=True, full_compute_seconds=full,
                             exit_code=0, result_sha256=c.sha256(directory / "result.json"))
            entries.append(entry)
            save(self.run / f"job-{index:03d}-closeout.json", entry)
        save(self.run / "study-completed.json", {"status": "completed_fixed_schedule", "entries": entries,
             "unexecuted_jobs": [], "formal_study_completed": True,
             "summary": {"planned_jobs": 215, "dispatched_jobs": 215, "unexecuted_job_count": 0},
             "config_sha256": c.sha256(self.config), "freeze_sha256": c.sha256(self.freeze)})
        started = {"command": [".venv-sdp/bin/python", "-m", "experiments.extensions.metric_sdp_formal.run_study",
                    "--config", self.contract["config_path"], "--freeze", "mock-freeze.json", "--output", "mock-run"],
                   "cwd": ".", "environment": {"PYTHONPATH": "src:.", **self.contract["threads"]},
                   "config_sha256": c.sha256(self.config), "freeze_sha256": c.sha256(self.freeze),
                   "runtime_source_sha256": c.read_json(self.freeze)["runtime_source_sha256"],
                   "operator_source_sha256": c.sha256(self.root / c.OPERATOR)}
        save(self.run.with_name("mock-run-launch-started.json"), started)
        stdout = self.run.with_name("mock-run-launch-stdout.txt")
        stdout.write_text("synthetic retained controller log; no process executed\n")
        save(self.run.with_name("mock-run-launch-attempt.json"), {**started, "exit_code": 0,
             "operator_wall_seconds": 1, "retained_stdout_stderr": stdout.relative_to(self.root).as_posix(),
             "retained_stdout_stderr_sha256": c.sha256(stdout)})

    def mock_audit(self, records):
        names = ("source_config_freeze_and_outcome_accounting", "original_input_full_degrees_bank_and_incumbent",
                 "all_durable_operations_current_quotient_relaxation_safe", "exact_full_trace_quotient_and_signed_component_presolve",
                 "component_exact_primal_dual_and_raw_binding", "original_lift_psd_diag_box_all_triangles",
                 "quotient_upper_transfer_all_prior_operations", "original_exact_interval_and_width",
                 "complete_cost_and_hard_wall_RSS_target_eligibility")
        manifest = records["collection-manifest.json"]
        audits = [{**{k: r[k] for k in ("index", "case_id", "arm", "outcome_status", "result_sha256",
                   "failure_sha256", "durable_prefix_operations")}, "checks": {n: True for n in names}}
                  for r in records["job-rows.json"]]
        path = self.root / "synthetic-external-audit.json"
        save(path, {"schema": c.AUDIT_SCHEMA, "integrity_status": "validated", "scientific_credit_approved": True,
             "all_215_outcomes_accounted": True, "reviewer_task": "/synthetic/independent-parser-contract-fixture",
             "independent_of_composition_author": True, "config_sha256": manifest["config_sha256"],
             "freeze_sha256": manifest["freeze_sha256"], "raw_inventory_sha256": manifest["raw_inventory_sha256"],
             "collector_source_sha256": c.source_sha256(), "job_audits": audits})
        value = c.read_json(path)
        value["operator_command_logs_exit_and_limits_validated"] = True
        save(path, value)
        return path


class CollectionContract(unittest.TestCase):
    def test_all_unexecuted_and_diagnostic_only_complete_denominators(self):
        project = MockProject()
        save(project.run / "study-halted.json", {"retained_entries": [], "unexecuted_jobs": project.jobs,
             "unexecuted_job_identities_known": True,
             "summary": {"planned_jobs": 215, "dispatched_jobs": 0, "unexecuted_job_count": 215}})
        result = project.collect()
        self.assertEqual(result["collection-manifest.json"]["integrity_issues"], [])
        self.assertEqual(len(result["job-rows.json"]), 215)
        self.assertEqual(len(result["primary-pair-rows.json"]), 86)
        self.assertEqual(result["summary.json"]["overall"]["unexecuted"], 215)
        self.assertTrue(all(p["time_ratio_A_over_B"] is None for p in result["primary-pair-rows.json"]))
        self.assertFalse(result["collection-manifest.json"]["scientific_credit_authorized"])

    def test_external_gate_zero_cost_and_tamper_never_select_favorable_subset(self):
        project = MockProject()
        project.completed_metadata()
        diagnostic = project.collect()
        self.assertEqual(diagnostic["collection-manifest.json"]["integrity_issues"], [])
        self.assertTrue(all(p["time_ratio_A_over_B"] is None for p in diagnostic["primary-pair-rows.json"]))
        audit = project.mock_audit(diagnostic)
        audited = project.collect(audit)
        self.assertEqual(audited["collection-manifest.json"]["audit_refusal"], None)
        self.assertEqual(audited["collection-manifest.json"]["raw_inventory_sha256"],
                         diagnostic["collection-manifest.json"]["raw_inventory_sha256"])
        self.assertEqual(audited["primary-pair-rows.json"][0]["time_ratio_A_over_B"], 0.5)
        self.assertTrue(audited["primary-pair-rows.json"][1]["same_verified_target"])
        self.assertIsNone(audited["primary-pair-rows.json"][1]["time_ratio_A_over_B"])
        self.assertEqual(audited["primary-pair-rows.json"][1]["time_outcome"], "undefined")
        original = c.read_json(audit)
        for kind in ("self-review", "missing-outcome", "inventory-drift"):
            modified = copy.deepcopy(original)
            if kind == "self-review":
                modified["reviewer_task"] = c.AUTHOR
            elif kind == "missing-outcome":
                modified["job_audits"].pop()
            else:
                modified["raw_inventory_sha256"] = "0" * 64
            save(audit, modified)
            rejected = project.collect(audit)
            self.assertFalse(rejected["collection-manifest.json"]["scientific_credit_authorized"])
            self.assertTrue(rejected["collection-manifest.json"]["audit_refusal"])
            self.assertEqual(len(rejected["primary-pair-rows.json"]), 86)
            self.assertTrue(all(p["time_ratio_A_over_B"] is None for p in rejected["primary-pair-rows.json"]))
        save(audit, original)
        job = project.jobs[3]
        result_path = project.run / f"job-003-{job['case_id']}-{job['arm']}" / "result.json"
        modified = c.read_json(result_path)
        modified["gamma_exact"] = "2"
        save(result_path, modified)
        rejected = project.collect(audit)
        self.assertTrue(rejected["collection-manifest.json"]["integrity_issues"])
        self.assertFalse(rejected["collection-manifest.json"]["scientific_credit_authorized"])
        self.assertEqual(len(rejected["job-rows.json"]), 215)

    def test_operator_end_incomplete_and_log_drift_remain_diagnostic(self):
        project = MockProject()
        project.completed_metadata()
        final = project.run.with_name("mock-run-launch-attempt.json")
        saved = final.read_bytes()
        final.unlink()  # Metadata-only simulation of an operator still finishing.
        incomplete = project.collect()
        self.assertEqual(incomplete["collection-manifest.json"]["operator_evidence"]["state"], "incomplete")
        self.assertEqual(incomplete["collection-manifest.json"]["integrity_issues"], [])
        self.assertFalse(incomplete["collection-manifest.json"]["scientific_credit_authorized"])
        final.write_bytes(saved)
        complete = project.collect()
        audit = project.mock_audit(complete)
        stdout = project.run.with_name("mock-run-launch-stdout.txt")
        self.assertIn(stdout.relative_to(project.root).as_posix(), complete["raw-inventory.json"]["raw_artifact_sha256"])
        stdout.write_text("changed retained operator log\n")
        invalid = project.collect(audit)
        self.assertTrue(any("stdout digest" in x for x in invalid["collection-manifest.json"]["integrity_issues"]))
        self.assertFalse(invalid["collection-manifest.json"]["scientific_credit_authorized"])
        self.assertEqual(len(invalid["primary-pair-rows.json"]), 86)


if __name__ == "__main__":
    unittest.main()
