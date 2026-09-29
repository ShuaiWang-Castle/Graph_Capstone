"""Ledger-first strict collection, including every failed/unlaunched denominator."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import io
import json
import math
from pathlib import Path

from .contracts import (ARMS, ARM_PHASES, COMMON_PHASES, PHASES, SCHEMA, SEED_PHASES, canonical_partition,
                        content_hash, groups_from_membership, integer_labels, rational_record,
                        rational_value, read_json, sha256, utc_now, write_once)
from .freeze import CONFIG_PATH, NAMESPACE, validate_freeze
from .schedule import DOWNSTREAM_SEEDS, PREFIXES
from .stages import bank_identity


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_identity(record, manifest):
    require(record.get("schema_version") == SCHEMA, "record schema differs from freeze")
    for key in ("config_sha256", "freeze_sha256", "runtime_source_manifest_sha256", "expected_ledger_sha256", "versions"):
        require(record.get(key) == manifest[key], f"record identity differs: {key}")


def validate_setup(record, setup_expected, manifest, freeze):
    validate_identity(record, manifest)
    require(record["status"] == "completed", "a partial setup is not successful input evidence")
    for name in ("setup_key", "dataset", "discovery_seed"):
        require(record[name] == setup_expected[name], "setup belongs to another expected key")
    bank = record["fixed_bank"]
    expected = freeze["archived_bank_identity"][setup_expected["setup_key"]]
    require(record["archived_v1_bank_reference"] == expected, "setup changed its original bank reference")
    archived = read_json(expected["path"])
    require(bank["blocks"] == archived["blocks"] and bank["discovery_labels"] == archived["discovery_labels"],
            "setup bank/discovery differs from the independently archived v1 identity")
    require(bank["bank_sha256"] == bank_identity(bank["blocks"]) == archived["bank_sha256"], "setup bank hash mismatch")
    original = record["original"]
    n = original["graph_counts"]["vertices"]
    integer_labels(bank["discovery_labels"], n)
    require(len(original["degrees_exact"]) == n and sum(original["degrees_exact"]) == original["S_exact"] > 0,
            "setup original degree/volume contract differs")
    require(record["dataset_metadata"] == archived["dataset"], "setup full dataset processing changed")
    require(bank["discovery_partition_sha256"] == content_hash(canonical_partition(bank["discovery_labels"])),
            "setup discovery partition identity differs")


def _phase_sum(records, names, *, arm=None, seeds=None, prefix=None):
    return sum(row["seconds"] for row in records if row["phase"] in names and row.get("arm") == arm
               and row["status"] == "completed" and (seeds is None or row.get("seed") in seeds)
               and (prefix is None or row.get("prefix") == prefix))


def validate_case(record, expected, setup, manifest):
    validate_identity(record, manifest)
    require(record["status"] == "completed", "partial/failed case cannot yield successful metrics")
    for key in ("case_key", "dataset", "discovery_seed", "gamma", "case_ordinal", "setup_key",
                "preprocessing_order", "downstream_order"):
        require(record[key] == expected[key], f"case differs from frozen expected ledger: {key}")
    require(set(record["arms"]) == set(ARMS), "unknown/missing arm")
    require(record["completed_solver_calls"] == record["scheduled_solver_calls"] == 36
            and record["prefix_summary_count"] == 12, "complete case has incomplete call counts")
    require(record["gc_policy"] == "normal_enabled_no_manual_collect"
            and record["per_arm_peak_memory"] == "not_measured", "memory/GC policy changed")
    n = setup["original"]["graph_counts"]["vertices"]
    discovery_labels = integer_labels(setup["fixed_bank"]["discovery_labels"], n)
    discovery_q = rational_value(record["discovery_original_Q_exact"])
    records = record["primary_phase_records"]
    for row in records:
        require(row["phase"] in PHASES and row.get("arm") in (None,) + ARMS, "unknown primary phase/arm")
        require(row["status"] in {"completed", "not_applicable"}, "complete case contains failed primary phase")
        if row["status"] == "completed":
            require(isinstance(row["seconds"], (int, float)) and math.isfinite(row["seconds"]) and row["seconds"] >= 0,
                    "invalid primary phase time")
        else:
            require(row["seconds"] is None, "inapplicable phase cannot have a measured successful duration")
    # Check measured outer intervals within their physical domain. Candidate
    # B-F/F are an explicit duration partition, not invented contiguous intervals.
    intervals = {}
    for row in records:
        if row.get("attribution") == "measured_outer_interval":
            start, end = row["start_offset_seconds"], row["end_offset_seconds"]
            require(end >= start >= 0 and abs((end - start) - row["seconds"]) <= 1e-8,
                    "outer interval endpoints differ from duration")
            intervals.setdefault(row["interval_domain"], []).append((start, end))
    for domain, times in intervals.items():
        times.sort()
        require(all(left[1] <= right[0] for left, right in zip(times, times[1:])), f"overlapping primary intervals: {domain}")
    for phase in COMMON_PHASES + ("fixed_bank_refinement",):
        require(any(row["phase"] == phase and row.get("arm") is None and row["status"] == "completed" for row in records),
                f"common required phase missing: {phase}")
    common = _phase_sum(records, COMMON_PHASES)
    refinement = _phase_sum(records, ("fixed_bank_refinement",))
    for arm in ARMS:
        state = record["arms"][arm]
        require(state["status"] == "completed", "complete case has unfinished arm")
        provenance = state["provenance"]
        membership = integer_labels(provenance["operational_membership"], n)
        groups = groups_from_membership(membership, provenance["graph_counts"]["vertices"])
        require([list(group) for group in groups] == provenance["original_groups"], "operational groups do not match IDs")
        require(provenance["original_partition_sha256"] == content_hash(canonical_partition(membership)), "partition hash differs")
        require(provenance["gamma_exact"] == str(rational_value(record["gamma"])), "arm gamma changed")
        require(provenance["graph_counts"]["S_exact"] == setup["original"]["S_exact"], "arm total volume differs")
        require([row["seed"] for row in state["seed_results"]] == list(DOWNSTREAM_SEEDS), "unknown/duplicate/missing seed")
        require([row["prefix"] for row in state["prefixes"]] == list(PREFIXES), "unknown/duplicate/missing prefix")
        for phase in ARM_PHASES:
            entries = [row for row in records if row["phase"] == phase and row.get("arm") == arm]
            require(len(entries) == 1, f"missing/duplicated arm primary phase: {arm}/{phase}")
        scores = []
        for seed_record in state["seed_results"]:
            seed = seed_record["seed"]
            require(seed_record["arm"] == arm and seed_record["status"] == "completed", "seed belongs to another/failed arm")
            raw_labels = integer_labels(seed_record["raw_solver_labels"], len(groups))
            raw_original = integer_labels(seed_record["raw_original_labels"], n)
            require(raw_original == tuple(raw_labels[v] for v in membership), "raw labels were lifted through wrong IDs")
            raw_q = rational_value(seed_record["raw_original_Q_exact"])
            require(raw_q == rational_value(seed_record["raw_quotient_Q_exact"]), "raw quotient/original exact objectives differ")
            selected_q = rational_value(seed_record["returned_Q_exact"])
            require(selected_q == max(raw_q, discovery_q), "per-seed external fallback chose the wrong exact Q")
            fallback = raw_q <= discovery_q
            require(seed_record["discovery_fallback"] == fallback and seed_record["louvain_initial_partition_supplied"] is False,
                    "fallback/warm-start policy changed")
            expected_labels = discovery_labels if fallback else raw_original
            require(tuple(seed_record["returned_original_labels"]) == expected_labels, "actual selected output was not preserved")
            require(seed_record["winner_kind"] == ("discovery" if fallback else "downstream_seed")
                    and seed_record["winner_seed"] == (None if fallback else seed), "seed tie/winner metadata differs")
            for phase in SEED_PHASES:
                require(sum(row["phase"] == phase and row.get("arm") == arm and row.get("seed") == seed
                            and row["status"] == "completed" for row in records) == 1, "missing/duplicated seed compute interval")
            scores.append(raw_q)
        for result in state["prefixes"]:
            k = result["prefix"]
            require(result["arm"] == arm and result["status"] == "completed", "prefix belongs to another/failed arm")
            best = max([discovery_q] + scores[:k])
            winner = None if best == discovery_q else next(i for i, score in enumerate(scores[:k]) if score == best)
            require(rational_value(result["returned_Q_exact"]) == best, "prefix exact Q differs from fixed maximum")
            require(result["winner_kind"] == ("discovery" if winner is None else "downstream_seed")
                    and result["winner_seed"] == (None if winner is None else DOWNSTREAM_SEEDS[winner]), "prefix tie policy changed")
            expected_labels = discovery_labels if winner is None else tuple(state["seed_results"][winner]["raw_original_labels"])
            require(tuple(result["returned_original_labels"]) == expected_labels, "prefix returned labels differ from actual winner")
            require(result["raw_seed_Q_exact"] == [rational_record(score) for score in scores[:k]], "prefix raw-score provenance differs")
            count = sum(score <= discovery_q for score in scores[:k])
            require(result["fallback_count"] == count and result["fallback_frequency"] == count / k, "fallback denominator differs")
            require(sum(row["phase"] == "prefix_finalize" and row.get("arm") == arm and row.get("prefix") == k
                        and row["status"] == "completed" for row in records) == 1, "prefix finalization timer differs")
            charged = result["cost"]
            parts = {"common_seconds": common, "fixed_bank_refinement_seconds": 0.0 if arm == "U" else refinement,
                     "arm_preparation_seconds": _phase_sum(records, ARM_PHASES, arm=arm),
                     "seed_compute_seconds": _phase_sum(records, SEED_PHASES, arm=arm, seeds=DOWNSTREAM_SEEDS[:k]),
                     "prefix_finalize_seconds": _phase_sum(records, ("prefix_finalize",), arm=arm, prefix=k)}
            require(all(charged[key] == value for key, value in parts.items())
                    and charged["constructed_standalone_seconds"] == math.fsum(parts.values()), "standalone cost does not match disjoint phases")
    r, rd = record["arms"]["R"]["provenance"], record["arms"]["RD"]["provenance"]
    require(r["r_prefix_partition_sha256"] == rd["r_prefix_partition_sha256"]
            and rd["independent_r_prefix_partition_equality_verified"] is True, "independent R-prefix equality missing")
    require(rd["additional_removed_vertices_after_r"] == r["graph_counts"]["vertices"] - rd["graph_counts"]["vertices"] >= 0,
            "RD incremental removal differs from its sequential quotient")


def derive_prefix_tables(case_rows, cases):
    arm_rows, comparisons = [], []
    for expected in case_rows:
        key = expected["case_key"]
        record = cases.get(key)
        for k in PREFIXES:
            values = {}
            for arm in ARMS:
                source = None if record is None else record["arms"][arm]
                value = None if source is None else next(row for row in source["prefixes"] if row["prefix"] == k)
                row = {"case_key": key, "dataset": expected["dataset"], "discovery_seed": expected["discovery_seed"],
                       "gamma": expected["gamma"], "arm": arm, "prefix": k,
                       "status": "unavailable" if value is None else "completed",
                       "unavailable_reason": "case not fully completed under this frozen version" if value is None else None,
                       "returned_Q_exact": None if value is None else value["returned_Q_exact"],
                       "constructed_standalone_seconds": None if value is None else value["cost"]["constructed_standalone_seconds"],
                       "phase_costs": None if value is None else value["cost"],
                       "winner_kind": None if value is None else value["winner_kind"],
                       "winner_seed": None if value is None else value["winner_seed"],
                       "fallback_count": None if value is None else value["fallback_count"],
                       "fallback_frequency": None if value is None else value["fallback_frequency"],
                       "raw_seed_Q_exact": None if value is None else value["raw_seed_Q_exact"],
                       "coverage": None if source is None else source["provenance"]["coverage"],
                       "degree_status_counts": None if source is None else source["provenance"].get("degree_stage", {}).get("status_counts"),
                       "mapped_bank_denominators": None if source is None else source["provenance"].get("mapped_bank", {}).get("summary"),
                       "additional_removed_vertices_after_r": None if source is None else source["provenance"].get("additional_removed_vertices_after_r"),
                       "source_raw_reference": None if record is None else record["collection_source_reference"]}
                arm_rows.append(row)
                values[arm] = row
            for a, b in (("D", "U"), ("R", "U"), ("RD", "U"), ("D", "R"), ("RD", "R")):
                left, right = values[a], values[b]
                available = left["status"] == right["status"] == "completed"
                ql = None if not available else rational_value(left["returned_Q_exact"])
                qr = None if not available else rational_value(right["returned_Q_exact"])
                tl = None if not available else left["constructed_standalone_seconds"]
                tr = None if not available else right["constructed_standalone_seconds"]
                comparisons.append({"case_key": key, "dataset": expected["dataset"], "discovery_seed": expected["discovery_seed"],
                    "gamma": expected["gamma"], "prefix": k, "comparison": f"{a}/{b}", "arm_A": a, "arm_B": b,
                    "status": "completed" if available else "unavailable", "returned_Q_A_exact": left["returned_Q_exact"],
                    "returned_Q_B_exact": right["returned_Q_exact"],
                    "returned_Q_A_minus_B_exact": None if not available else rational_record(ql - qr),
                    "total_cost_A_over_B": None if not available or tr == 0 else tl / tr,
                    "speedup_B_over_A": None if not available or tl == 0 else tr / tl,
                    "quality_matched": None if not available else ql == qr,
                    "quality_matched_speedup_B_over_A": None if not available or ql != qr or tl == 0 else tr / tl,
                    "lower_quality_outcome_is_not_labeled_quality_preserving": True,
                    "source_raw_reference": left["source_raw_reference"]})
    return {"arm_prefix_rows": arm_rows, "paired_comparison_rows": comparisons}


def collect_records(config_path, freeze_path, run_dir, output_dir):
    config, freeze = validate_freeze(config_path, freeze_path, require_threads=False)
    run_dir, output_dir = Path(run_dir), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("collection selection and evidence records are write-once")
    manifest_path = run_dir / "run-manifest.json"
    manifest = read_json(manifest_path)
    require(manifest["freeze_sha256"] == sha256(freeze_path) and manifest["config_sha256"] == sha256(config_path),
            "run manifest belongs to another frozen version")
    require(manifest["runtime_source_sha256"] == freeze["runtime_source_sha256"]
            and manifest["expected_ledger"] == freeze["expected_ledger"], "run changed the expected frozen source/grid")
    expected = freeze["expected_ledger"]
    allowed = {"run-manifest.json", "run-completed.json", "run-failed.json"}
    for setup in expected["setups"]:
        key = setup["setup_key"]
        allowed.update({f"{key}-setup-started.json", f"{key}-setup-completed.json", f"{key}-setup.json.gz",
                        f"{key}-setup-failed-partial.json.gz"})
    for case in expected["cases"]:
        key = case["case_key"]
        allowed.update({f"{key}-started.json", f"{key}-completed.json", f"{key}.json.gz", f"{key}-failed-partial.json.gz"})
        allowed.update(f"{key}-progress-{i:03d}.json" for i in range(1, 41))
    require(all(path.is_file() and path.name in allowed for path in run_dir.iterdir()),
            "unexpected raw path could hide an unlisted case/repeat/source version")
    source_files = {str(path): sha256(path) for path in sorted(run_dir.iterdir()) if path.is_file()}
    setups = {}
    for setup in expected["setups"]:
        path = run_dir / f"{setup['setup_key']}-setup.json.gz"
        if path.exists():
            record = read_json(path)
            validate_setup(record, setup, manifest, freeze)
            done = read_json(run_dir / f"{setup['setup_key']}-setup-completed.json")
            validate_identity(done, manifest)
            require(done["status"] == "completed" and done["record"]["path"] == str(path)
                    and done["record"]["sha256"] == sha256(path), "setup completion marker does not bind its raw bytes")
            setups[setup["setup_key"]] = record
    cases, selections, seed_rows = {}, [], []
    for case in expected["cases"]:
        path = run_dir / f"{case['case_key']}.json.gz"
        failure_path = run_dir / f"{case['case_key']}-failed-partial.json.gz"
        if path.exists():
            require(not failure_path.exists(), "a case cannot be selected from both success and failure records")
            require(case["setup_key"] in setups, "complete case has no complete frozen setup")
            record = read_json(path)
            require(record["setup_reference"]["path"] == str(run_dir / f"{case['setup_key']}-setup.json.gz")
                    and record["setup_reference"]["sha256"] == sha256(record["setup_reference"]["path"]), "setup reference mismatch")
            validate_case(record, case, setups[case["setup_key"]], manifest)
            done_path = run_dir / f"{case['case_key']}-completed.json"
            done = read_json(done_path)
            validate_identity(done, manifest)
            require(done["status"] == "completed" and done["record"]["path"] == str(path)
                    and done["record"]["sha256"] == sha256(path), "completion marker does not bind successful raw bytes")
            record["collection_source_reference"] = {"path": str(path), "sha256": sha256(path)}
            cases[case["case_key"]] = record
            status = "completed"
        else:
            status = "failed" if failure_path.exists() else "not_executed"
            if failure_path.exists():
                partial = read_json(failure_path)
                validate_identity(partial, manifest)
                require(partial["status"] == "failed" and partial["case_key"] == case["case_key"], "wrong failed partial identity")
        selections.append({"case_key": case["case_key"], "status": status,
                           "selected_raw_path": str(path) if status == "completed" else None,
                           "selected_raw_sha256": sha256(path) if status == "completed" else None,
                           "failed_partial_path": str(failure_path) if failure_path.exists() else None,
                           "failed_partial_sha256": sha256(failure_path) if failure_path.exists() else None,
                           "fixed_selection_policy": "unique complete current frozen-version record; no partial case success or repeat selection"})
        for seed in DOWNSTREAM_SEEDS:
            for arm in ARMS:
                value = None if status != "completed" else next(row for row in record["arms"][arm]["seed_results"] if row["seed"] == seed)
                seed_rows.append({"execution_key": f"{case['case_key']}/{arm}/seed{seed}", "case_key": case["case_key"],
                                  "arm": arm, "seed": seed, "status": "completed" if value is not None else
                                    "unavailable_after_case_failure" if status == "failed" else "not_executed",
                                  "raw_and_selected_result": value, "eligible_for_completed_case_metrics": value is not None})
    complete = run_dir / "run-completed.json"
    failed = run_dir / "run-failed.json"
    require(not (complete.exists() and failed.exists()), "run has contradictory terminal outcomes")
    if complete.exists():
        terminal = read_json(complete)
        validate_identity(terminal, manifest)
        require(terminal["status"] == "completed" and len(cases) == 54 and len(setups) == 18
                and terminal["completed_solver_calls"] == 1944 and terminal["prefix_summary_count"] == 648,
                "run completion counts differ from full expected ledger")
    else:
        require(failed.exists(), "run has not reached an immutable terminal outcome")
        terminal = read_json(failed)
        validate_identity(terminal, manifest)
        require(terminal["status"] == "halted_for_recorded_source_repair", "unknown failure terminal status")
    # Progress sidecars independently expose actual global call order.
    for case in expected["cases"]:
        if case["case_key"] not in cases:
            continue
        progress = [read_json(path) for path in sorted(run_dir.glob(f"{case['case_key']}-progress-*.json"))]
        require([row["sequence"] for row in progress] == list(range(1, 41)), "complete case progress sidecars are missing/duplicated")
        for row in progress:
            validate_identity(row, manifest)
        actual_prepare = [row["arm"] for row in progress if row["phase"] == "arm_prepared"]
        actual_seeds = [(row["seed"], row["arm"]) for row in progress if row["phase"] == "seed_completed"]
        require(actual_prepare == case["preprocessing_order"] and actual_seeds == [(row["seed"], arm)
                for row in case["downstream_order"] for arm in row["arms"]], "actual execution order differs from frozen schedule")
    tables = derive_prefix_tables(expected["cases"], cases)
    require(len(seed_rows) == 1944 and len(tables["arm_prefix_rows"]) == 648
            and len(tables["paired_comparison_rows"]) == 810, "collection dropped fixed-grid denominators")
    require(source_files == {str(path): sha256(path) for path in sorted(run_dir.iterdir()) if path.is_file()},
            "raw files changed during collection validation")
    output_dir.mkdir(parents=True, exist_ok=False)
    write_once(output_dir / "tables.json", {**tables, "seed_execution_rows": seed_rows})
    # A compact comparison CSV complements the exact rational JSON table.
    csv_rows = []
    for row in tables["paired_comparison_rows"]:
        flat = dict(row)
        for key, value in flat.items():
            if isinstance(value, dict):
                flat[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        csv_rows.append(flat)
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(csv_rows[0]))
    writer.writeheader()
    writer.writerows(csv_rows)
    with (output_dir / "paired-comparisons.csv").open("x", encoding="utf-8", newline="") as target:
        target.write(text.getvalue())
    record = {"schema_version": SCHEMA, "created_at_utc": utc_now(), "status": "complete" if len(cases) == 54 else "partial_with_failure_denominators",
              "run_dir": str(run_dir), "config_sha256": sha256(config_path), "freeze_sha256": sha256(freeze_path),
              "runtime_source_sha256": freeze["runtime_source_sha256"], "source_raw_sha256": source_files,
              "expected_ledger_sha256": freeze["expected_ledger_sha256"], "expected_counts": expected["counts"],
              "case_status_counts": dict(Counter(row["status"] for row in selections)), "case_selection": selections,
              "seed_execution_status_counts": dict(Counter(row["status"] for row in seed_rows)),
              "table_rows": {key: len(value) for key, value in tables.items()}, "seed_execution_rows": len(seed_rows),
              "artifact_sha256": {"tables.json": sha256(output_dir / "tables.json"),
                                   "paired-comparisons.csv": sha256(output_dir / "paired-comparisons.csv")},
              "prefixes_are_correlated_not_independent_graph_replicates": True,
              "v1_or_native_timings_pooled": False, "scientific_novelty_or_venue_approval": False}
    write_once(output_dir / "collection-manifest.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--freeze", default=str(NAMESPACE / "freeze.json"))
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    record = collect_records(args.config, args.freeze, args.run_dir, args.output_dir)
    print(json.dumps({"status": record["status"], "cases": record["case_status_counts"], "rows": record["table_rows"]}))


if __name__ == "__main__":
    main()
