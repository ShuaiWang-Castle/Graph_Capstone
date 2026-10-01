"""Completed-budget M5 summaries and explicitly scoped paired bootstrap.

Descriptive/empty summaries use stdlib. NumPy and resampling are lazy and require
--bootstrap, after verified inventory and an authorized offline CPU window.
"""
from __future__ import annotations
import argparse
import json
import statistics
import warnings
from collections import Counter, defaultdict
from pathlib import Path
try:
    from .inventory import ROOT, REAL, METHODS, NUMERIC_FIELDS, canonical, csv_write, digest, finite, project_path, read_json, utc, validate_analysis_cohort
except ImportError:
    from inventory import ROOT, REAL, METHODS, NUMERIC_FIELDS, canonical, csv_write, digest, finite, project_path, read_json, utc, validate_analysis_cohort

PAIRS = (("zr_hfd", "hfd_no_volume"), ("zr_hfd", "hfd_oracle"), ("zr_hfd", "tlhfd_no_volume"),
    ("zr_hfd", "clique_acl_no_volume"), ("zr_hfd", "zh_prov"), ("hfd_oracle", "hfd_no_volume"),
    ("tlhfd_oracle", "tlhfd_no_volume"), ("clique_acl_oracle", "clique_acl_no_volume"),
    ("zr_hfd", "tlhfd_oracle"), ("zr_hfd", "clique_acl_oracle"))
REPLICATES = 10000
SEED = 20261005


def completed(row):
    return row.get("completed_budget_execution") is True and row.get("integrity_status") == "PASS"


def descriptives(values):
    values = [float(v) for v in values if finite(v)]
    return {"observations": len(values), "mean": statistics.fmean(values), "median": statistics.median(values)} if values else {"observations": 0, "mean": None, "median": None}


def grouped_panels(rows):
    panels = defaultdict(list)
    for row in rows:
        family = row["dataset_family"]
        panels[family].append(row)
        if family == "HSBM":
            panels["HSBM_mu" + str(row["cross_edge_fraction"])].append(row)
    return {k: panels[k] for k in sorted(panels)}


def panel_summary(rows):
    by_method = defaultdict(list)
    for row in rows:
        by_method[row["method"]].append(row)
    methods = {}
    for method in METHODS:
        planned = by_method[method]
        done = [r for r in planned if completed(r)]
        partial = [r for r in planned if not completed(r) and finite(r.get("F1"))]
        methods[method] = {"planned": len(planned), "completed_budget": len(done),
            "completion_fraction": len(done) / len(planned) if planned else None,
            "status_counts": dict(Counter(r["analysis_status"] for r in planned)),
            "completed_only": {key: descriptives([r.get(key) for r in done]) for key in NUMERIC_FIELDS},
            "partial_offline_quality_available": len(partial),
            "seed_omissions_completed": sum(r.get("contains_seed") is False for r in done),
            "native_author_seed_omissions_completed": sum(r.get("native_author_seed_omission") is True for r in done),
            "certificate_status_counts_completed": dict(Counter(str(r.get("certificate_status", "UNKNOWN")) for r in done)),
            "certificate_target_met_counts_completed": dict(Counter(str(r.get("LB_R_target_precision_met")) for r in done if r.get("certificate_status"))),
            "touched_definitions": sorted({r.get("touched_definition", "UNKNOWN") for r in done}),
            "status": "NOT_RUN" if not done else "COMPLETED_ONLY_DESCRIPTIVE"}
    lookup = {(r["dataset"], r["query_id"], r["method"]): r for r in rows}
    query_keys = sorted({(r["dataset"], r["query_id"]) for r in rows})
    comparisons = {}
    for left, right in PAIRS:
        pairs = [(lookup.get((*q, left)), lookup.get((*q, right))) for q in query_keys]
        pairs = [(a, b) for a, b in pairs if a and b and completed(a) and completed(b) and finite(a.get("F1")) and finite(b.get("F1"))]
        differences = [a["F1"] - b["F1"] for a, b in pairs]
        comparisons[left + "_minus_" + right] = {"planned_query_pairs": len(query_keys), "complete_pairs": len(pairs),
            "paired_F1_difference": descriptives(differences),
            "difference_of_medians_on_complete_pairs": statistics.median(a["F1"] for a, _ in pairs) - statistics.median(b["F1"] for _, b in pairs) if pairs else None,
            "status": "NOT_RUN" if not pairs else "COMPLETE_PAIR_DESCRIPTIVE",
            "missing_policy": "No imputation; incomplete pair omitted from descriptive difference and explicitly retained in denominator"}
    return {"methods": methods, "comparisons": comparisons}


