"""Hash-bound descriptive v2 summaries; standard library only, no graph execution."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

SCHEMA = "public-pipelines-v2.1"
DATASETS = ("ca-GrQc", "ca-HepTh", "email-Eu-core", "facebook_combined", "ca-CondMat", "p2p-Gnutella08")
GAMMAS = (Fraction(1, 2), Fraction(1), Fraction(2))
ARMS = ("U", "D", "R", "RD")
DISCOVERY_SEEDS = (0, 1, 2)
SEEDS = tuple(range(10, 19))
PREFIXES = (1, 3, 9)
COMPARISONS = (("D", "U"), ("R", "U"), ("RD", "U"), ("D", "R"), ("RD", "R"))
COUNTS = {"setups": 18, "cases": 54, "arm_states": 216, "executions": 1944, "prefixes": 648}
RUNTIME_PATHS = frozenset((
    "experiments/candidates.py", "experiments/datasets.py", "experiments/pipeline.py",
    "experiments/extensions/__init__.py", "experiments/extensions/public_pipelines_v2/__init__.py",
    *("experiments/extensions/public_pipelines_v2/" + name + ".py" for name in
      ("contracts", "integer_objective", "stages", "schedule", "run_case", "run_all", "freeze", "collect")),
    "research/baselines/almost_clique.py", "research/baselines/recursive_cheap.py", "research/baselines/sparse_criteria.py",
    "src/degree_contraction/__init__.py", "src/degree_contraction/certificate.py", "src/degree_contraction/quotient.py"))
ACCEPTED_STATUSES = {"verified_positive_definite", "verified_positive_semidefinite"}
DEFAULT_CONFIG = "experiments/extensions/public_pipelines_v2/config.json"
DEFAULT_FREEZE = "experiments/extensions/public_pipelines_v2/freeze.json"
DEFAULT_COLLECTION = "analysis/collections/20260929-public-pipelines-v2"
DEFAULT_OUTPUT = "analysis/results/20260929-public-pipelines-v2"


class ReportError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReportError(message)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def content_hash(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(root, path):
    root = Path(root).resolve()
    value = Path(path)
    result = (root / value).resolve() if not value.is_absolute() else value.resolve()
    require(result.is_relative_to(root), "artifact path leaves the repository root")
    return result


def portable(root, path):
    return resolve(root, path).relative_to(Path(root).resolve()).as_posix()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def read_json(path):
    path = Path(path)
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ReportError("nonfinite JSON constant: " + value)))


def rational(value):
    require(isinstance(value, dict) and set(value) == {"numerator", "denominator"}, "invalid rational fields")
    n, d = value["numerator"], value["denominator"]
    require(type(n) is int and type(d) is int and d > 0, "rational fields require integers and a positive denominator")
    result = Fraction(n, d)
    require(result.numerator == n and result.denominator == d, "rational fields must be reduced")
    return result


def rational_record(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def number(value, *, nullable=False):
    if value is None and nullable:
        return None
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "invalid nonnegative finite metric")
    return value


def integer(value):
    require(type(value) is int and value >= 0, "invalid nonnegative integer count")
    return value


def stats(values, *, exact=False):
    """A zero denominator has null summary values, never a fabricated zero."""
    available = [value for value in values if value is not None]
    if not available:
        return {"n": 0, "median": None, "min": None, "max": None}
    transform = rational_record if exact else (lambda value: value)
    return {"n": len(available), "median": transform(statistics.median(available)),
            "min": transform(min(available)), "max": transform(max(available))}


def verify_hashes(root, mapping, validated):
    require(isinstance(mapping, dict), "SHA inventory must be an object")
    for path, expected in mapping.items():
        require(isinstance(expected, str) and len(expected) == 64, "invalid SHA-256 identity")
        key = portable(root, path)
        require(key not in validated or validated[key] == expected, "conflicting input SHA identities")
        require(sha256(resolve(root, path)) == expected, "input SHA mismatch: " + key)
        validated[key] = expected


def fixed_keys(config):
    for key, expected in (("datasets", DATASETS), ("discovery_seeds", DISCOVERY_SEEDS), ("arms", ARMS),
                          ("downstream_seeds", SEEDS), ("prefixes", PREFIXES), ("gamma", ("1/2", "1", "2"))):
        require(tuple(config[key]) == expected, "configuration changes the fixed grid: " + key)
    require(all(type(value) is int for name in ("discovery_seeds", "downstream_seeds", "prefixes") for value in config[name]),
            "boolean/noninteger grid value")
    cases = []
    for dataset in DATASETS:
        for seed in DISCOVERY_SEEDS:
            for gamma in GAMMAS:
                setup = f"{dataset}-discovery{seed}"
                key = f"{setup}-gamma{gamma.numerator}over{gamma.denominator}"
                cases.append({"case_key": key, "setup_key": setup, "dataset": dataset,
                              "discovery_seed": seed, "gamma": rational_record(gamma), "case_ordinal": len(cases)})
    return cases


def unique_index(rows, key, expected, label):
    require(len(rows) == len(expected), "wrong " + label + " row count")
    index = {}
    for row in rows:
        value = key(row)
        require(value in expected and value not in index, "unknown/duplicate " + label + " key")
        index[value] = row
    require(set(index) == set(expected), "missing " + label + " key")
    return index


def validate_input(collection_dir, config_path, freeze_path, *, root=Path.cwd()):
    """Trust the frozen collector's scientific checks; verify its byte-bound contract."""
    root = Path(root).resolve()
    collection_dir = resolve(root, collection_dir)
    config_path, freeze_path = resolve(root, config_path), resolve(root, freeze_path)
    config, freeze = read_json(config_path), read_json(freeze_path)
    cases = fixed_keys(config)
    case_keys = {row["case_key"] for row in cases}
    seed_keys = {(key, arm, seed) for key in case_keys for arm in ARMS for seed in SEEDS}
    prefix_keys = {(key, arm, prefix) for key in case_keys for arm in ARMS for prefix in PREFIXES}
    comparison_keys = {(key, f"{a}/{b}", prefix) for key in case_keys for a, b in COMPARISONS for prefix in PREFIXES}
    validated = {portable(root, config_path): sha256(config_path), portable(root, freeze_path): sha256(freeze_path)}
    require(freeze["status"] == "frozen_after_independent_actual_source_and_configuration_review", "unapproved v2 freeze")
    require(freeze["config_sha256"] == sha256(config_path), "configuration is not the frozen one")
    require(set(freeze["runtime_source_sha256"]) == RUNTIME_PATHS, "the complete 19-source runtime identity is required")
    for field in ("runtime_source_sha256", "original_v1_runtime_source_sha256", "required_artifact_sha256", "archived_data_sha256"):
        verify_hashes(root, freeze[field], validated)
    for entry in freeze["archived_bank_identity"].values():
        verify_hashes(root, {entry["path"]: entry["sha256"]}, validated)
    ledger = freeze["expected_ledger"]
    require(ledger["counts"] == COUNTS and freeze["expected_ledger_sha256"] == content_hash(ledger), "invalid frozen ledger identity")
    frozen_cases = unique_index(ledger["cases"], lambda row: row["case_key"], case_keys, "frozen case")
    for expected in cases:
        require(all(frozen_cases[expected["case_key"]][key] == value for key, value in expected.items()), "frozen case grid differs")
    unique_index(ledger["executions"], lambda row: (row["case_key"], row["arm"], row["seed"]), seed_keys, "frozen execution")
    unique_index(ledger["prefixes"], lambda row: (row["case_key"], row["arm"], row["prefix"]), prefix_keys, "frozen prefix")
    require(len(ledger["setups"]) == len(freeze["archived_bank_identity"]) == 18, "wrong setup identity denominator")
    manifest_path = collection_dir / "collection-manifest.json"
    manifest = read_json(manifest_path)
    validated[portable(root, manifest_path)] = sha256(manifest_path)
    require(manifest["schema_version"] == SCHEMA and manifest["status"] == "complete", "only a complete frozen v2 collection is reportable")
    require(manifest["config_sha256"] == sha256(config_path) and manifest["freeze_sha256"] == sha256(freeze_path), "collection source version differs")
    require(manifest["runtime_source_sha256"] == freeze["runtime_source_sha256"]
            and manifest["expected_ledger_sha256"] == freeze["expected_ledger_sha256"] and manifest["expected_counts"] == COUNTS,
            "collection/freeze source or ledger identities differ")
    require(manifest["case_status_counts"] == {"completed": 54} and manifest["seed_execution_status_counts"] == {"completed": 1944}
            and manifest["seed_execution_rows"] == 1944 and manifest["table_rows"] == {"arm_prefix_rows": 648, "paired_comparison_rows": 810},
            "failed/missing observations cannot produce a complete report")
    require(manifest["v1_or_native_timings_pooled"] is False and manifest["prefixes_are_correlated_not_independent_graph_replicates"] is True,
            "collection interpretation policy differs")
    require(set(manifest["artifact_sha256"]) == {"tables.json", "paired-comparisons.csv"}, "unexpected/missing collection artifact")
    verify_hashes(root, {portable(root, collection_dir / name): digest for name, digest in manifest["artifact_sha256"].items()}, validated)
    verify_hashes(root, manifest["source_raw_sha256"], validated)
    run_dir = resolve(root, manifest["run_dir"])
    inventory = {portable(root, path): sha256(path) for path in run_dir.iterdir() if path.is_file()}
    require(inventory == manifest["source_raw_sha256"] and all(path.is_file() for path in run_dir.iterdir()), "raw inventory changed since collection")
    require(not (run_dir / "run-failed.json").exists(), "a failed run cannot yield a complete report")
    run_manifest, terminal = read_json(run_dir / "run-manifest.json"), read_json(run_dir / "run-completed.json")
    require(run_manifest["config_sha256"] == manifest["config_sha256"] and run_manifest["freeze_sha256"] == manifest["freeze_sha256"]
            and run_manifest["runtime_source_sha256"] == freeze["runtime_source_sha256"] and run_manifest["expected_ledger"] == ledger,
            "raw run manifest differs from the frozen collection")
    require(terminal["status"] == "completed" and terminal["completed_cases"] == 54 and terminal["completed_solver_calls"] == 1944
            and terminal["prefix_summary_count"] == 648 and terminal["expected_counts"] == COUNTS, "raw completion ledger is incomplete")
    selected = unique_index(manifest["case_selection"], lambda row: row["case_key"], case_keys, "source selection")
    tables = read_json(collection_dir / "tables.json")
    require(set(tables) == {"arm_prefix_rows", "paired_comparison_rows", "seed_execution_rows"}, "unexpected/missing table kind")
    arms = unique_index(tables["arm_prefix_rows"], lambda row: (row["case_key"], row["arm"], row["prefix"]), prefix_keys, "arm prefix")
    comparisons = unique_index(tables["paired_comparison_rows"], lambda row: (row["case_key"], row["comparison"], row["prefix"]), comparison_keys, "comparison")
    seeds = unique_index(tables["seed_execution_rows"], lambda row: (row["case_key"], row["arm"], row["seed"]), seed_keys, "seed execution")
    seed_scalars = {}
    for key, row in seeds.items():
        require(row["execution_key"] == f"{key[0]}/{key[1]}/seed{key[2]}" and row["status"] == "completed"
                and row["eligible_for_completed_case_metrics"] is True, "noncomplete/incorrect seed key")
        result = row["raw_and_selected_result"]
        require(result["status"] == "completed" and result["arm"] == key[1] and result["seed"] == key[2], "seed source key differs")
        seed_scalars[key] = {name: result[name] for name in ("raw_original_Q_exact", "returned_Q_exact", "winner_kind", "winner_seed", "discovery_fallback")}
        rational(result["raw_original_Q_exact"])
        rational(result["returned_Q_exact"])
    # Release collector table label vectors before loading any raw case. Their
    # integrity is already bound to the frozen collector and the input SHA.
    tables.pop("seed_execution_rows")
    del seeds
    coverage_rows = []
    for case in cases:
        key = case["case_key"]
        selection = selected[key]
        expected_path = portable(root, run_dir / f"{key}.json.gz")
        require(selection["status"] == "completed" and selection["selected_raw_path"] == expected_path
                and selection["failed_partial_path"] is None and selection["failed_partial_sha256"] is None
                and selection["selected_raw_sha256"] == manifest["source_raw_sha256"][expected_path], "case selection is partial/changed")
        raw = read_json(resolve(root, expected_path))
        require(raw["status"] == "completed" and all(raw[name] == value for name, value in case.items())
                and raw["completed_solver_calls"] == raw["scheduled_solver_calls"] == 36 and raw["prefix_summary_count"] == 12,
                "raw case header is not complete or fixed")
        require(set(raw["arms"]) == set(ARMS) and raw["config_sha256"] == manifest["config_sha256"]
                and raw["freeze_sha256"] == manifest["freeze_sha256"], "raw arm/source identity differs")
        source = {"path": expected_path, "sha256": selection["selected_raw_sha256"]}
        setup_ref = raw["setup_reference"]
        require(setup_ref["path"] == portable(root, run_dir / f"{case['setup_key']}-setup.json.gz")
                and setup_ref["sha256"] == manifest["source_raw_sha256"][setup_ref["path"]], "raw setup SHA differs")
        setup = read_json(resolve(root, setup_ref["path"]))
        require(setup["status"] == "completed" and setup["setup_key"] == case["setup_key"], "raw setup is incomplete")
        original_bank_count = integer(setup["fixed_bank"]["candidate_count"])
        for arm in ARMS:
            state = raw["arms"][arm]
            require(state["status"] == "completed", "raw arm did not complete")
            seed_rows = unique_index(state["seed_results"], lambda row: row["seed"], set(SEEDS), "raw seed")
            prefix_rows = unique_index(state["prefixes"], lambda row: row["prefix"], set(PREFIXES), "raw prefix")
            for seed in SEEDS:
                require(all(seed_rows[seed][name] == value for name, value in seed_scalars[(key, arm, seed)].items()), "seed table does not match frozen raw output")
            provenance = state["provenance"]
            coverage = provenance["coverage"]
            degree = provenance.get("degree_stage")
            mapped = provenance.get("mapped_bank", {}).get("summary")
            statuses = {} if degree is None else degree["status_counts"]
            for name, count in statuses.items():
                require(isinstance(name, str) and name, "invalid degree status name")
                integer(count)
            accepted = None if degree is None else integer(degree["accepted_count"])
            candidates = None if degree is None else integer(degree["candidate_count"])
            if degree is not None:
                require(sum(statuses.values()) == candidates and sum(count for name, count in statuses.items() if name in ACCEPTED_STATUSES) == accepted,
                        "degree status denominator/acceptance count differs")
            if arm == "RD":
                require(isinstance(mapped, dict) and mapped["cap_applied_after_complete_original_bank_mapping"] is True,
                        "missing complete RD mapped-bank provenance")
                for name in ("complete_original_bank_count", "trivial_original_image_count", "unique_nontrivial_images",
                             "duplicate_nontrivial_images_removed", "current_cap_exclusions", "admissible_current_images", "max_block_size"):
                    integer(mapped[name])
                require(mapped["complete_original_bank_count"] == original_bank_count
                        == mapped["trivial_original_image_count"] + mapped["unique_nontrivial_images"] + mapped["duplicate_nontrivial_images_removed"]
                        and mapped["unique_nontrivial_images"] == mapped["current_cap_exclusions"] + mapped["admissible_current_images"]
                        == candidates and mapped["max_block_size"] == 64, "RD mapped-bank denominator accounting differs")
            for prefix in PREFIXES:
                row = arms[(key, arm, prefix)]
                result = prefix_rows[prefix]
                require(row["status"] == "completed" and row["source_raw_reference"] == source
                        and row["dataset"] == case["dataset"] and row["discovery_seed"] == case["discovery_seed"] and row["gamma"] == case["gamma"],
                        "arm table source identity differs")
                rational(row["returned_Q_exact"])
                require(row["returned_Q_exact"] == result["returned_Q_exact"] and row["phase_costs"] == result["cost"]
                        and row["constructed_standalone_seconds"] == result["cost"]["constructed_standalone_seconds"]
                        and row["coverage"] == coverage and row["degree_status_counts"] == (None if degree is None else statuses)
                        and row["mapped_bank_denominators"] == mapped
                        and row["additional_removed_vertices_after_r"] == provenance.get("additional_removed_vertices_after_r"),
                        "arm table metrics differ from frozen raw provenance")
                number(row["constructed_standalone_seconds"])
            lcc = coverage["largest_component_under_original_objective"]
            n, remaining = integer(coverage["original_vertices"]), integer(coverage["remaining_vertices"])
            removed = integer(coverage["removed_vertices"])
            require(n > 0 and removed == n - remaining, "coverage denominator differs")
            positive_n = integer(coverage["positive_degree_original_vertices"])
            positive_removed = integer(coverage["positive_degree_removed_vertices"])
            coverage_rows.append({**case, "arm": arm, "original_vertices": n, "remaining_vertices": remaining,
                "removed_vertices": removed, "removed_fraction": coverage["removed_fraction"],
                "positive_degree_original_vertices": positive_n, "positive_degree_removed_vertices": positive_removed,
                "positive_degree_removed_fraction": None if positive_n == 0 else positive_removed / positive_n,
                "largest_component_original_vertices": integer(lcc["vertices"]), "largest_component_removed_vertices": integer(lcc["removed_vertices"]),
                "largest_component_removed_fraction": lcc["removed_fraction"],
                "remaining_off_diagonal_edges": integer(provenance["graph_counts"]["off_diagonal_edges"]),
                "remaining_loop_count": integer(provenance["graph_counts"]["loop_count"]),
                "additional_removed_vertices_after_r": provenance.get("additional_removed_vertices_after_r"),
                "complete_original_bank_count": original_bank_count, "degree_applicable": degree is not None,
                "degree_candidate_count": candidates, "degree_accepted_count": accepted,
                "degree_nonaccepted_count": None if candidates is None else candidates - accepted,
                "degree_status_counts": statuses, "mapped_bank_denominators": mapped, "source_raw_reference": source})
        del raw
    for key, row in comparisons.items():
        case_key, comparison, prefix = key
        a, b = comparison.split("/")
        left, right = arms[(case_key, a, prefix)], arms[(case_key, b, prefix)]
        require(row["status"] == "completed" and row["arm_A"] == a and row["arm_B"] == b
                and row["source_raw_reference"] == left["source_raw_reference"]
                and all(row[name] == left[name] for name in ("dataset", "gamma", "discovery_seed")), "comparison source/arm differs")
        qa, qb = rational(left["returned_Q_exact"]), rational(right["returned_Q_exact"])
        require(row["returned_Q_A_exact"] == left["returned_Q_exact"] and row["returned_Q_B_exact"] == right["returned_Q_exact"]
                and rational(row["returned_Q_A_minus_B_exact"]) == qa - qb and row["quality_matched"] is (qa == qb), "exact comparison quality differs")
        ta, tb = left["constructed_standalone_seconds"], right["constructed_standalone_seconds"]
        ratio, speedup = (None if tb == 0 else ta / tb), (None if ta == 0 else tb / ta)
        require(row["total_cost_A_over_B"] == ratio and row["speedup_B_over_A"] == speedup
                and row["quality_matched_speedup_B_over_A"] == (speedup if qa == qb else None), "comparison cost ratio differs")
        number(row["total_cost_A_over_B"], nullable=True)
        number(row["speedup_B_over_A"], nullable=True)
    return {"manifest": manifest, "cases": cases, "comparison_rows": list(comparisons.values()),
            "coverage_rows": coverage_rows, "validated_input_sha256": validated,
            "config_path": portable(root, config_path), "freeze_path": portable(root, freeze_path),
            "collection_dir": portable(root, collection_dir)}


