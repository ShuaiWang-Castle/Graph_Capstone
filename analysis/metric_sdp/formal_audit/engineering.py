"""New bounded audit-helper fixtures; authoring is separate from execution.

Run only AFTER root's explicit finished-measurements signal. All actual exact
graphs have n<=4. The 215-row exercises are mocks without graph construction,
discovery, a scientific worker, a solver or a scientific measurement. Each
attempt uses a new exclusive output directory and retains exact fixture values,
source identities, unittest output and all failures. These are engineering
diagnostics and never performance or utility evidence.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import copy
from fractions import Fraction as F
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
from analysis.metric_sdp.formal_audit import closeout as audit

OUTPUT = None
FIXTURES = {
    "two_disjoint_weighted_edges": {"A": [[0, 2, 0, 0], [2, 0, 0, 0], [0, 0, 0, 5], [0, 0, 5, 0]], "gamma": "0"},
    "two_copied_leaves": {"A": [[0, 0, 1], [0, 0, 1], [1, 1, 0]], "gamma": "0"},
    "disjoint_exterior_columns": {"A": [[0, 10, 1, 0], [10, 0, 0, 1], [1, 0, 0, 0], [0, 1, 0, 0]], "gamma": "0"},
}


def graph(name):
    value = FIXTURES[name]
    return audit.graph_from_dense([[F(x) for x in row] for row in value["A"]], F(value["gamma"]))


def pair(u, v, p, affinity, loss, active, inactive, strict):
    return {"criterion": "exact optimized constant-mixture pair copy", "u": u, "v": v,
            "p": str(F(p)), "affinity": str(F(affinity)), "loss": str(F(loss)),
            "margin": str(F(affinity) - F(loss)), "certified": True, "strict": strict,
            "active_exterior_columns": active, "inactive_volume": str(F(inactive)),
            "tie_policy": "smallest minimizing probability",
            "weak_anchor_support": [u] if F(p) == 1 else [v] if F(p) == 0 else [u, v]}


def zero_exterior_certificate(stage, current):
    """Hand-derived projected matrices for the new explicit n4 two-edge graph."""
    if stage == "S":
        return {"criterion": "exact uniform collective copy", "block": [0, 1, 2, 3],
                "certified": True, "strict": False, "available": True, "status": "verified_exact_psd",
                "distances": [["0"] * 4 for _ in range(4)],
                "projected_matrix": [["7", "3", "10"], ["3", "7", "10"], ["10", "10", "20"]]}
    if stage == "D":
        return {"criterion": "core exact actual-median degree copy", "block": [0, 1, 2, 3],
                "certified": True, "strict": False, "available": True, "status": "verified_exact_psd",
                "basis_pivot": 2, "delta": ["0"] * 4, "weighted_mean_delta": "0",
                "projected_matrix": [["14/5", "-6/5", "4"], ["-6/5", "14/5", "4"], ["4", "4", "20"]]}
    return {"criterion": "project-derived exact degree-weighted collective reference", "block": [0, 1, 2, 3],
            "penalty": "full_pair_distance", "center": None, "gamma": "0", "certified": True,
            "strict": False, "available": True, "status": "verified_positive_semidefinite",
            "verification_status": "verified_positive_semidefinite", "metadata": {
                "graph_fingerprint": current["weighted_fingerprint"], "block_volume_exact": "14",
                "total_volume_exact": "14", "gamma_exact": "0",
                "exact_pair_penalties": [["0"] * 4 for _ in range(4)],
                "exact_projected_matrix": [["8", "10", "10"], ["10", "35/2", "15/2"], ["10", "15/2", "35/2"]]}}


def leaf_events():
    original = graph("two_copied_leaves")
    q1 = audit.graph_from_dense([[F(0), F(2)], [F(2), F(0)]], F(0))
    q2 = audit.graph_from_dense([[F(4)]], F(0))
    checkpoints = {"bank": {"blocks": [[0, 1], [0, 1, 2]], "discovery_labels": [0, 0, 0]}}
    certificates = [pair(0, 1, "1/2", 0, 0, 1, 0, False), pair(0, 1, 0, 2, 0, 0, 0, True)]
    graphs, before_maps, maps, after_maps, blocks = [original, q1, q2], [[0, 1, 2], [0, 0, 1]], [[0, 0, 1], [0, 0]], [[0, 0, 1], [0, 0, 0]], [[0, 1], [0, 1]]
    events = []
    for i in range(2):
        before, after = graphs[i:i + 2]
        op = {"index": i, "stage": "S", "current_n_before": before["n"], "block_current": blocks[i],
              "original_groups_before": [[u for u, c in enumerate(before_maps[i]) if c == v] for v in blocks[i]],
              "original_bank_blocks": [], "original_membership_before": before_maps[i],
              "current_graph_sha256": before["exact_fingerprint"], "gamma_exact": "0", "S_exact": "4",
              "block_volume_exact": "2" if i == 0 else "4", "certificate": certificates[i],
              "current_n_after": after["n"], "old_to_new_membership": maps[i],
              "original_membership_after": after_maps[i], "quotient_graph_sha256": after["exact_fingerprint"],
              "quotient_degrees_exact": list(map(str, after["d"]))}
        events.append({"kind": "accepted_operation", "mode": "S", "operation": op,
                       "counts_snapshot": {"S_accepted_operations": i + 1}, "completed_phases": []})
    return original, checkpoints, events


def proof_fixture(directory):
    """Explicit q2 proposal and Gram factors; no numerical factor construction."""
    import numpy as np
    from experiments.extensions.metric_sdp import rational
    C = ((F(0), F(1, 7)), (F(1, 7), F(0)))
    H, y, lambdas, slack = np.ones((2, 2)), np.array([float(F(1, 7))] * 2), np.zeros(2), np.zeros((2, 2))
    inequalities = [rational.Inequality("lower", 0, 1), rational.Inequality("upper", 0, 1)]
    proof = rational.repair_interval(C, H, y, inequalities, lambdas,
        denominator=2 ** 40, primal_factor=np.ones((2, 1)), dual_factor=np.zeros((2, 0)))
    raw = directory / "component-000-round-000-raw.npz"
    with raw.open("xb") as handle:
        np.savez_compressed(handle, H=H, y=y, lambdas=lambdas, psd_dual_slack=slack,
                            triangles=np.zeros((0, 3), dtype=np.int64))
    metric = {"round": 0, "active_triangles": 0, "epsilon": 1e-6,
              "lower_exact": str(proof.lower), "upper_exact": str(proof.upper), "width_exact": str(proof.width)}
    (directory / "component-000-round-000-metrics.json").write_bytes(audit.json_bytes(metric))
    (directory / "component-000-proof.json").write_bytes(audit.json_bytes(proof.to_dict()))
    return C, proof, metric


class Engineering(unittest.TestCase):
    def folder(self, name):
        target = OUTPUT / name
        target.mkdir(exist_ok=False)
        return target

    def test_loop_mass_and_full_trace_quotient(self):
        current = graph("two_disjoint_weighted_edges")
        after, mapping = audit.merge(current, [0, 1])
        self.assertEqual(mapping, [0, 0, 1, 2])
        self.assertEqual(after["A"], ((F(4), F(0), F(0)), (F(0), F(0), F(5)), (F(0), F(5), F(0))))
        self.assertEqual(after["d"], (F(4), F(5), F(5)))
        self.assertEqual(after["S"], F(14))
        self.assertEqual(after["C"][0][0], F(2, 7))
        self.assertEqual(sum((x for row in after["C"] for x in row), F()), F(1))

    def test_three_independent_collective_matrices_and_tampers(self):
        current = graph("two_disjoint_weighted_edges")
        for stage in ("S", "D", "W"):
            certificate = zero_exterior_certificate(stage, current)
            checked = audit.check_criterion(current, [0, 1, 2, 3], certificate, stage)
            self.assertEqual(checked["exact_rank"], 2)
            self.assertFalse(checked["strict"])
            damaged = copy.deepcopy(certificate)
            if stage == "W":
                damaged["metadata"]["exact_projected_matrix"][0][0] = "9"
            else:
                damaged["projected_matrix"][0][0] = "9"
            with self.assertRaises(audit.AuditFailure):
                audit.check_criterion(current, [0, 1, 2, 3], damaged, stage)
            damaged = copy.deepcopy(certificate)
            damaged["strict"] = True
            with self.assertRaises(audit.AuditFailure):
                audit.check_criterion(current, [0, 1, 2, 3], damaged, stage)

    def test_dense_exterior_actual_medians_and_lower_pair_tie(self):
        current = graph("disjoint_exterior_columns")
        audit.check_criterion(current, [0, 1], pair(0, 1, 0, 10, 1, 2, 0, True), "S")
        D = {"criterion": "core exact actual-median degree copy", "block": [0, 1], "certified": True,
             "strict": True, "available": True, "status": "verified_exact_psd", "basis_pivot": 0,
             "delta": ["1/11", "1/11"], "weighted_mean_delta": "1/11", "projected_matrix": [["36"]]}
        audit.check_criterion(current, [0, 1], D, "D")
        D["delta"][0] = "0"
        with self.assertRaises(audit.AuditFailure):
            audit.check_criterion(current, [0, 1], D, "D")
        noncanonical_tie = pair(0, 1, 1, 10, 1, 2, 0, True)
        with self.assertRaises(audit.AuditFailure):
            audit.check_criterion(current, [0, 1], noncanonical_tie, "S")

    def test_true_sequential_weak_prefix_and_stale_current_refusals(self):
        original, checkpoint, events = leaf_events()
        final, membership, checked = audit.replay_operations(original, checkpoint, events, "S", 4)
        self.assertEqual(final["A"], ((F(4),),))
        self.assertEqual(membership, [0, 0, 0])
        self.assertEqual([x["strict"] for x in checked], [False, True])
        for field, value in (("current_graph_sha256", original["exact_fingerprint"]),
                             ("original_membership_before", [0, 1, 2]), ("block_volume_exact", "2")):
            damaged = copy.deepcopy(events)
            damaged[1]["operation"][field] = value
            with self.assertRaises(audit.AuditFailure):
                audit.replay_operations(original, checkpoint, damaged, "S", 4)
        damaged = copy.deepcopy(events)
        damaged[0]["completed_phases"] = [{"stage": "S", "start_n": 3, "end_n": 2,
                                           "accepted_operations": 1, "fixed_point": True}]
        with self.assertRaises(audit.AuditFailure):
            audit.replay_operations(original, checkpoint, damaged, "S", 4)

    def test_independent_psd_singular_zero_row_and_negative_diagonal(self):
        self.assertEqual(audit.psd([[F(1), F(1)], [F(1), F(1)]]), (True, False, 1))
        self.assertFalse(audit.psd([[F(0), F(1)], [F(1), F(0)]])[0])
        self.assertFalse(audit.psd([[F(-1), F(0)], [F(0), F(1)]])[0])
        with self.assertRaises(audit.AuditFailure):
            audit.psd([[1.0]])

    def test_stored_original_csr_bank_incumbent_and_loop_tampers(self):
        import numpy as np
        directory = self.folder("original-csr")
        original = graph("disjoint_exterior_columns")
        bank = {"blocks": [[0, 1, 2, 3], [0, 1], [2, 3]], "discovery_labels": [0, 0, 0, 0]}
        checkpoint = {"original_n": 4, "original_fingerprint": original["fingerprint"],
                      "degrees_exact": list(map(str, original["d"])), "S_exact": "24", "gamma_exact": "0",
                      "bank": bank, "bank_sha256": audit.canonical_hash(bank), "incumbent_Q_exact": "1"}
        with (directory / "original-adjacency.npz").open("xb") as handle:
            np.savez_compressed(handle, data=np.array(original["values"]), indices=np.array(original["indices"]),
                                indptr=np.array(original["indptr"]), shape=np.array([4, 4]))
        self.assertEqual(audit.check_original(directory, checkpoint, original, {"metadata": None}), F(1))
        for key, value in (("degrees_exact", ["10", "11", "1", "1"]), ("S_exact", "23"), ("incumbent_Q_exact", "0")):
            damaged = copy.deepcopy(checkpoint)
            damaged[key] = value
            with self.assertRaises(audit.AuditFailure):
                audit.check_original(directory, damaged, original, {"metadata": None})
        damaged = copy.deepcopy(checkpoint)
        damaged["bank"]["blocks"].append([0, 1])
        damaged["bank_sha256"] = audit.canonical_hash(damaged["bank"])
        with self.assertRaises(audit.AuditFailure):
            audit.check_original(directory, damaged, original, {"metadata": None})

    def test_component_payload_raw_binding_and_partial_nonproof(self):
        from analysis.metric_sdp import pilot_validation as pilot
        directory = self.folder("proof-q2")
        C, proof, metric = proof_fixture(directory)
        current = audit.graph_from_dense([[F(0), F(1)], [F(1), F(0)]], F(5, 7))
        # The payload is deliberately checked against its different explicit C
        # below first, then refused under a wrong current objective.
        from experiments.extensions.metric_sdp import rational
        self.assertTrue(rational.verify_interval(C, rational.interval_from_payload(proof.to_dict())))
        summary, arrays = pilot.raw_round(directory / "component-000-round-000-raw.npz", 2, False)
        self.assertTrue(summary["all_proposals_finite"])
        config = {"solver": {"rational_denominator": 2 ** 40, "max_rounds": 2, "eps_sequence": [1e-6]}}
        pilot.proof_raw_binding(proof, arrays, config)
        altered = {key: value.copy() for key, value in arrays.items()}
        altered["H"][0, 1] = 0
        with self.assertRaises(pilot.AuditFailure):
            pilot.proof_raw_binding(proof, altered, config)
        with self.assertRaises((audit.AuditFailure, ValueError, ArithmeticError)):
            audit.replay_proofs(directory, {}, None, current, [[0, 1]], [F(1, 1000)], config, pilot)
        # A new interrupted NPZ is retained, never converted into a proof.
        incomplete = directory / "new-incomplete-raw.npz"
        incomplete.write_bytes(b"PK\x03\x04incomplete engineering fixture")
        partial, values = pilot.raw_round(incomplete, 2, True)
        self.assertTrue(partial["retained_unreadable_partial"])
        self.assertIsNone(values)

    def test_original_lift_all_orientations_repeated_membership(self):
        import numpy as np
        from analysis.metric_sdp import pilot_validation as pilot
        from experiments.extensions.metric_sdp import rational
        original = graph("two_copied_leaves")
        current, membership = audit.merge(original, [0, 1])
        # The first weak merge from leaf_events is relaxed-safe. With gamma0,
        # the q2 all-ones Gram gives exact interval[1,1] and Y_original=J_3.
        proof = rational.repair_interval(current["C"], np.ones((2, 2)), np.array([0.5, 0.5]),
            [rational.Inequality("lower", 0, 1), rational.Inequality("upper", 0, 1)], np.zeros(2),
            denominator=2 ** 40, primal_factor=np.ones((2, 1)), dual_factor=np.zeros((2, 0)))
        result = {"lower_exact": "1", "upper_exact": "1", "width_exact": "0",
                  "discrete_incumbent_gap_exact": "0", "lift_validation": {
                      "original_lifted_trace_exact": "1", "all_cross_coefficients_nonpositive": True}}
        value = audit.check_lift(original, current, membership, [[0, 1]], {0: proof}, set(), result, F(1), pilot)
        self.assertEqual(value["lower_exact"], "1")
        local = proof.primal.matrix.fractions()
        Y = [[local[membership[i]][membership[j]] for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    self.assertLessEqual(Y[i][j] + Y[j][k] - Y[i][k], 1)
        self.assertEqual(sum((original["C"][i][j] * Y[i][j] for i in range(3) for j in range(3)), F()), F(1))

    def test_unresolved_result_first_precedence_timer_and_failure_budget(self):
        directory = self.folder("unresolved-markers")
        timer = {"wall_seconds": 300, "perf_counter": 100}
        (directory / "timer-start.json").write_bytes(audit.json_bytes(timer))
        config = {"formal": {"wall_seconds": 300, "rss_bytes": 100}, "watchdog": {"initialization_limit_seconds": 60}}
        entry = {"status": "full_wall_limit", "limit_reason": "full_wall_limit", "exit_code": -15,
                 "process_wall_seconds_including_import_input_output": 302, "monitored_peak_RSS_bytes": 101,
                 "full_compute_seconds": None}
        self.assertIsNone(audit.check_outcome(directory, entry, None, config))
        damaged = {**entry, "status": "missing_final_result"}
        with self.assertRaises(audit.AuditFailure):
            audit.check_outcome(directory, damaged, None, config)
        finished = {"status": "verified_interval_too_wide", "full_compute_seconds": 10, "perf_counter": 111}
        (directory / "compute-finished.json").write_bytes(audit.json_bytes(finished))
        # Result-first precedence preserves a serialized mathematical status
        # separately from a later physical RSS/serialization interruption.
        bounded = {"status": "verified_interval_too_wide"}
        entry.update(status="verified_interval_too_wide", limit_reason="rss_limit")
        audit.check_outcome(directory, entry, bounded, config)
        entry["status"] = "rss_limit"
        with self.assertRaises(audit.AuditFailure):
            audit.check_outcome(directory, entry, bounded, config)
        timer["wall_seconds"] = 180
        (directory / "timer-start.json").write_bytes(audit.json_bytes(timer))
        with self.assertRaises(audit.AuditFailure):
            audit.check_outcome(directory, entry, None, config)

    def test_required_applicability_retains_unbounded_and_unexecuted(self):
        row = {"original_checkpoint_present": False, "durable_prefix_operations": 0,
               "composition_completed": False, "reported_lower_exact": None, "controller_target_claimed": False}
        self.assertEqual(audit.required_checks(row), {"source_config_freeze_and_outcome_accounting"})
        row.update(original_checkpoint_present=True, durable_prefix_operations=1)
        self.assertIn("all_durable_operations_current_quotient_relaxation_safe", audit.required_checks(row))
        self.assertNotIn("original_exact_interval_and_width", audit.required_checks(row))
        row.update(composition_completed=True, reported_lower_exact="0", controller_target_claimed=True)
        self.assertEqual(len(audit.required_checks(row)), 9)

    def test_complete_215_mock_denominator_and_no_favorable_subset(self):
        directory = self.folder("mock-215")
        cases = [{"case_id": f"mock-{i:03d}", "stratum": "controlled", "parameters": {"engineering": True}} for i in range(43)]
        jobs = [{"case_id": cases[i // 5]["case_id"], "case_index": i // 5,
                 "arm": ("U", "S", "D", "SD", "SW")[(i // 5 + i % 5) % 5], "backend": "mock"} for i in range(215)]
        rows = [{"index": i, **job, "outcome_status": "unexecuted", "result_sha256": None,
                 "failure_sha256": None, "durable_prefix_operations": 0,
                 "original_checkpoint_present": False, "composition_completed": False,
                 "reported_lower_exact": None, "controller_target_claimed": False, "partial_files": []}
                for i, job in enumerate(jobs)]
        raw = {"controller_state": "halted", "operator": {"state": "complete"}, "raw_artifact_sha256": {}}
        manifest = {"status": "diagnostic_only", "scientific_credit_authorized": False, "independent_exactness_audit": None,
                    "collector_source_sha256": {}, "raw_inventory_sha256": audit.canonical_hash(raw),
                    "config_sha256": "mock-config", "freeze_sha256": "mock-freeze", "integrity_issues": []}
        fresh = {"raw-inventory.json": raw, "job-rows.json": rows, "primary-pair-rows.json": [],
                 "summary.json": {}, "collection-manifest.json": manifest}
        for name, value in fresh.items():
            if name != "collection-manifest.json":
                (directory / name).write_bytes(audit.json_bytes(value))
        recorded = {**manifest, "output_artifact_sha256": {name: audit.digest(directory / name)
                    for name in fresh if name != "collection-manifest.json"}}
        (directory / "collection-manifest.json").write_bytes(audit.json_bytes(recorded))
        mock_collector = SimpleNamespace(
            collect=lambda *args, **kwargs: fresh,
            authenticate=lambda *args: ({"cases": cases}, {}, {}, "mock-config", "mock-freeze", []),
            fixed_schedule=lambda contract: jobs,
            controller=lambda *args: ("halted", {}, []),
            inspect_job=lambda *args: (rows[args[2]], {}),
            inventory=lambda *args: ({}, []))
        kwargs = {"config_sha": "mock-config", "freeze_sha": "mock-freeze",
                  "collection_sha": audit.digest(directory / "collection-manifest.json"),
                  "source_approval": directory / "unused-mock-source-approval", "source_approval_sha": "mock"}
        fake_pilot = SimpleNamespace(inspect_environment=lambda frozen: None)
        with patch.object(audit, "authenticate_dependencies", return_value=(fake_pilot, {"engineering_mock": True})), \
             patch.object(audit, "imported", return_value=mock_collector), \
             patch.object(audit, "operator_events"), patch.object(audit, "original_graph", side_effect=AssertionError("graph regeneration forbidden in mock")):
            result = audit.audit(directory / "mock-config", directory / "mock-freeze", directory / "absent-run", directory, **kwargs)
            self.assertTrue(result["all_215_outcomes_accounted"])
            self.assertEqual(len(result["job_audits"]), 215)
            self.assertEqual(result["credited_verified_target_jobs"], 0)
            self.assertEqual(result["original_inputs_reconstructed_once"], 0)
            with patch.object(audit, "audit_job", side_effect=lambda *args: {
                **{key: args[2][key] for key in ("index", "case_id", "arm", "outcome_status", "result_sha256", "failure_sha256", "durable_prefix_operations")},
                "checks": {}, "findings": [], "credited_verified_target": False}):
                refused = audit.audit(directory / "mock-config", directory / "mock-freeze", directory / "absent-run", directory, **kwargs)
            self.assertFalse(refused["scientific_credit_approved"])
            self.assertEqual(len(refused["job_audits"]), 215)
            self.assertEqual(len(refused["findings"]), 215)


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements-finished", action="store_true", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    OUTPUT = Path(args.output).resolve()
    audit.require(OUTPUT.is_relative_to(audit.ROOT / audit.BASE), "engineering output outside assigned namespace")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    source_before = {path: audit.digest(audit.ROOT / path) for path in (*audit.HELPER_SOURCES, audit.BASE + "engineering.py")}
    (OUTPUT / "fixture-values.json").write_bytes(audit.json_bytes({"scope": "new explicit n<=4 graphs and mocks only", "fixtures": FIXTURES}))
    stream = io.StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Engineering))
    (OUTPUT / "unittest.txt").write_text(stream.getvalue(), encoding="utf-8")
    record = {"schema": "metric-sdp-formal-audit-helper-engineering-attempt-v1",
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "success": result.wasSuccessful(), "source_sha256_before": source_before,
              "source_sha256_after": {path: audit.digest(audit.ROOT / path) for path in source_before},
              "maximum_actual_graph_n": 4, "mock_outcome_denominator": 215,
              "scientific_input_generation": False, "candidate_discovery": False, "solver_or_native_backend": False,
              "scientific_worker": False, "author_or_old_suite_rerun": False,
              "scientific_or_performance_evidence": False, "all_attempt_failures_retained": True}
    (OUTPUT / "attempt.json").write_bytes(audit.json_bytes(record))
    sys.stdout.write(stream.getvalue())
    print(json.dumps(record))
    return 0 if record["success"] and record["source_sha256_before"] == record["source_sha256_after"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
