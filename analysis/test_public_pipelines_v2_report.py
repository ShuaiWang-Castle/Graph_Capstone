"""Pure synthetic input-contract fixtures; no public data, numerical modules or solver."""
from __future__ import annotations

import copy
from fractions import Fraction
import gzip
from pathlib import Path
import tempfile
import unittest

from analysis import public_pipelines_v2_report as report


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = report.json_bytes(value)
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == ".gz" else data)


def fixture(root):
    """Manufacture labeled schema examples, never pretend a benchmark was run."""
    config = {"datasets": list(report.DATASETS), "gamma": ["1/2", "1", "2"], "arms": list(report.ARMS),
              "discovery_seeds": list(report.DISCOVERY_SEEDS), "downstream_seeds": list(report.SEEDS),
              "prefixes": list(report.PREFIXES), "synthetic_engineering_fixture_only": True}
    config_path = root / report.DEFAULT_CONFIG
    put(config_path, config)
    source_map = {}
    for name in report.RUNTIME_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic byte-identity fixture; never executed.\n", encoding="utf-8")
        source_map[name] = report.sha256(path)
    cases = report.fixed_keys(config)
    ledger = {"counts": report.COUNTS, "cases": cases,
        "setups": [{"setup_key": f"{name}-discovery{seed}"} for name in report.DATASETS for seed in report.DISCOVERY_SEEDS],
        "executions": [{"case_key": row["case_key"], "arm": arm, "seed": seed} for row in cases for arm in report.ARMS for seed in report.SEEDS],
        "prefixes": [{"case_key": row["case_key"], "arm": arm, "prefix": prefix} for row in cases for arm in report.ARMS for prefix in report.PREFIXES]}
    archives = {}
    for row in ledger["setups"]:
        path = root / "archive" / (row["setup_key"] + ".json")
        put(path, {"synthetic_engineering_fixture_only": True})
        archives[row["setup_key"]] = {"path": path.relative_to(root).as_posix(), "sha256": report.sha256(path)}
    freeze = {"status": "frozen_after_independent_actual_source_and_configuration_review",
              "config_sha256": report.sha256(config_path), "runtime_source_sha256": source_map,
              "original_v1_runtime_source_sha256": {}, "required_artifact_sha256": {}, "archived_data_sha256": {},
              "archived_bank_identity": archives, "expected_ledger": ledger, "expected_ledger_sha256": report.content_hash(ledger),
              "synthetic_engineering_fixture_only": True}
    freeze_path = root / report.DEFAULT_FREEZE
    put(freeze_path, freeze)
    run_dir = root / "synthetic-run"
    run_manifest = {"config_sha256": freeze["config_sha256"], "freeze_sha256": report.sha256(freeze_path),
                    "runtime_source_sha256": source_map, "expected_ledger": ledger, "synthetic_engineering_fixture_only": True}
    put(run_dir / "run-manifest.json", run_manifest)
    put(run_dir / "run-completed.json", {"status": "completed", "completed_cases": 54, "completed_solver_calls": 1944,
                                        "prefix_summary_count": 648, "expected_counts": report.COUNTS,
                                        "synthetic_engineering_fixture_only": True})
    arms, comparisons, seeds, selected = [], [], [], []
    setup_hashes = {}
    for case in cases:
        setup_key = case["setup_key"]
        if setup_key not in setup_hashes:
            path = run_dir / f"{setup_key}-setup.json.gz"
            put(path, {"setup_key": setup_key, "status": "completed", "fixed_bank": {"candidate_count": 4},
                       "synthetic_engineering_fixture_only": True})
            setup_hashes[setup_key] = {"path": path.relative_to(root).as_posix(), "sha256": report.sha256(path)}
        key = case["case_key"]
        raw = {**case, "status": "completed", "completed_solver_calls": 36, "scheduled_solver_calls": 36,
               "prefix_summary_count": 12, "config_sha256": freeze["config_sha256"], "freeze_sha256": report.sha256(freeze_path),
               "setup_reference": setup_hashes[setup_key], "arms": {}, "synthetic_engineering_fixture_only": True}
        current_rows = []
        gamma, discovery = report.rational(case["gamma"]), case["discovery_seed"]
        qbase = Fraction(1, 3) + Fraction(discovery, 10000)
        qvalues = {"U": qbase, "D": qbase + Fraction(discovery - 1, 2**80), "R": qbase, "RD": qbase + Fraction(1, 10)}
        costs = {"U": 1.0, "D": 0.5, "R": 2.0, "RD": 1.5}
        for arm in report.ARMS:
            remaining = 1 if arm in ("D", "RD") else 2
            coverage = {"original_vertices": 2, "remaining_vertices": remaining, "removed_vertices": 2 - remaining,
                        "removed_fraction": (2 - remaining) / 2, "positive_degree_original_vertices": 2,
                        "positive_degree_removed_vertices": 2 - remaining,
                        "largest_component_under_original_objective": {"vertices": 2, "removed_vertices": 2 - remaining,
                                                                     "removed_fraction": (2 - remaining) / 2}}
            provenance = {"coverage": coverage, "graph_counts": {"off_diagonal_edges": 0, "loop_count": remaining}}
            mapped = None
            if arm in ("D", "RD"):
                statuses = ({"verified_positive_definite": 1, "auto_screened_without_verification": 2, "exact_size_limit_preassembly": 1}
                            if arm == "D" else {"verified_positive_definite": 1, "zero_degree_excluded": 1})
                provenance["degree_stage"] = {"candidate_count": sum(statuses.values()), "accepted_count": 1, "status_counts": statuses}
            if arm == "RD":
                mapped = {"complete_original_bank_count": 4, "trivial_original_image_count": 1, "unique_nontrivial_images": 2,
                          "duplicate_nontrivial_images_removed": 1, "current_cap_exclusions": 0, "admissible_current_images": 2,
                          "max_block_size": 64, "cap_applied_after_complete_original_bank_mapping": True}
                provenance["mapped_bank"] = {"summary": mapped}
                provenance["additional_removed_vertices_after_r"] = 1
            seed_values = [{"status": "completed", "arm": arm, "seed": seed,
                            "raw_original_Q_exact": report.rational_record(qvalues[arm]), "returned_Q_exact": report.rational_record(qvalues[arm]),
                            "winner_kind": "downstream_seed", "winner_seed": seed, "discovery_fallback": False} for seed in report.SEEDS]
            prefix_values = []
            for prefix in report.PREFIXES:
                cost = {"constructed_standalone_seconds": (10 + prefix) * costs[arm]}
                prefix_values.append({"prefix": prefix, "returned_Q_exact": report.rational_record(qvalues[arm]), "cost": cost})
                current_rows.append({"case_key": key, "dataset": case["dataset"], "discovery_seed": discovery, "gamma": case["gamma"],
                    "arm": arm, "prefix": prefix, "status": "completed", "returned_Q_exact": report.rational_record(qvalues[arm]),
                    "constructed_standalone_seconds": cost["constructed_standalone_seconds"], "phase_costs": cost, "coverage": coverage,
                    "degree_status_counts": provenance.get("degree_stage", {}).get("status_counts"), "mapped_bank_denominators": mapped,
                    "additional_removed_vertices_after_r": provenance.get("additional_removed_vertices_after_r")})
            raw["arms"][arm] = {"status": "completed", "provenance": provenance, "seed_results": seed_values, "prefixes": prefix_values}
            seeds.extend({"execution_key": f"{key}/{arm}/seed{row['seed']}", "case_key": key, "arm": arm, "seed": row["seed"],
                          "status": "completed", "eligible_for_completed_case_metrics": True, "raw_and_selected_result": row} for row in seed_values)
        path = run_dir / f"{key}.json.gz"
        put(path, raw)
        source = {"path": path.relative_to(root).as_posix(), "sha256": report.sha256(path)}
        selected.append({"case_key": key, "status": "completed", "selected_raw_path": source["path"], "selected_raw_sha256": source["sha256"],
                         "failed_partial_path": None, "failed_partial_sha256": None})
        for row in current_rows:
            row["source_raw_reference"] = source
        arms.extend(current_rows)
        by_key = {(row["arm"], row["prefix"]): row for row in current_rows}
        for a, b in report.COMPARISONS:
            for prefix in report.PREFIXES:
                ta, tb = (by_key[(arm, prefix)]["constructed_standalone_seconds"] for arm in (a, b))
                matched = qvalues[a] == qvalues[b]
                comparisons.append({"case_key": key, "dataset": case["dataset"], "discovery_seed": discovery, "gamma": case["gamma"],
                    "comparison": f"{a}/{b}", "arm_A": a, "arm_B": b, "prefix": prefix, "status": "completed",
                    "returned_Q_A_exact": report.rational_record(qvalues[a]), "returned_Q_B_exact": report.rational_record(qvalues[b]),
                    "returned_Q_A_minus_B_exact": report.rational_record(qvalues[a] - qvalues[b]), "speedup_B_over_A": tb / ta,
                    "total_cost_A_over_B": ta / tb, "quality_matched": matched,
                    "quality_matched_speedup_B_over_A": tb / ta if matched else None, "source_raw_reference": source})
    collection = root / report.DEFAULT_COLLECTION
    tables = {"arm_prefix_rows": arms, "paired_comparison_rows": comparisons, "seed_execution_rows": seeds}
    put(collection / "tables.json", tables)
    (collection / "paired-comparisons.csv").write_text("synthetic_engineering_fixture_only\n", encoding="utf-8")
    manifest = {"schema_version": report.SCHEMA, "status": "complete", "run_dir": run_dir.relative_to(root).as_posix(),
        "config_sha256": freeze["config_sha256"], "freeze_sha256": report.sha256(freeze_path), "runtime_source_sha256": source_map,
        "expected_ledger_sha256": freeze["expected_ledger_sha256"], "expected_counts": report.COUNTS,
        "case_status_counts": {"completed": 54}, "seed_execution_status_counts": {"completed": 1944}, "seed_execution_rows": 1944,
        "table_rows": {"arm_prefix_rows": 648, "paired_comparison_rows": 810}, "v1_or_native_timings_pooled": False,
        "prefixes_are_correlated_not_independent_graph_replicates": True, "case_selection": selected,
        "artifact_sha256": {name: report.sha256(collection / name) for name in ("tables.json", "paired-comparisons.csv")},
        "source_raw_sha256": {path.relative_to(root).as_posix(): report.sha256(path) for path in run_dir.iterdir()},
        "synthetic_engineering_fixture_only": True}
    put(collection / "collection-manifest.json", manifest)
    return collection, manifest, tables