COVERAGE_METRICS = ("original_vertices", "remaining_vertices", "removed_vertices", "removed_fraction",
                    "positive_degree_original_vertices", "positive_degree_removed_vertices", "positive_degree_removed_fraction",
                    "largest_component_original_vertices", "largest_component_removed_vertices", "largest_component_removed_fraction",
                    "remaining_off_diagonal_edges", "remaining_loop_count", "additional_removed_vertices_after_r",
                    "complete_original_bank_count", "degree_candidate_count", "degree_accepted_count", "degree_nonaccepted_count")


def summarize_comparisons(rows):
    groups = []
    for dataset in DATASETS:
        for gamma in GAMMAS:
            for a, b in COMPARISONS:
                for prefix in PREFIXES:
                    group = sorted((row for row in rows if row["dataset"] == dataset and rational(row["gamma"]) == gamma
                                    and row["comparison"] == f"{a}/{b}" and row["prefix"] == prefix), key=lambda row: row["discovery_seed"])
                    require([row["discovery_seed"] for row in group] == list(DISCOVERY_SEEDS), "comparison group needs all three fixed discovery seeds")
                    differences = [rational(row["returned_Q_A_minus_B_exact"]) for row in group]
                    times = [row["total_cost_A_over_B"] for row in group]
                    matched = [row for row in group if row["quality_matched"]]
                    seeds = [{"discovery_seed": row["discovery_seed"], "case_key": row["case_key"],
                              "returned_Q_A_exact": row["returned_Q_A_exact"], "returned_Q_B_exact": row["returned_Q_B_exact"],
                              "returned_Q_A_minus_B_exact": row["returned_Q_A_minus_B_exact"], "speedup_B_over_A": row["speedup_B_over_A"],
                              "time_ratio_A_over_B": row["total_cost_A_over_B"],
                              "quality_matched": row["quality_matched"], "quality_matched_speedup_B_over_A": row["quality_matched_speedup_B_over_A"],
                              "source_raw_reference": row["source_raw_reference"]} for row in group]
                    groups.append({"dataset": dataset, "gamma": rational_record(gamma), "comparison": f"{a}/{b}", "prefix": prefix,
                        "discovery_seed_denominator": 3, "per_seed": seeds,
                        "speedup_B_over_A": stats([row["speedup_B_over_A"] for row in group]),
                        "time_ratio_A_over_B": stats(times),
                        "time_A_relative_to_B_counts": {"slower": sum(value is not None and value > 1 for value in times),
                            "equal": sum(value == 1 for value in times),
                            "faster": sum(value is not None and value < 1 for value in times),
                            "undefined": sum(value is None for value in times)},
                        "returned_Q_A_exact": stats([rational(row["returned_Q_A_exact"]) for row in group], exact=True),
                        "returned_Q_B_exact": stats([rational(row["returned_Q_B_exact"]) for row in group], exact=True),
                        "returned_Q_A_minus_B_exact": stats(differences, exact=True),
                        "quality_matched_seed_count": len(matched),
                        "quality_matched_speedup_B_over_A": stats([row["quality_matched_speedup_B_over_A"] for row in matched]),
                        "Q_difference_sign_counts": {"positive": sum(value > 0 for value in differences),
                                                     "zero": sum(value == 0 for value in differences),
                                                     "negative": sum(value < 0 for value in differences)},
                        "quality_A_relative_to_B_counts": {"better": sum(value > 0 for value in differences),
                            "equal": sum(value == 0 for value in differences), "worse": sum(value < 0 for value in differences)}})
    return groups


