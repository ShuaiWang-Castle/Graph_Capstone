#!/usr/bin/env python3
"""Read-only, after-the-run C1 gate analysis. It never scores a cover or trains.

Input is the already scored four-arm development result table, its frozen
catalog, the matching raw run directory, and the pre-quality gate. Missing
jobs remain explicit. This module is intentionally stdlib-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

ELEMENT = "nocd_pairdot_elementwise500"
BMM = "nocd_pairdot_bmm500"
CSR = "nocd_pairdot_csr500"
CAP = "nocd_pairdot_elementwise1000"
METHODS = (ELEMENT, BMM, CSR, CAP)
SEEDS = (73, 74, 75)
SIZES = (1000, 5000)
QUALITY = ("matched_macro_f1", "matched_membership_micro_f1")
AT_LEAST_TWO = "at_least_two_correct_recall"


def read_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and (not positive or value > 0)


def job_id(case_id: str, method: str, seed: int) -> str:
    return f"{case_id}__{method}__s{seed}"


def checked_catalog(catalog, gate):
    if not isinstance(catalog, list) or len(catalog) != gate["development_graphs"]:
        raise ValueError("Catalog must contain the frozen 24 development cases")
    cases = {}
    for row in catalog:
        case = row["case_id"]
        if not isinstance(case, str) or case in ("", ".", "..") or "/" in case or "\\" in case or case in cases:
            raise ValueError("Invalid or repeated case_id")
        if row.get("status") != "GENERATED" or row.get("n") not in SIZES:
            raise ValueError("Expected a generated frozen n1000/n5000 case")
        cases[case] = row
    if Counter(c["n"] for c in cases.values()) != {1000: 12, 5000: 12}:
        raise ValueError("Frozen 12+12 size strata changed")
    return cases


def checked_gate(gate):
    if gate.get("gate_id") != "C1_before_first_development_quality_v1":
        raise ValueError("Unexpected C1 gate identity")
    if gate.get("algorithm_seeds") != list(SEEDS) or gate.get("development_graphs") != 24:
        raise ValueError("Frozen C1 grid changed")
    if gate.get("primary_control") != ELEMENT or gate.get("secondary_operator_control") != BMM:
        raise ValueError("Primary/operator control identity changed")
    if gate.get("budget_control") != CAP or gate.get("candidate_backends") != ["sampled_csr"]:
        raise ValueError("C1 arm identity changed")
    q = gate["quality_thresholds"]
    s = gate["speed_thresholds"]
    if q["metrics"] != list(QUALITY) or q["per_size_per_algorithm_seed_mean_paired_delta_at_least"] != -0.01:
        raise ValueError("Quality policy changed")
    if q["all_regressions_delta_at_most"] != -0.03:
        raise ValueError("Material-regression policy changed")
    if s["per_size_per_algorithm_seed_median_paired_saving_at_least"] != 0.1:
        raise ValueError("Speed policy changed")
    if gate["one_global_backend_selection"]["tie_preference"] != "bmm":
        raise ValueError("Tie policy changed")


def source_sha_from_raw(source_hashes, relative):
    matches = [v for k, v in source_hashes.items() if k.replace("\\", "/").endswith("/" + relative)]
    return matches[0] if len(matches) == 1 else None


def read_raw_trace(prediction_path: Path, expected_hash: str | None, cap: int, check: int):
    if not prediction_path.is_file():
        return {"trace_error": "missing_prediction_file"}
    if expected_hash and digest(prediction_path) != expected_hash:
        return {"trace_error": "prediction_sha256_mismatch"}
    prediction = read_json(prediction_path)
    trace = prediction.get("trace")
    kind = prediction.get("metadata", {}).get("kind")
    if not isinstance(trace, list) or not trace or not isinstance(kind, str):
        return {"trace_error": "missing_trace_or_termination"}
    epochs = [item.get("epoch") for item in trace if isinstance(item, dict)]
    if len(epochs) != len(trace) or any(type(e) is not int for e in epochs):
        return {"trace_error": "invalid_trace_epoch_type"}
    expected = list(range(0, epochs[-1] + 1, check))
    if epochs != expected and not (epochs == expected + [cap] and cap % check and epochs[-1] == cap):
        return {"trace_error": "check_epoch_sequence_mismatch", "check_epochs": epochs}
    last = epochs[-1]
    if not 0 <= last <= cap:
        return {"trace_error": "last_check_outside_cap"}
    if kind == "training_loss_patience":
        lower = upper = last  # check is before the update at this epoch
    elif kind == "max_epochs":
        if last != cap:
            return {"trace_error": "natural_cap_without_final_check"}
        lower = upper = cap + 1  # loop is inclusive: range(max_epochs+1)
    elif kind == "internal_time_budget":
        lower, upper = last, min(cap, last + check - 1)
    else:
        return {"trace_error": "unknown_termination", "termination": kind}
    stage = prediction.get("stage_seconds", {})
    forward_backward = stage.get("forward_loss_backward_seconds")
    if not finite_number(forward_backward) or forward_backward < 0:
        return {"trace_error": "missing_or_invalid_forward_backward_stage"}
    exact = lower if lower == upper else None
    return {
        "termination": kind,
        "last_check_epoch": last,
        "number_of_checks": len(trace),
        "train_updates_lower": lower,
        "train_updates_upper": upper,
        "train_updates_exact": exact,
        "forward_loss_backward_seconds": forward_backward,
        "forward_backward_seconds_per_exact_update": forward_backward / exact if exact else None,
        "trace_error": None,
    }


def assemble_rows(results, cases, run_root: Path, gate, controls):
    if not isinstance(results, list):
        raise ValueError("Scored results must be a JSON array")
    controls_by_id = {m["id"]: m for m in controls["methods"]}
    if set(controls_by_id) != set(METHODS):
        raise ValueError("Four-arm control configuration changed")
    scored = {}
    for row in results:
        key = (row.get("case_id"), row.get("seed"), row.get("method"))
        if key[0] not in cases or key[1] not in SEEDS or key[2] not in METHODS:
            raise ValueError(f"Unexpected scored row identity: {key}")
        if key in scored:
            raise ValueError(f"Duplicate scored row identity: {key}")
        if row.get("job_id") != job_id(key[0], key[2], key[1]):
            raise ValueError(f"Wrong job_id for scored row: {key}")
        scored[key] = row
    expected_ids = {job_id(case, method, seed) for case in cases for seed in SEEDS for method in METHODS}
    unknown_raw = [str(p) for p in run_root.glob("*/result.json") if p.parent.name not in expected_ids]
    if unknown_raw:
        raise ValueError(f"Unexpected raw result identities: {unknown_raw[:3]}")

    rows = []
    raw_hashes = {}
    for case in sorted(cases):
        for seed in SEEDS:
            for method in METHODS:
                key = (case, seed, method)
                jid = job_id(case, method, seed)
                job_dir = run_root / jid
                result_path = job_dir / "result.json"
                spec_path = job_dir / "spec.json"
                score = scored.get(key)
                raw = read_json(result_path) if result_path.is_file() else None
                errors = []
                oracle_k = None
                source_signature = None
                if raw is not None:
                    raw_hashes[jid] = digest(result_path)
                    if isinstance(raw.get("source_hashes"), dict):
                        source_signature = hashlib.sha256(json.dumps(raw["source_hashes"], sort_keys=True).encode()).hexdigest()
                    for field, value in (("job_id", jid), ("case_id", case), ("seed", seed), ("method", method)):
                        if raw.get(field) != value:
                            errors.append("raw_" + field + "_mismatch")
                    if raw.get("graph_sha256") != cases[case].get("graph_sha256"):
                        errors.append("raw_graph_sha256_mismatch")
                    if raw.get("device") != "cpu" or raw.get("threads") != 1 or raw.get("information_policy") != "oracle_K":
                        errors.append("raw_comparison_panel_mismatch")
                    if not spec_path.is_file():
                        errors.append("missing_raw_spec")
                    else:
                        spec = read_json(spec_path)
                        for field, value in (("job_id", jid), ("case_id", case), ("seed", seed), ("method", method),
                                             ("device", "cpu"), ("threads", 1), ("information_policy", "oracle_K")):
                            if spec.get(field) != value:
                                errors.append("spec_" + field + "_mismatch")
                        config_file = Path(spec.get("config", ""))
                        if (not config_file.is_file() or not spec.get("config_sha256")
                                or digest(config_file) != spec["config_sha256"]
                                or raw.get("config_sha256") != spec["config_sha256"]):
                            errors.append("per_job_config_sha256_mismatch")
                        else:
                            job_config = read_json(config_file)
                            oracle_k = job_config.get("k")
                            if type(oracle_k) is not int or oracle_k < 1:
                                errors.append("invalid_oracle_k_scalar")
                            if any(job_config.get(k) != v for k, v in controls_by_id[method]["parameters"].items()
                                   if k not in ("k", "source_dir", "module_path")):
                                errors.append("per_job_control_parameters_mismatch")
                    for relative in ("candidates/nocd_pairdot/adapter.py", "candidates/nocd_pairdot/pairdot.py"):
                        expected = gate["source_hashes"][relative]
                        if source_sha_from_raw(raw.get("source_hashes", {}), relative) != expected:
                            errors.append("raw_source_mismatch:" + relative)
                if score is None:
                    status = raw.get("status", "NOT_RUN") if raw else "NOT_RUN"
                    errors.append("missing_scored_row")
                else:
                    status = score.get("status")
                    if raw is None:
                        errors.append("missing_raw_result")
                    elif status != raw.get("status") or score.get("pipeline_seconds") != raw.get("pipeline_seconds"):
                        errors.append("raw_scored_status_or_time_mismatch")
                    if score.get("device") != "cpu" or score.get("threads") != 1 or score.get("information_policy") != "oracle_K":
                        errors.append("comparison_panel_mismatch")
                metrics = {name: score.get(name) if score else None for name in (*QUALITY, AT_LEAST_TWO)}
                for name in QUALITY:
                    if metrics[name] is not None and (not finite_number(metrics[name]) or not 0 <= metrics[name] <= 1):
                        errors.append("invalid_metric:" + name)
                    if score is not None and score.get("metric_status") == "SCORED" and metrics[name] is None:
                        errors.append("scored_without_metric:" + name)
                if metrics[AT_LEAST_TWO] is not None and (not finite_number(metrics[AT_LEAST_TWO]) or not 0 <= metrics[AT_LEAST_TWO] <= 1):
                    errors.append("invalid_metric:" + AT_LEAST_TWO)
                if score is not None and score.get("metric_status") == "SCORED" and AT_LEAST_TWO not in score:
                    errors.append("scored_without_at_least_two_field")
                seconds = score.get("pipeline_seconds") if score else (raw.get("pipeline_seconds") if raw else None)
                if status == "COMPLETED" and not finite_number(seconds, positive=True):
                    errors.append("completed_without_positive_full_time")
                cap = controls_by_id[method]["parameters"]["max_epochs"]
                check = controls_by_id[method]["parameters"]["check_every"]
                trace = {}
                if raw is not None and status == "COMPLETED":
                    expected_prediction = (job_dir / "prediction.json").resolve()
                    if not raw.get("prediction") or Path(raw["prediction"]).resolve() != expected_prediction:
                        errors.append("prediction_path_mismatch")
                    else:
                        trace = read_raw_trace(expected_prediction, raw.get("prediction_sha256"), cap, check)
                        if trace.get("trace_error"):
                            errors.append("trace:" + trace["trace_error"])
                row = {
                    "job_id": jid, "case_id": case, "n": cases[case]["n"], "seed": seed,
                    "method": method, "oracle_k": oracle_k,
                    "raw_source_map_signature": source_signature, "status": status,
                    "metric_status": score.get("metric_status") if score else "MISSING_SCORED_ROW",
                    "pipeline_seconds": seconds if status == "COMPLETED" else None,
                    **metrics, **trace,
                    "integrity_errors": errors,
                    "valid_completed_scored": status == "COMPLETED" and score is not None
                    and score.get("metric_status") == "SCORED" and not errors,
                }
                rows.append(row)
    # K is allowed only in this explicitly labeled oracle panel, and must be
    # the same scalar for all four arms and all three algorithm seeds of a case.
    for case in cases:
        group = [r for r in rows if r["case_id"] == case]
        known = {r["oracle_k"] for r in group if r["oracle_k"] is not None}
        if len(known) > 1:
            for row in group:
                row["integrity_errors"].append("oracle_k_cross_arm_or_seed_mismatch")
                row["valid_completed_scored"] = False
    signatures = {r["raw_source_map_signature"] for r in rows if r["raw_source_map_signature"] is not None}
    if len(signatures) > 1:
        for row in rows:
            row["integrity_errors"].append("cross_arm_source_map_mismatch")
            row["valid_completed_scored"] = False
    if len(rows) != 288:
        raise AssertionError("The planned four-arm denominator is not 288")
    return rows, raw_hashes


def pair_row(a, b, label):
    same = a["case_id"] == b["case_id"] and a["seed"] == b["seed"] and a["n"] == b["n"]
    if not same:
        raise ValueError("Attempt to pair different case/seed/size")
    valid = a["valid_completed_scored"] and b["valid_completed_scored"]
    row = {
        "pair": label, "case_id": a["case_id"], "n": a["n"], "seed": a["seed"],
        "reference_method": a["method"], "compared_method": b["method"],
        "reference_status": a["status"], "compared_status": b["status"],
        "reference_metric_status": a["metric_status"], "compared_metric_status": b["metric_status"],
        "reference_seconds": a["pipeline_seconds"] if valid else None,
        "compared_seconds": b["pipeline_seconds"] if valid else None,
        "paired_valid": valid,
        "candidate_only_incomplete": a["valid_completed_scored"] and not b["valid_completed_scored"],
    }
    row["saving"] = 1 - b["pipeline_seconds"] / a["pipeline_seconds"] if valid else None
    for prefix, source in (("reference", a), ("compared", b)):
        for name in ("termination", "last_check_epoch", "train_updates_lower", "train_updates_upper",
                     "train_updates_exact", "forward_loss_backward_seconds",
                     "forward_backward_seconds_per_exact_update"):
            row[prefix + "_" + name] = source.get(name) if valid else None
    a_low, a_high = a.get("train_updates_lower"), a.get("train_updates_upper")
    b_low, b_high = b.get("train_updates_lower"), b.get("train_updates_upper")
    if valid and all(type(v) is int for v in (a_low, a_high, b_low, b_high)):
        row["update_delta_lower"] = b_low - a_high
        row["update_delta_upper"] = b_high - a_low
        if a_low == a_high and b_low == b_high:
            row["update_delta_exact"] = b_low - a_low
            row["update_count_relation"] = "same_count_not_identical_trajectory" if b_low == a_low else "different_count"
        else:
            row["update_delta_exact"] = None
            row["update_count_relation"] = "definitely_different_count" if (b_low > a_high or b_high < a_low) else "unresolved_from_trace"
    else:
        row.update(update_delta_lower=None, update_delta_upper=None, update_delta_exact=None,
                   update_count_relation="not_common_completed_or_trace_unavailable")
    for metric in (*QUALITY, AT_LEAST_TWO):
        va, vb = a.get(metric), b.get(metric)
        row["delta_" + metric] = vb - va if valid and va is not None and vb is not None else None
    row["material_macro_or_micro_regression"] = valid and any(
        row["delta_" + metric] is not None and row["delta_" + metric] <= -0.03 for metric in QUALITY
    )
    row["at_least_two_loss"] = valid and row["delta_" + AT_LEAST_TWO] is not None and row["delta_" + AT_LEAST_TWO] < 0
    return row


def stratum_summary(pairs, label, n, seed):
    selected = [p for p in pairs if p["pair"] == label and p["n"] == n and p["seed"] == seed]
    valid = [p for p in selected if p["paired_valid"]]
    complete_denominator = len(selected) == 12 and len(valid) == 12
    means = {}
    for metric in QUALITY:
        values = [p["delta_" + metric] for p in valid]
        means[metric] = statistics.mean(values) if complete_denominator and len(values) == 12 else None
    return {
        "pair": label, "n": n, "seed": seed, "planned": len(selected),
        "paired_completed_scored": len(valid),
        "candidate_only_incomplete": sum(p["candidate_only_incomplete"] for p in selected),
        "median_saving": statistics.median(p["saving"] for p in valid) if complete_denominator else None,
        "mean_delta_macro": means[QUALITY[0]], "mean_delta_micro": means[QUALITY[1]],
        "material_regression_count": sum(p["material_macro_or_micro_regression"] for p in selected),
        "at_least_two_loss_count": sum(p["at_least_two_loss"] for p in selected),
        "complete_denominator": complete_denominator,
    }


def cap_comparison(reference, budget):
    same = reference["case_id"] == budget["case_id"] and reference["seed"] == budget["seed"]
    if not same:
        raise ValueError("Cap controls crossed case or seed")
    low_a, high_a = reference.get("train_updates_lower"), reference.get("train_updates_upper")
    low_b, high_b = budget.get("train_updates_lower"), budget.get("train_updates_upper")
    common = reference["valid_completed_scored"] and budget["valid_completed_scored"]
    if common and all(type(v) is int for v in (low_a, high_a, low_b, high_b)):
        if low_b > high_a:
            label = "definitely_more_updates"
        elif high_b <= low_a:
            label = "cap_only_no_extra_updates"
        else:
            label = "update_order_unresolved_from_trace"
    else:
        label = "not_common_completed_or_trace_unavailable"
    return {
        "case_id": reference["case_id"], "n": reference["n"], "seed": reference["seed"],
        "reference_status": reference["status"], "cap_status": budget["status"],
        "reference_termination": reference.get("termination"), "cap_termination": budget.get("termination"),
        "reference_last_check_epoch": reference.get("last_check_epoch"),
        "cap_last_check_epoch": budget.get("last_check_epoch"),
        "reference_updates_lower": low_a, "reference_updates_upper": high_a,
        "cap_updates_lower": low_b, "cap_updates_upper": high_b,
        "reference_seconds": reference["pipeline_seconds"] if common else None,
        "cap_seconds": budget["pipeline_seconds"] if common else None,
        "actual_extra_update_class": label,
    }


def evaluate_grid(rows, gate):
    if len(rows) != 288:
        raise ValueError("Expected 288 planned arm rows")
    lookup = {(r["case_id"], r["seed"], r["method"]): r for r in rows}
    cases = sorted({r["case_id"] for r in rows})
    pairs, caps = [], []
    for case in cases:
        for seed in SEEDS:
            ref = lookup[(case, seed, ELEMENT)]
            bmm = lookup[(case, seed, BMM)]
            csr = lookup[(case, seed, CSR)]
            cap = lookup[(case, seed, CAP)]
            pairs.extend((pair_row(ref, bmm, "BMM_vs_elementwise"),
                          pair_row(ref, csr, "CSR_vs_elementwise"),
                          pair_row(bmm, csr, "CSR_vs_BMM"),
                          pair_row(ref, cap, "cap1000_vs_500")))
            caps.append(cap_comparison(ref, cap))
    strata = [stratum_summary(pairs, label, n, seed)
              for label in ("BMM_vs_elementwise", "CSR_vs_elementwise", "CSR_vs_BMM", "cap1000_vs_500")
              for n in SIZES for seed in SEEDS]
    by_label = {(s["pair"], s["n"], s["seed"]): s for s in strata}
    qmin = gate["quality_thresholds"]["per_size_per_algorithm_seed_mean_paired_delta_at_least"]
    smin = gate["speed_thresholds"]["per_size_per_algorithm_seed_median_paired_saving_at_least"]
    arms = {}
    for method, label in ((BMM, "BMM_vs_elementwise"), (CSR, "CSR_vs_elementwise")):
        six = [by_label[(label, n, seed)] for n in SIZES for seed in SEEDS]
        quality_status = all(s["complete_denominator"] and
                             s["mean_delta_macro"] is not None and s["mean_delta_macro"] >= qmin and
                             s["mean_delta_micro"] is not None and s["mean_delta_micro"] >= qmin and
                             s["candidate_only_incomplete"] == 0 for s in six)
        all_grid = quality_status and all(s["median_saving"] >= smin for s in six)
        large_only = quality_status and all(by_label[(label, 5000, seed)]["median_saving"] >= smin for seed in SEEDS)
        chosen_pairs = [p for p in pairs if p["pair"] == label]
        pooled_saving = statistics.median(p["saving"] for p in chosen_pairs) if all(p["paired_valid"] for p in chosen_pairs) else None
        arms[method] = {
            "quality_and_status_eligible": quality_status,
            "all_grid_speed_signal": all_grid,
            "n5000_limited_speed_signal": large_only,
            "pooled_72_median_saving": pooled_saving,
            "claim_scope": "all_grid" if all_grid else ("n5000_only" if large_only else "none"),
        }
    csr_vs_bmm = {}
    for scope in ("all_grid", "n5000_only"):
        sizes = SIZES if scope == "all_grid" else (5000,)
        csr_vs_bmm[scope] = all(
            by_label[("CSR_vs_BMM", n, seed)]["complete_denominator"] and
            by_label[("CSR_vs_BMM", n, seed)]["median_saving"] >= smin
            for n in sizes for seed in SEEDS
        )
    eligible = [method for method in (BMM, CSR) if arms[method]["quality_and_status_eligible"]]
    selected, selection_reason = None, "no_quality_and_status_eligible_backend"
    if eligible:
        # Exact tie goes to the simpler existing bmm control.
        selected = max(eligible, key=lambda m: (arms[m]["pooled_72_median_saving"], m == BMM))
        selection_reason = "largest_pooled_72_paired_median_saving"
        scope = arms[selected]["claim_scope"]
        if selected == CSR and scope != "none" and not csr_vs_bmm[scope] and arms[BMM]["claim_scope"] != "none":
            selected = BMM
            selection_reason = "bmm_simplification_when_CSR_lacks_10pct_direct_advantage"
    selected_scope = arms[selected]["claim_scope"] if selected else "none"
    materials = [p for p in pairs if p["pair"] in ("BMM_vs_elementwise", "CSR_vs_elementwise")
                 and (p["material_macro_or_micro_regression"] or p["at_least_two_loss"])]
    status_counts = {method: dict(Counter(r["status"] for r in rows if r["method"] == method)) for method in METHODS}
    count_change = {label: dict(Counter(p["update_count_relation"] for p in pairs if p["pair"] == label))
                    for label in ("BMM_vs_elementwise", "CSR_vs_elementwise")}
    return {
        "planned_jobs": len(rows), "planned_per_arm": 72,
        "job_status_counts": status_counts,
        "arms": arms,
        "csr_direct_10pct_vs_bmm": csr_vs_bmm,
        "selected_global_backend": selected,
        "selected_claim_scope": selected_scope,
        "selection_reason": selection_reason,
        "confirmation_gate_open": selected_scope != "none",
        "material_or_at_least_two_loss_count": len(materials),
        "pointwise_no_regression_language_allowed": len(materials) == 0,
        "cap1000_update_classes": dict(Counter(r["actual_extra_update_class"] for r in caps)),
        "paired_actual_update_count_classes": count_change,
    }, pairs, strata, caps, materials


def write_csv(path: Path, rows):
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("results", "catalog", "run-root", "gate", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    results_path, catalog_path = Path(args.results), Path(args.catalog)
    run_root, gate_path, output = Path(args.run_root), Path(args.gate), Path(args.output)
    if output.exists():
        raise FileExistsError("Use a new absent output directory; analysis output is once-only")
    gate = read_json(gate_path)
    checked_gate(gate)
    controls_path = gate_path.parent / "nocd_pairdot_controls_v1.json"
    if digest(controls_path) != gate["source_hashes"]["configs/nocd_pairdot_controls_v1.json"]:
        raise ValueError("Four-arm controls changed after gate freeze")
    project_root = gate_path.parent.parent
    for relative, expected in gate["source_hashes"].items():
        actual = project_root / relative
        if not actual.is_file() or digest(actual) != expected:
            raise ValueError("Frozen source/config bytes changed: " + relative)
    cases = checked_catalog(read_json(catalog_path), gate)
    rows, raw_hashes = assemble_rows(read_json(results_path), cases, run_root, gate, read_json(controls_path))
    decision, pairs, strata, caps, materials = evaluate_grid(rows, gate)
    decision["integrity_error_jobs"] = [r["job_id"] for r in rows if r["integrity_errors"]]
    decision["input_sha256"] = {
        "results": digest(results_path), "catalog": digest(catalog_path),
        "gate": digest(gate_path), "controls": digest(controls_path),
        "raw_result_sha256_by_job": raw_hashes,
    }
    decision["analysis_scope"] = "Development descriptive gate only; no confirmation results or independent statistical inference"
    output.mkdir(parents=True)
    write_csv(output / "jobs.csv", rows)
    write_csv(output / "pairs.csv", pairs)
    write_csv(output / "update_counts.csv", [p for p in pairs if p["pair"] in ("BMM_vs_elementwise", "CSR_vs_elementwise")])
    write_csv(output / "strata.csv", strata)
    write_csv(output / "cap1000.csv", caps)
    write_csv(output / "regressions.csv", materials)
    (output / "gate-analysis.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(output / "gate-analysis.json")


if __name__ == "__main__":
    main()
