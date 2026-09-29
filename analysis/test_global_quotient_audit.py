"""Engineering fixtures for the exploratory audit, not benchmark evidence.

Do not run while the formal sequential benchmark is active or on its partial
results. These small constructed inputs check arithmetic, guards, dependency
bookkeeping, and failure isolation; mocked safety checks prove no criterion.
After root authorizes post-run validation:
    .venv/bin/python -m pytest -q analysis/test_global_quotient_audit.py
"""
from copy import deepcopy
from fractions import Fraction
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from analysis import global_quotient_audit as audit


def path_graph():
    return audit.ExactGraph.from_rows([{1: 1}, {0: 1, 2: 1}, {1: 1, 3: 1}, {2: 1}])


def manifest_fixture():
    return {"suites": ["public", "controls", "scaling"], "config": {
        "proposal": {"seeds": [7]}, "public_datasets": ["fixture-public"],
        "gamma": ["1/2", "1"], "development_datasets": ["fixture-development"],
        "controlled_cases": [{"case_id": "fixture-profile", "family": "profile_scaling",
                              "gamma": ["1"], "candidate_bank_evaluation": False}],
        "scaling": {"methods": ["first", "second"], "replicate_count": 2,
                    "memory_replicate_count": 1}}}


def case_fixture():
    return audit.Case("controlled", "fixture", "fixture", "fixture", ("1",), {})


def config_fixture():
    return {"checker": {"exact_max_size": 64, "dense_max_size": 64, "screen_tolerance": 1e-10},
            "recursive_cheap": {"max_block_size": 64}}


def certificate_record(block, *, fingerprint="fixture-fingerprint", gamma="1"):
    return {"block": block, "certified": True, "strict": False,
            "verification_status": "verified_positive_semidefinite",
            "metadata": {"graph_fingerprint": fingerprint, "gamma_exact": gamma}}


def raw_fixture(*, groups=None, certificates=None, recursive=None, native=None):
    value = {"status": "completed", "graph_fingerprint": "fixture-fingerprint", "gamma_exact": "1",
             "production_independent_bank": {"status": "completed",
                 "candidate_certificates": certificates or [],
                 "reduction": {"merge_groups": groups or []}}, "global_baselines": {}}
    if recursive is not None:
        value["global_baselines"]["recursive_cheap"] = recursive
    if native is not None:
        value["native_full_solver"] = native
    return value


def graph_data_fixture(graph=None):
    graph = graph or path_graph()
    return (SimpleNamespace(shape=(graph.n, graph.n)),
            SimpleNamespace(fingerprint="fixture-fingerprint"), graph, {})


def unexpected(*args, **kwargs):
    raise AssertionError("This dependency must not be called by the fixture")


class ExactArithmeticFixtures(unittest.TestCase):
    def test_sign_ties_keep_diagonal_and_do_not_assert_uniqueness(self):
        graph = audit.ExactGraph.from_rows([{0: 2, 1: 1}, {0: 1, 1: 2}])
        result = audit.solve_exact(graph, Fraction(2, 3))
        self.assertEqual(result["resolution_status"], "resolved_sign")
        self.assertEqual(result["Q_exact"], "1/3")
        self.assertEqual(graph.objective([0, 0], Fraction(2, 3)), Fraction(1, 3))
        self.assertFalse(result["uniqueness_asserted"])
        self.assertEqual(result["sign_test_positive_adjacency_pairs_checked"], 1)

    def test_one_vertex_is_explicitly_trivial(self):
        result = audit.solve_exact(audit.ExactGraph.from_rows([{0: 8}]), Fraction(3, 2))
        self.assertTrue(result["trivial"])
        self.assertEqual(result["Q_exact"], "-1/2")

    def test_binary_float_is_interpreted_exactly(self):
        graph = audit.ExactGraph.from_rows([{0: 0.1}])
        self.assertEqual(graph.volume, Fraction.from_float(0.1))
        self.assertNotEqual(graph.volume, Fraction(1, 10))

    def test_original_isolate_is_allowed_in_sign_proof(self):
        graph = audit.ExactGraph.from_rows([{1: 1}, {0: 1}, {}])
        result = audit.solve_exact(graph, 2)
        self.assertEqual(result["resolution_status"], "resolved_sign")
        self.assertEqual(result["Q_exact"], "-1")

    def test_all_set_partitions_and_full_modularity_constant(self):
        result = audit.solve_exact(path_graph(), 1)
        self.assertEqual(result["resolution_status"], "resolved_enumeration")
        self.assertEqual(result["partitions_evaluated"], 15)
        self.assertEqual(result["optimum_partition_count"], 1)
        self.assertEqual(result["Q_exact"], "1/6")
        self.assertEqual(result["upper_bound_Q_exact"], result["Q_exact"])

    def test_exact_quotient_keeps_doubled_internal_edges_and_lift(self):
        graph = path_graph()
        quotient, groups, membership = audit.exact_quotient(graph, [[0, 1], [2, 3]])
        self.assertEqual(quotient.rows, ({0: Fraction(2), 1: Fraction(1)},
                                        {0: Fraction(1), 1: Fraction(2)}))
        self.assertEqual(quotient.degrees, (Fraction(3), Fraction(3)))
        self.assertEqual(quotient.volume, graph.volume)
        result = audit.solve_exact(quotient, 1)
        lifted = [result["labels"][membership[u]] for u in range(graph.n)]
        self.assertEqual(result["resolution_status"], "resolved_sign")
        self.assertEqual(graph.objective(lifted, 1), Fraction(result["Q_exact"]))
        self.assertEqual(groups, ((0, 1), (2, 3)))

    def test_positive_graph_above_cap_is_unresolved(self):
        graph = audit.ExactGraph.from_rows([{v: 1 for v in range(11) if v != u} for u in range(11)])
        result = audit.solve_exact(graph, 0)
        self.assertFalse(result["resolved"])
        self.assertEqual(result["resolution_status"], "unresolved_above_enumeration_cap")
        with self.assertRaises(audit.AuditError):
            audit.solve_exact(graph, 0, enumeration_cap=11)

    def test_invalid_groups_and_adjacencies_are_rejected(self):
        with self.assertRaises(audit.AuditError):
            audit.exact_quotient(path_graph(), [[0, 1], [1, 2]])
        with self.assertRaises(audit.AuditError):
            audit.ExactGraph.from_rows([{1: 1}, {}])
        with self.assertRaises(audit.AuditError):
            audit.ExactGraph.from_rows([{0: -1}])
        with self.assertRaises(audit.AuditError):
            audit.ExactGraph.from_rows([{}])