def summarize_coverage(rows):
    groups = []
    for dataset in DATASETS:
        for gamma in GAMMAS:
            for arm in ARMS:
                group = sorted((row for row in rows if row["dataset"] == dataset and rational(row["gamma"]) == gamma
                                and row["arm"] == arm), key=lambda row: row["discovery_seed"])
                require([row["discovery_seed"] for row in group] == list(DISCOVERY_SEEDS), "coverage group needs all three fixed discovery seeds")
                names = sorted({name for row in group for name in row["degree_status_counts"]})
                statuses = {name: {"per_seed": [{"discovery_seed": row["discovery_seed"], "count": row["degree_status_counts"].get(name, 0)}
                                               for row in group], "counts": stats([row["degree_status_counts"].get(name, 0) for row in group]),
                                    "total_decisions_across_three_fixed_seeds": sum(row["degree_status_counts"].get(name, 0) for row in group),
                                    "acceptance_status": name in ACCEPTED_STATUSES} for name in names}
                mapped = [row["mapped_bank_denominators"] for row in group]
                mapped_metrics = {}
                if arm == "RD":
                    for name in ("complete_original_bank_count", "trivial_original_image_count", "unique_nontrivial_images",
                                 "duplicate_nontrivial_images_removed", "current_cap_exclusions", "admissible_current_images"):
                        mapped_metrics[name] = stats([value[name] for value in mapped])
                groups.append({"dataset": dataset, "gamma": rational_record(gamma), "arm": arm, "discovery_seed_denominator": 3,
                    "per_seed": group, "metrics": {name: stats([row[name] for row in group]) for name in COVERAGE_METRICS},
                    "degree_applicable_seed_count": sum(row["degree_applicable"] for row in group),
                    "degree_statuses": statuses, "mapped_bank_metrics": mapped_metrics,
                    "mapped_bank_policy": {"max_block_size": 64, "cap_after_complete_original_mapping": True} if arm == "RD" else None})
    return groups