def gate_g_e4(rows, integrity_status):
    assessments = {}
    for dataset in REAL:
        selected = [r for r in rows if r["dataset"] == dataset]
        summary = panel_summary(selected)
        main = summary["methods"]["zr_hfd"]
        hfd = summary["methods"]["hfd_no_volume"]
        oracle = summary["methods"]["hfd_oracle"]
        eligible = bool(main["planned"]) and main["completed_budget"] == main["planned"] == hfd["planned"] == hfd["completed_budget"] and integrity_status == "PASS"
        reference_complete = bool(main["planned"]) and main["completed_budget"] == main["planned"] == oracle["planned"] == oracle["completed_budget"] and integrity_status == "PASS"
        a = main["completed_only"]["F1"]["median"]
        b = hfd["completed_only"]["F1"]["median"]
        comparison = ("PASS" if a >= b else "FAIL") if eligible else "NOT_RUN"
        status = comparison if eligible and reference_complete else "NOT_RUN"
        assessments[dataset] = {"status": status, "quality_comparison_status": comparison,
            "oracle_reference_status": "COMPLETE_REFERENCE" if reference_complete else "REFERENCE_INCOMPLETE",
            "planned_queries": main["planned"], "main_completed": main["completed_budget"], "HFD_no_volume_completed": hfd["completed_budget"],
            "HFD_oracle_planned": oracle["planned"], "HFD_oracle_completed": oracle["completed_budget"],
            "complete_frozen_dataset_eligible": eligible, "main_F1_median_completed_only": a,
            "HFD_no_volume_F1_median_completed_only": b,
            "oracle_gap": summary["comparisons"]["zr_hfd_minus_hfd_oracle"],
            "reason": None if eligible and reference_complete else "Complete planned main/HFD-no-volume required for comparison; complete main/HFD-oracle reference additionally required for a full G-E4 conclusion. Partial gaps stay descriptive."}
    states = [v["status"] for v in assessments.values()]
    status = "PASS" if "PASS" in states else "FAIL" if all(s == "FAIL" for s in states) else "NOT_RUN"
    return {"status": status, "datasets": assessments,
        "criterion": "At least one complete official real dataset: median F1(main) >= median F1(HFD-no-volume), with its full planned main/HFD-oracle reference gap reported",
        "source": "provenance/goal-objective.md G-E4", "completion_is_not_convergence": True}