class ManifestAndOutputFixtures(unittest.TestCase):
    def test_manifest_derives_all_tuples_and_rotated_scaling_jobs(self):
        manifest = manifest_fixture()
        cases = audit.expected_cases(manifest)
        self.assertEqual(sum(len(case.gammas) for case in cases), 5)
        self.assertEqual([case.stratum for case in cases], ["public", "controlled", "development"])
        jobs = audit.expected_jobs(manifest)
        self.assertEqual(len(jobs), 9)
        self.assertEqual(jobs[3:7], ["scaling-fixture-profile-first-timing-0",
                                    "scaling-fixture-profile-second-timing-0",
                                    "scaling-fixture-profile-second-timing-1",
                                    "scaling-fixture-profile-first-timing-1"])
        partial = deepcopy(manifest)
        partial["suites"].remove("scaling")
        with self.assertRaises(audit.AuditError):
            audit.expected_cases(partial)

    def test_halted_run_creates_no_output_and_imports_no_frozen_dependencies(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "formal"
            audit.write_once(run / "run-manifest.json", manifest_fixture())
            audit.write_once(run / "run-completed.json", {"status": "halted_for_repair", "outcomes": []})
            with patch.object(audit, "frozen_dependencies") as load:
                with self.assertRaises(audit.IncompleteRunError):
                    audit.run_audit("formal", "analysis/new-audit", repo_root=root)
                load.assert_not_called()
            self.assertFalse((root / "analysis/new-audit").exists())

    def test_complete_guard_requires_every_expected_job_in_order(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = manifest_fixture()
            audit.write_once(root / "run-manifest.json", manifest)
            rows = [{"job": job, "event": "completed", "exit_code": 0}
                    for job in audit.expected_jobs(manifest)]
            audit.write_once(root / "run-completed.json", {"status": "completed", "outcomes": rows,
                                                           "not_launched_due_failure": []})
            audit.validate_complete_run(root, audit.InputCatalog(root))
            for outcomes in (rows[:-1], list(reversed(rows)), [dict(row, exit_code=1) for row in rows]):
                (root / "run-completed.json").write_text(json.dumps({"status": "completed", "outcomes": outcomes}))
                with self.assertRaises(audit.IncompleteRunError):
                    audit.validate_complete_run(root, audit.InputCatalog(root))

    def test_missing_arms_remain_in_summary_denominator(self):
        rows = [{"stratum": "public", "arm": arm, **audit.unavailable("missing_record")}
                for arm in audit.ARMS]
        result = audit.summarize(rows, 1)
        self.assertEqual(result["observed_arm_rows"], 3)
        self.assertEqual(len(result["stratum_arm_cells"]), 3)
        for cell in result["stratum_arm_cells"]:
            self.assertEqual(cell["denominator"], 1)
            self.assertEqual(cell["status_counts"], {"unavailable": 1})
            self.assertEqual(cell["unavailability_reasons"], {"missing_record": 1})

    def test_exclusive_output_and_input_mutation_guard(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "record.json"
            audit.write_once(target, {"first": 1})
            with self.assertRaises(FileExistsError):
                audit.write_once(target, {"replacement": 1})
            catalog = audit.InputCatalog(root)
            catalog.observe(target)
            target.write_text('{"changed":1}')
            with self.assertRaises(audit.AuditError):
                catalog.verify_unchanged()
            with self.assertRaises(audit.AuditError):
                audit.validate_output_directory(root, root / "formal", root / "experiments/new-output")

    def test_bad_bank_hash_is_an_explicit_reduced_dependency_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            case = audit.Case("public", "fixture", "fixture", "fixture", ("1",), {})
            with (root / "fixture-candidates.json.gz").open("xb") as target:
                target.write(gzip.compress(json.dumps({"blocks": [[0, 1]], "bank_sha256": "wrong"}).encode()))
            bank, reason, _ = audit.case_bank(case, root, audit.InputCatalog(root))
            self.assertIsNone(bank)
            self.assertTrue(reason.startswith("invalid_candidate_bank:"))


class SafetyDependencyFixtures(unittest.TestCase):
    def test_forced_exact_check_and_compatible_union_are_recorded(self):
        graph = audit.ExactGraph.from_rows([{1: 1, 2: 1}, {0: 1, 2: 1}, {0: 1, 1: 1}])
        prepared = SimpleNamespace(fingerprint="fixture-fingerprint")
        blocks = [[0, 1], [1, 2]]
        raw = {"candidate_certificates": [certificate_record(block) for block in blocks],
               "reduction": {"merge_groups": [[0, 1, 2]]}}
        calls = []
        def certify(prepared_graph, block, gamma, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(certified=True, strict=False,
                verification_status="verified_positive_semidefinite",
                metadata={"graph_fingerprint": prepared_graph.fingerprint, "gamma_exact": str(gamma),
                          "exact_elimination": {"zero_pivots": 1}, "exact_verification_seconds": 9})
        result = audit.production_recheck(prepared, graph, raw, Fraction(1), blocks,
                                          config_fixture()["checker"], certify)
        self.assertEqual(result["accepted_block_count"], 2)
        self.assertTrue(all(call["verification"] == "exact" for call in calls))
        self.assertNotIn("exact_verification_seconds", result["checks"][0]["forced_exact_metadata"])

    def test_positive_degree_and_fingerprint_requirements_precede_checker(self):
        graph = audit.ExactGraph.from_rows([{1: 1}, {0: 1}, {}])
        prepared = SimpleNamespace(fingerprint="fixture-fingerprint")
        for record in (certificate_record([0, 2]), certificate_record([0, 1], fingerprint="wrong")):
            raw = {"candidate_certificates": [record], "reduction": {"merge_groups": [record["block"]]}}
            with self.assertRaises(audit.AuditError):
                audit.production_recheck(prepared, graph, raw, Fraction(1), [record["block"]],
                                          config_fixture()["checker"], unexpected)

    def test_bad_reduced_groups_do_not_erase_original_exact_proof(self):
        raw = raw_fixture(groups=[[0, 1], [1, 2]])
        rows, _ = audit.audit_case_gamma(case_fixture(), raw, graph_data_fixture(), [], None, Fraction(1),
                                         config_fixture(), {"certify": unexpected, "replay": unexpected})
        self.assertTrue(rows["original"]["original_optimum_established"])
        self.assertEqual(rows["original"]["Q_exact"], "1/6")
        self.assertEqual(rows["production"]["resolution_status"], "unavailable")
        self.assertTrue(rows["production"]["audit_errors"])

    def test_missing_bank_does_not_erase_original_exact_proof(self):
        rows, _ = audit.audit_case_gamma(case_fixture(), raw_fixture(), graph_data_fixture(), None,
                                         "missing_record", Fraction(1), config_fixture(),
                                         {"certify": unexpected, "replay": unexpected})
        self.assertTrue(rows["original"]["original_optimum_established"])
        self.assertEqual(rows["production"]["reason"], "missing_record")
        self.assertEqual(rows["recursive"]["reason"], "missing_record")

    def test_predeclared_profile_bank_skip_is_identity_production_arm(self):
        case = audit.Case("controlled", "fixture-profile", "fixture-profile", "fixture-profile", ("1",),
                          {"family": "profile_scaling", "candidate_bank_evaluation": False})
        raw = raw_fixture()
        raw["production_independent_bank"] = {"status": "unavailable",
            "verification_status": "predeclared_computation_only_bank_skip"}
        rows, _ = audit.audit_case_gamma(case, raw, graph_data_fixture(), [], "predeclared_bank_skip",
                                         Fraction(1), config_fixture(),
                                         {"certify": unexpected, "replay": unexpected})
        self.assertTrue(rows["production"]["identity_due_to_predeclared_skip"])
        self.assertTrue(rows["production"]["original_optimum_established"])
        self.assertEqual(rows["production"]["Q_exact"], rows["original"]["Q_exact"])
        self.assertEqual(rows["recursive"]["resolution_status"], "unavailable")

    def test_failed_exact_recheck_withholds_only_production_original_claim(self):
        raw = raw_fixture(groups=[[0, 1]], certificates=[certificate_record([0, 1])])
        def reject(*args, **kwargs):
            return SimpleNamespace(certified=False, strict=False, verification_status="failed_exact_psd")
        rows, _ = audit.audit_case_gamma(case_fixture(), raw, graph_data_fixture(), [[0, 1]], None,
                                         Fraction(1), config_fixture(), {"certify": reject, "replay": unexpected})
        self.assertTrue(rows["original"]["original_optimum_established"])
        self.assertTrue(rows["production"]["resolved"])
        self.assertFalse(rows["production"]["original_optimum_established"])
        self.assertEqual(rows["production"]["production_certificate_recheck"]["status"], "error")

    def test_bad_completed_native_value_remains_visible_without_erasing_original(self):
        native = {"paired_arms": {"unreduced": {"status": "optimal", "optimality_proved": True,
            "solution": {"labels": [0, 0, 1, 1], "Q": "0"},
            "lifted_labels": [0, 0, 1, 1], "lifted_Q_original_exact": "1/6"}}}
        rows, _ = audit.audit_case_gamma(case_fixture(), raw_fixture(native=native), graph_data_fixture(),
                                         [], None, Fraction(1), config_fixture(),
                                         {"certify": unexpected, "replay": unexpected})
        original = rows["original"]
        self.assertTrue(original["original_optimum_established"])
        self.assertTrue(original["audit_errors"])
        self.assertEqual(original["native_adapter_status"]["validation_status"], "error")

    def test_completed_native_reduced_witness_lifts_through_recorded_groups(self):
        graph = path_graph()
        quotient, _, membership = audit.exact_quotient(graph, [[0, 1], [2, 3]])
        record = {"status": "optimal", "optimality_proved": True,
                  "solution": {"labels": [0, 1], "Q": "1/6"},
                  "lifted_labels": [0, 0, 1, 1], "lifted_Q_original_exact": "1/6"}
        observations, values = audit.validate_native({"native_full_solver": {"paired_arms": {"reduced": record}}},
            graph, Fraction(1), {"production": quotient}, {"production": membership})
        self.assertEqual(values, {"reduced": Fraction(1, 6)})
        self.assertTrue(observations["reduced"]["quotient_lift_identity_verified"])

    def test_recursive_replay_preserves_decisions_and_is_not_independent_implementation(self):
        recorded = {"available": True, "certified": True, "gamma_exact": "1", "strict": False,
            "input_vertices": 4, "remaining_vertices": 2, "removed_vertices": 2, "round_count": 1,
            "merge_groups": [[0, 1], [2, 3]],
            "metadata": {"original_graph_sha256": "fixture-graph", "original_bank_sha256": "fixture-bank",
                         "final_quotient_sha256": "fixture-quotient", "total_volume_exact": "6", "max_block_size": 64},
            "round_stats": [{"input_vertices": 4, "remaining_vertices": 2, "round_seconds": 3,
                             "criteria": {"degree_proportional_twins": {"groups": 2}}}]}
        raw = {"result": recorded, "reduction": {"merge_groups": [[0, 1], [2, 3]]}}
        def replay(adjacency, bank, gamma, **kwargs):
            self.assertTrue(kwargs["include_round_decisions"])
            result = deepcopy(recorded)
            result["round_stats"][0]["round_seconds"] = 7
            result["round_stats"][0]["decisions_current_vertex_ids"] = {
                "degree_proportional_twins": [[0, 1], [2, 3]]}
            return result
        result = audit.recursive_replay(SimpleNamespace(shape=(4, 4)), raw, Fraction(1), [],
                                        config_fixture()["recursive_cheap"], replay)
        self.assertEqual(result["status"], "replayed_groups_match")
        self.assertFalse(result["independent_reimplementation_of_prior_criteria"])
        self.assertIn("decisions_current_vertex_ids", result["trace"]["round_stats"][0])
        wrong = deepcopy(raw)
        wrong["reduction"]["merge_groups"] = [[0, 2], [1, 3]]
        with self.assertRaises(audit.AuditError):
            audit.recursive_replay(SimpleNamespace(shape=(4, 4)), wrong, Fraction(1), [],
                                   config_fixture()["recursive_cheap"], replay)


if __name__ == "__main__":
    unittest.main()