def write_json_once(path, value):
    with Path(path).open("xb") as target:
        target.write(json_bytes(value))


def write_csv_once(path, rows):
    require(bool(rows), "empty report table")
    fields = list(rows[0])
    require(all(set(row) == set(fields) for row in rows), "inconsistent CSV row schema")
    with Path(path).open("x", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                             if isinstance(value, (dict, list)) else value for name, value in row.items()})


def build_report(collection_dir=DEFAULT_COLLECTION, config_path=DEFAULT_CONFIG, freeze_path=DEFAULT_FREEZE,
                 output_dir=DEFAULT_OUTPUT, *, root=Path.cwd()):
    root = Path(root).resolve()
    output = resolve(root, output_dir)
    require(not output.exists(), "report output namespace already exists; refusing overwrite")
    program = Path(__file__).resolve()
    source_hash = sha256(program)
    data = validate_input(collection_dir, config_path, freeze_path, root=root)
    comparison_groups = summarize_comparisons(data["comparison_rows"])
    coverage_groups = summarize_coverage(data["coverage_rows"])
    require(len(comparison_groups) == 270 and len(coverage_groups) == 72 and len(data["coverage_rows"]) == 216, "summary denominator differs")
    verify_hashes(root, data["validated_input_sha256"], {})
    require(source_hash == sha256(program), "analysis source changed during report construction")
    timestamp = datetime.now(timezone.utc).isoformat()
    summary = {"schema_version": "public-pipelines-v2-descriptive-report-v1", "status": "complete", "created_at_utc": timestamp,
        "input_collection_dir": data["collection_dir"], "config_path": data["config_path"], "freeze_path": data["freeze_path"],
        "expected_counts": COUNTS, "paired_comparison_rows": 810, "comparison_groups": comparison_groups,
        "coverage_groups": coverage_groups, "coverage_case_arm_rows": 216,
        "interpretation": {"speedup_B_over_A": "T_B/T_A, constructed standalone single-resolution costs",
            "time_ratio_A_over_B": "T_A/T_B; reciprocal of speedup when both costs are positive; null when T_B=0",
            "time_outcome_counts": "three fixed seeds, classified by T_A/T_B relative to 1; undefined when T_B=0",
            "Q_difference": "exact returned Q_A minus returned Q_B; no tolerance or float rounding",
            "quality_matched": "exact equal returned rational Q; its own n, null values when n=0",
            "replication": "three fixed discovery seeds per graph/resolution; six observed graphs",
            "prefixes": "correlated summaries of the same nine downstream calls, not independent replicates",
            "coverage": "original full graph and original largest-component supplement under the same original objective",
            "degree_nonaccepted": "retained rejection/abstention/cap/zero-degree statuses; not all are mathematical rejections",
            "v1_or_native_timings_pooled": False, "hypothesis_tests_or_population_inference": False,
            "per_arm_peak_memory": "not_measured"}, "provenance_path": portable(root, output / "report-provenance.json"),
        "scientific_novelty_or_venue_approval": False}
    # All validation/aggregation has succeeded before any output is created.
    output.mkdir(parents=True, exist_ok=False)
    write_json_once(output / "summary.json", summary)
    write_csv_once(output / "comparison_seed_rows.csv", [{**row, "time_ratio_A_over_B": row["total_cost_A_over_B"]}
                                                        for row in data["comparison_rows"]])
    write_csv_once(output / "comparison_aggregate_rows.csv", comparison_groups)
    write_csv_once(output / "coverage_seed_rows.csv", data["coverage_rows"])
    write_csv_once(output / "coverage_aggregate_rows.csv", coverage_groups)
    report = ("# Public pipeline v2 descriptive results\n\n"
              "The frozen collection is complete: 54 cases, 216 arm states, 1,944 scheduled solver calls and 648 prefix summaries. "
              "All six full graphs and all three discovery seeds appear in the 810 paired rows.\n\n"
              "The summary contains 270 graph/resolution/comparison/prefix groups and 72 graph/resolution/arm coverage groups. "
              "Each group preserves the three seed values and median/min/max. Absolute Q and Q differences remain reduced rational values. "
              "Quality-matched speedups use only seeds with exactly equal returned Q; empty subsets have n=0 and null statistics.\n\n"
              "Coverage uses one case/arm observation rather than repeating it across prefixes. RD additional removals, complete mapped-bank denominators "
              "and every D/RD degree-decision status are retained. The largest-component supplement uses the original full-graph objective.\n\n"
              "Speedup B/A means constructed T_B/T_A; time ratio A/B means T_A/T_B. Slower/equal/faster/undefined and "
              "quality worse/equal/better counts retain the three-seed denominator. No relative Q ratio is formed. "
              "The three prefixes share nine solver executions and are correlated. "
              "No v1/native time is pooled, no p-value is computed, and per-arm peak memory is not measured.\n\n"
              "See summary.json and the four CSV tables; report-provenance.json binds this analysis source, all validated inputs and the output bytes.\n")
    with (output / "report.md").open("x", encoding="utf-8") as target:
        target.write(report)
    artifact_hashes = {path.name: sha256(path) for path in sorted(output.iterdir())}
    provenance = {"schema_version": "public-pipelines-v2-report-provenance-v1", "status": "complete", "created_at_utc": timestamp,
        "analysis_source_path": program.relative_to(root).as_posix() if program.is_relative_to(root) else "analysis/public_pipelines_v2_report.py",
        "analysis_source_sha256": source_hash, "validated_input_sha256": data["validated_input_sha256"],
        "input_collection_dir": data["collection_dir"], "artifact_sha256": artifact_hashes,
        "graph_solver_certificate_or_timing_reexecuted": False, "standard_library_only": True,
        "scientific_novelty_or_venue_approval": False}
    write_json_once(output / "report-provenance.json", provenance)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-dir", default=DEFAULT_COLLECTION)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--freeze", default=DEFAULT_FREEZE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = build_report(args.collection_dir, args.config, args.freeze, args.output_dir)
    except (ReportError, OSError, KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
        parser.exit(2, "Report refused: " + str(error) + "\n")
    print(json.dumps({"status": result["status"], "comparison_groups": len(result["comparison_groups"]),
                      "coverage_groups": len(result["coverage_groups"]), "output": args.output_dir}))


if __name__ == "__main__":
    main()