class PureReportContractTests(unittest.TestCase):
    def test_complete_exact_quality_subsets_coverage_and_exclusive_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            summary = report.build_report(root=root)
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(len(summary["comparison_groups"]), 270)
            self.assertEqual(len(summary["coverage_groups"]), 72)
            def group(comparison):
                return next(row for row in summary["comparison_groups"] if row["dataset"] == "ca-GrQc"
                            and row["gamma"] == report.rational_record(Fraction(1, 2)) and row["prefix"] == 1 and row["comparison"] == comparison)
            degree = group("D/U")
            self.assertEqual(degree["speedup_B_over_A"], {"n": 3, "median": 2.0, "min": 2.0, "max": 2.0})
            self.assertEqual(degree["time_ratio_A_over_B"], {"n": 3, "median": 0.5, "min": 0.5, "max": 0.5})
            self.assertEqual(degree["time_A_relative_to_B_counts"], {"slower": 0, "equal": 0, "faster": 3, "undefined": 0})
            self.assertEqual(degree["quality_A_relative_to_B_counts"], {"better": 1, "equal": 1, "worse": 1})
            self.assertEqual(degree["returned_Q_A_exact"], {"n": 3,
                "median": report.rational_record(Fraction(1, 3) + Fraction(1, 10000)),
                "min": report.rational_record(Fraction(1, 3) - Fraction(1, 2**80)),
                "max": report.rational_record(Fraction(1, 3) + Fraction(2, 10000) + Fraction(1, 2**80))})
            self.assertEqual(degree["returned_Q_B_exact"]["min"], report.rational_record(Fraction(1, 3)))
            self.assertEqual(degree["quality_matched_seed_count"], 1)
            self.assertEqual(degree["quality_matched_speedup_B_over_A"]["n"], 1)
            self.assertEqual(degree["returned_Q_A_minus_B_exact"]["min"], report.rational_record(Fraction(-1, 2**80)))
            self.assertEqual(degree["returned_Q_A_minus_B_exact"]["max"], report.rational_record(Fraction(1, 2**80)))
            self.assertEqual(group("RD/U")["quality_matched_speedup_B_over_A"], {"n": 0, "median": None, "min": None, "max": None})
            self.assertEqual(group("R/U")["quality_matched_speedup_B_over_A"]["median"], 0.5)
            coverage = next(row for row in summary["coverage_groups"] if row["dataset"] == "ca-GrQc" and row["arm"] == "RD"
                            and row["gamma"] == report.rational_record(Fraction(1, 2)))
            self.assertEqual(coverage["metrics"]["additional_removed_vertices_after_r"]["median"], 1)
            self.assertEqual(coverage["mapped_bank_metrics"]["unique_nontrivial_images"]["median"], 2)
            self.assertEqual(coverage["degree_statuses"]["zero_degree_excluded"]["total_decisions_across_three_fixed_seeds"], 3)
            output = root / report.DEFAULT_OUTPUT
            provenance = report.read_json(output / "report-provenance.json")
            for name, digest in provenance["artifact_sha256"].items():
                self.assertEqual(report.sha256(output / name), digest)
            before = report.sha256(output / "summary.json")
            with self.assertRaises(report.ReportError):
                report.build_report(root=root)
            self.assertEqual(report.sha256(output / "summary.json"), before)

    def test_zero_cost_domains_negative_Q_and_nonnull_subset_denominators(self):
        rows = []
        for case in report.fixed_keys({"datasets": report.DATASETS, "gamma": ("1/2", "1", "2"), "arms": report.ARMS,
                                       "discovery_seeds": report.DISCOVERY_SEEDS, "downstream_seeds": report.SEEDS,
                                       "prefixes": report.PREFIXES}):
            seed = case["discovery_seed"]
            # Pure aggregation examples: T_A/T_B is respectively 2, 1, undefined.
            # Q values include negative and zero; no relative modularity is taken.
            qa = Fraction(seed - 1, 10)
            ratio, speedup = ((2.0, 0.5), (1.0, 1.0), (None, 0.0))[seed]
            for a, b in report.COMPARISONS:
                for prefix in report.PREFIXES:
                    rows.append({**case, "comparison": f"{a}/{b}", "prefix": prefix,
                        "returned_Q_A_exact": report.rational_record(qa), "returned_Q_B_exact": report.rational_record(Fraction(0)),
                        "returned_Q_A_minus_B_exact": report.rational_record(qa), "total_cost_A_over_B": ratio,
                        "speedup_B_over_A": speedup, "quality_matched": seed == 1,
                        "quality_matched_speedup_B_over_A": speedup if seed == 1 else None,
                        "source_raw_reference": {"synthetic_engineering_fixture_only": True}})
        group = report.summarize_comparisons(rows)[0]
        self.assertEqual(group["time_A_relative_to_B_counts"], {"slower": 1, "equal": 1, "faster": 0, "undefined": 1})
        self.assertEqual(group["time_ratio_A_over_B"], {"n": 2, "median": 1.5, "min": 1.0, "max": 2.0})
        self.assertEqual(group["speedup_B_over_A"], {"n": 3, "median": 0.5, "min": 0.0, "max": 1.0})
        self.assertEqual(group["returned_Q_A_exact"], {"n": 3, "median": report.rational_record(Fraction(0)),
            "min": report.rational_record(Fraction(-1, 10)), "max": report.rational_record(Fraction(1, 10))})
        self.assertEqual(group["quality_A_relative_to_B_counts"], {"better": 1, "equal": 1, "worse": 1})
        self.assertEqual(group["quality_matched_seed_count"], 1)
        self.assertEqual(group["quality_matched_speedup_B_over_A"]["n"], 1)
        # An exact quality match with T_A=0 still belongs to the match denominator,
        # while the undefined T_B/T_A is omitted from its numeric statistics.
        for row in rows:
            if row["discovery_seed"] == 1:
                row["total_cost_A_over_B"] = 0.0
                row["speedup_B_over_A"] = None
                row["quality_matched_speedup_B_over_A"] = None
        group = report.summarize_comparisons(rows)[0]
        self.assertEqual(group["time_A_relative_to_B_counts"], {"slower": 1, "equal": 0, "faster": 1, "undefined": 1})
        self.assertEqual(group["speedup_B_over_A"]["n"], 2)
        self.assertEqual(group["quality_matched_seed_count"], 1)
        self.assertEqual(group["quality_matched_speedup_B_over_A"], {"n": 0, "median": None, "min": None, "max": None})

    def test_partial_duplicate_missing_hash_and_quality_corruption_are_refused(self):
        for kind in ("partial", "duplicate_seed", "duplicate_prefix", "missing_comparison", "runtime_hash", "raw_hash", "quality"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                collection, manifest, tables = fixture(root)
                if kind == "partial":
                    manifest["status"] = "partial_with_failure_denominators"
                elif kind == "runtime_hash":
                    (root / next(iter(report.RUNTIME_PATHS))).write_text("Changed synthetic source bytes.\n", encoding="utf-8")
                elif kind == "raw_hash":
                    (root / manifest["case_selection"][0]["selected_raw_path"]).write_bytes(b"changed raw bytes")
                else:
                    if kind == "duplicate_seed":
                        tables["seed_execution_rows"][0] = copy.deepcopy(tables["seed_execution_rows"][1])
                    elif kind == "duplicate_prefix":
                        tables["arm_prefix_rows"][0] = copy.deepcopy(tables["arm_prefix_rows"][1])
                    elif kind == "missing_comparison":
                        tables["paired_comparison_rows"].pop()
                    else:
                        tables["paired_comparison_rows"][0]["quality_matched"] = True
                    put(collection / "tables.json", tables)
                    manifest["artifact_sha256"]["tables.json"] = report.sha256(collection / "tables.json")
                put(collection / "collection-manifest.json", manifest)
                with self.assertRaises(report.ReportError):
                    report.build_report(root=root)
                self.assertFalse((root / report.DEFAULT_OUTPUT).exists())


if __name__ == "__main__":
    unittest.main()