def bootstrap_panel(rows, summary, fields=NUMERIC_FIELDS):
    import numpy as np
    lookup = {(r["dataset"], r["query_id"], r["method"]): r for r in rows}
    keys = sorted({(r["dataset"], r["query_id"]) for r in rows})
    index = {key: i for i, key in enumerate(keys)}
    matrix = np.full((len(keys), len(METHODS), len(fields)), np.nan)
    units = defaultdict(list)
    for key in keys:
        reference = next(lookup[(*key, m)] for m in METHODS if (*key, m) in lookup)
        unit = reference["cluster_code"] if reference["dataset"] in REAL else reference["dataset"]
        units[unit].append(index[key])
        for mi, method in enumerate(METHODS):
            row = lookup.get((*key, method))
            if row and completed(row):
                for fi, field in enumerate(fields):
                    if finite(row.get(field)):
                        matrix[index[key], mi, fi] = row[field]
    if not np.isfinite(matrix).any():
        return {"status": "NOT_RUN", "reason": "No completed finite values; no resampling"}
    f1_index = list(fields).index("F1")
    f1 = matrix[:, :, f1_index]
    pair_matrix = np.column_stack([f1[:, METHODS.index(a)] - f1[:, METHODS.index(b)] for a, b in PAIRS])
    mean_draws = np.full((REPLICATES, len(METHODS), len(fields)), np.nan)
    median_draws = np.full_like(mean_draws, np.nan)
    pair_mean = np.full((REPLICATES, len(PAIRS)), np.nan)
    pair_median = np.full_like(pair_mean, np.nan)
    groups = [np.asarray(units[u], dtype=int) for u in sorted(units)]
    rng = np.random.default_rng(SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for replicate in range(REPLICATES):
            chosen = rng.integers(0, len(groups), size=len(groups))
            draws = np.concatenate([g[rng.integers(0, len(g), size=len(g))] for g in (groups[i] for i in chosen)])
            sample = matrix[draws]
            mean_draws[replicate] = np.nanmean(sample, axis=0)
            median_draws[replicate] = np.nanmedian(sample, axis=0)
            pair_mean[replicate] = np.nanmean(pair_matrix[draws], axis=0)
            pair_median[replicate] = np.nanmedian(pair_matrix[draws], axis=0)
    def interval(values):
        valid = values[np.isfinite(values)]
        return {"percentile_95_CI": [float(x) for x in np.quantile(valid, [.025, .975])] if len(valid) else None,
            "valid_replicates": len(valid)}
    for mi, method in enumerate(METHODS):
        for fi, field in enumerate(fields):
            target = summary["methods"][method]["completed_only"][field]
            target["bootstrap_mean"] = interval(mean_draws[:, mi, fi])
            target["bootstrap_median"] = interval(median_draws[:, mi, fi])
    for pi, (left, right) in enumerate(PAIRS):
        target = summary["comparisons"][left + "_minus_" + right]
        target["paired_F1_difference"]["bootstrap_mean"] = interval(pair_mean[:, pi])
        target["paired_F1_difference"]["bootstrap_median"] = interval(pair_median[:, pi])
    real = rows[0]["dataset"] in REAL
    return {"status": "PAIRED_RESAMPLING_COMPLETED_ONLY", "replicates": REPLICATES, "seed": SEED,
        "first_level_units": len(groups), "query_count_planned": len(keys),
        "resampling": "target cluster then its queries; identical draw indices across methods and paired differences" if real else "graph then its queries; identical draw indices across methods and paired differences",
        "scope": "Conditional descriptive resampling of fixed Contact topology/classes and the full fixed seed census; not population uncertainty" if rows[0]["dataset"] == "contact-high-school" else "Conditional on this one fixed observed topology and sampled cluster queries; no across-graph claim" if real else "Generated HSBM graph/query panel; three generation seeds reused across mixing conditions, so pooled cross-condition independence is limited",
        "missing_policy": "Unavailable fields/method outcomes remain NaN after the same planned-query draw; finite completed subset only, no imputations; report valid replicate counts"}


def summarize(report, rows, bootstrap=False, reproduced_cohort=False, reference_binding=None):
    binding = validate_analysis_cohort(report, reproduced_cohort, reference_binding)
    if bootstrap and report["integrity_status"] != "PASS":
        raise ValueError("Bootstrap requires a fully verified PASS inventory")
    panels = {}
    for name, selected in grouped_panels(rows).items():
        panel = panel_summary(selected)
        panel["statistical_scope"] = "Conditional descriptive resampling of a fixed topology/classes and fixed query census; not population uncertainty" if name == "contact-high-school" else "Conditional on one fixed topology; target-cluster and sampled-query hierarchy, not across-graph uncertainty" if name == "trivago-clicks" else "HSBM graph/query hierarchy; frozen mixing-condition panels"
        panel["bootstrap"] = bootstrap_panel(selected, panel) if bootstrap else {"status": "NOT_RUN", "reason": "Bootstrap waits authorized CPU window"}
        panels[name] = panel
    return {"schema_version": 1, "generated_utc": utc(), "inventory_manifest_sha256": report["manifest"]["manifest_sha256"],
        "cohort_origin": report.get("cohort_origin", "NONFORMAL_FIXTURE"), "reference_binding": binding,
        "reference_binding_sha256": binding["binding_receipt_sha256"] if binding else None,
        "inventory_run": report.get("run"), "storage_scope": report["manifest"].get("storage_scope"),
        "inventory_frozen_sha256": report["manifest"]["frozen_sha256"], "integrity_status": report["integrity_status"],
        "planned_tasks": len(rows), "status_counts": dict(Counter(r["analysis_status"] for r in rows)),
        "completed_budget_executions": sum(completed(r) for r in rows), "panels": panels,
        "G_E4": gate_g_e4(rows, report["integrity_status"]),
        "status": "NOT_RUN" if not any(completed(r) for r in rows) else "COMPLETED_ONLY_ANALYSIS",
        "scope": "Frozen all-or-nothing input; completed requested budget is not convergence; main support-union volume is not an implementation locality claim",
        "partial_policy": "All planned statuses and partial metrics stay in query_results.csv; partial records excluded from completed quality/cost tables",
        "cost_definition": "Controller wall includes topology, conversion, worker, offline evaluation, result/progress parsing; post-terminal archival excluded. Method-returned runtime and native kernel are separate.",
        "source_sha256": {"experiments/m5_analysis/summarize.py": digest(__file__)}}


def write_summary(output, summary, report, rows):
    if summary["cohort_origin"] == "FRESH_REPRODUCTION" and output.resolve() == ROOT / "results/m5_analysis/official_v12_001":
        raise ValueError("Fresh summary cannot overwrite original official analysis")
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    table = []
    for panel, data in summary["panels"].items():
        for method, m in data["methods"].items():
            row = {"panel": panel, "method": method, "planned": m["planned"], "completed_budget": m["completed_budget"],
                "completion_fraction": m["completion_fraction"], "status_counts": m["status_counts"], "seed_omissions_completed": m["seed_omissions_completed"],
                "native_author_seed_omissions_completed": m["native_author_seed_omissions_completed"], "statistical_scope": data["statistical_scope"]}
            for field, values in m["completed_only"].items():
                for key in ("observations", "mean", "median"):
                    row[field + "_" + key] = values[key]
                for key in ("bootstrap_mean", "bootstrap_median"):
                    row[field + "_" + key + "_95_CI"] = values.get(key, {}).get("percentile_95_CI")
            table.append(row)
    csv_write(output / "quality_cost_summary.csv", table)
    pairs = [{"panel": panel, "comparison": name, **value} for panel, data in summary["panels"].items() for name, value in data["comparisons"].items()]
    csv_write(output / "paired_comparisons.csv", pairs)
    partial = [r for r in rows if not completed(r) and r["analysis_status"] != "NOT_RUN"]
    csv_write(output / "partial_and_failed.csv", partial, sorted({key for r in rows for key in r} | set(NUMERIC_FIELDS)))
    provenance = {"generated_utc": utc(), "analysis_source_sha256": {"inventory.py": digest(ROOT / "experiments/m5_analysis/inventory.py"), "summarize.py": digest(__file__)},
        "cohort_origin": summary["cohort_origin"], "reference_binding_sha256": summary.get("reference_binding_sha256"),
        "inputs": {name: digest(output / name) for name in ("inventory.json", "query_results.csv", "query_results.json", "attempt_inventory.json")},
        "outputs": {name: digest(output / name) for name in ("summary.json", "quality_cost_summary.csv", "paired_comparisons.csv", "partial_and_failed.csv")},
        "bootstrap_executed": any(p["bootstrap"]["status"] != "NOT_RUN" for p in summary["panels"].values())}
    (output / "analysis_provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="results/m5_analysis/official_v12_001")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--reproduced-cohort", action="store_true")
    parser.add_argument("--reference-binding", help="Verified fresh reference binding, paired with --reproduced-cohort")
    args = parser.parse_args()
    output = project_path(args.input)
    if not output.is_relative_to(ROOT / "results/m5_analysis"):
        parser.error("Summary writes restricted to results/m5_analysis")
    if args.reproduced_cohort != bool(args.reference_binding):
        parser.error("Both --reproduced-cohort and --reference-binding are required for fresh mode")
    if args.reproduced_cohort and output.resolve() == ROOT / "results/m5_analysis/official_v12_001":
        parser.error("Fresh summary cannot overwrite original official analysis")
    report, rows = read_json(output / "inventory.json"), read_json(output / "query_results.json")
    for name, expected in report["artifact_sha256"].items():
        if digest(output / name) != expected:
            parser.error("Inventory analysis artifact changed: " + name)
    if args.bootstrap and report["integrity_status"] != "PASS":
        parser.error("Bootstrap requires PASS inventory with --verify-files; metadata-only or failed audit cannot support final claims")
    summary = summarize(report, rows, args.bootstrap, args.reproduced_cohort,
                        project_path(args.reference_binding) if args.reference_binding else None)
    write_summary(output, summary, report, rows)
    print(json.dumps({"status": summary["status"], "planned": len(rows), "completed": summary["completed_budget_executions"], "G_E4": summary["G_E4"]["status"], "bootstrap": args.bootstrap}))


if __name__ == "__main__":
    main()
