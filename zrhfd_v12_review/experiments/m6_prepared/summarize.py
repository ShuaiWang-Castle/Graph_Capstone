"""Only the independent prepared-cut108 cohort enters these M6 summaries."""
from __future__ import annotations
import csv
from collections import Counter, defaultdict
from pathlib import Path
from common import ROOT, CONFIG, MANIFEST, atomic, read, sha, utc

def summarize():
    import numpy as np
    cfg = read(CONFIG)
    if not MANIFEST.exists():
        atomic(ROOT / "results/m6_prepared/summary.json", {"schema_version": 1,
            "status": "NOT_RUN", "formal_completed": 0, "formal_scheduled": 108,
            "reason": "Awaiting root SOURCE_FROZEN and serial measurement window",
            "manifest_exists": False})
        return
    manifest = read(MANIFEST)
    rows = []
    graph_values = defaultdict(list)
    for query in manifest["schedule"]:
        row = {"query_id": query["query_id"], "case_id": query["case_id"],
               "implementation_version": cfg["implementation_version"],
               "n": query["n"], "generation_seed": query["generation_seed"],
               "seed": query["seed"], "status": "NOT_RUN"}
        attempts = sorted((ROOT / "results/m6_prepared/queries" / query["query_id"]).glob("attempt_*"))
        row["attempt_count"] = len(attempts)
        if attempts:
            directory = attempts[-1]
            row["raw_directory"] = str(directory.relative_to(ROOT))
            if (directory / "terminal.json").exists():
                terminal = read(directory / "terminal.json")
                row.update({key: terminal.get(key) for key in ("status", "parent_process_wall_seconds",
                    "max_sampled_process_group_rss_bytes", "time_l_max_resident_set_size_bytes", "runtime_censored")})
                checkpoint = terminal.get("last_checkpoint") or {}
                row["last_checkpoint_stage"] = checkpoint.get("event", {}).get("stage")
            else:
                row["status"] = "interrupted_unfinished"
            if row["status"] == "completed":
                result = read(directory / "result.json")
                if sha(directory / "result.json") != terminal["result_sha256"]:
                    raise RuntimeError("Completed raw result hash differs")
                output, offline = result["raw_output"], result["offline_only"]
                row.update(result["timing"])
                row.update({"touched_volume": output["touched_volume"],
                    "output_volume": output["stats"]["volume"], "output_size": output["stats"]["size"],
                    "method_status": output["status"], "j_act": output["j_act"], "j_star": output["j_star"],
                    "region_volume": output["region_volume"], "certificate_status": output["certificate"]["certificate_status"],
                    "gap": output["certificate"]["gap"], "progress_io_seconds": result["progress_io"]["seconds"],
                    "touched_over_output_volume": offline["touched_over_output_volume"],
                    "target_volume": offline["target_volume"], "target_size": offline["target_size"],
                    "target_size_outlier": offline["target_size_outlier_from_native_requested_bounds"],
                    "covered": offline["covered"], "rho_hat": offline["rho_hat"],
                    "region_outside_truth_volume_ratio": offline["region_outside_truth_volume_ratio"],
                    "failure_class": offline["failure_class"], "F1": offline["quality"]["F1"],
                    "hull_best_F1": offline["hull_best_quality"]["F1"]})
                graph_values[query["case_id"]].append(row)
        rows.append(row)
    counts = dict(Counter(row["status"] for row in rows))
    by_n = {str(n): dict(Counter(row["status"] for row in rows if row["n"] == n))
            for n in sorted({r["n"] for r in rows})}
    completed = [row for row in rows if row["status"] == "completed"]
    graph_rows = []
    for case, values in sorted(graph_values.items()):
        graph_rows.append({"case_id": case, "n": values[0]["n"], "completed_queries": len(values),
            "median_method_hot_wall_seconds": float(np.median([v["method_hot_wall_seconds"] for v in values])),
            "median_parent_process_wall_seconds": float(np.median([v["parent_process_wall_seconds"] for v in values])),
            "median_target_volume": float(np.median([v["target_volume"] for v in values])),
            "median_touched_volume": float(np.median([v["touched_volume"] for v in values])),
            "median_touched_over_output_volume": float(np.median([v["touched_over_output_volume"] for v in values]))})
    fit_fields = {"method_hot_wall_seconds": "median_method_hot_wall_seconds",
                  "parent_process_wall_seconds": "median_parent_process_wall_seconds",
                  "touched_volume": "median_touched_volume"}
    def fit(data, field, adjusted=False):
        if len({r["n"] for r in data}) < 3:
            return None
        x = np.log([r["n"] for r in data])
        y = np.log([r[field] for r in data])
        columns = [np.ones(len(data)), x]
        if adjusted:
            columns.append(np.log([r["median_target_volume"] for r in data]))
        X = np.column_stack(columns)
        if np.linalg.matrix_rank(X) < len(columns):
            return None
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        return {"intercept": float(beta[0]), "logn_slope": float(beta[1]),
                "logtruthvol_slope": float(beta[2]) if adjusted else None}
    fits = {}
    rng = np.random.default_rng(cfg["bootstrap"]["seed"])
    strata = [[r for r in graph_rows if r["n"] == n] for n in sorted({r["n"] for r in graph_rows})]
    draws = []
    if len(strata) == 3:
        for _ in range(cfg["bootstrap"]["replicates"]):
            draws.append([stratum[int(index)] for stratum in strata
                          for index in rng.integers(0, len(stratum), len(stratum))])
    for name, field in fit_fields.items():
        for adjusted in (False, True):
            estimate = fit(graph_rows, field, adjusted)
            key = name + ("_logtruthvol_adjusted" if adjusted else "_raw_logn")
            if estimate is None:
                fits[key] = {"status": "NOT_ESTIMABLE"}
                continue
            samples = [fit(draw, field, adjusted) for draw in draws]
            slopes = [s["logn_slope"] for s in samples if s is not None]
            fits[key] = {"status": "DESCRIPTIVE_COMPLETED_ONLY", **estimate,
                "graph_cluster_bootstrap_95_ci": list(map(float, np.quantile(slopes, [.025, .975]))) if slopes else None,
                "bootstrap_valid_replicates": len(slopes), "graph_count": len(graph_rows),
                "unit": "OLS on log of graph medians; each graph receives equal weight",
                "limitation": "Incomplete graphs use only completed queries; does not establish the full-cohort gate"}
    complete = len(completed) == len(rows)
    ratio = float(np.median([r["touched_over_output_volume"] for r in completed])) if completed else None
    summary = {"schema_version": 1, "created_at_utc": utc(), "manifest_sha256": sha(MANIFEST),
        "implementation_version": cfg["implementation_version"], "legacy_measurements_imported": False,
        "scheduled_queries": len(rows), "completed_queries": len(completed), "status_counts": counts,
        "status_counts_by_n": by_n, "all_queries_completed": complete,
        "median_touched_over_output_volume_completed_only": ratio,
        "ratio_median_le_20": ratio <= 20 if ratio is not None else None,
        "graph_summaries": graph_rows, "fits": fits,
        "gate_assessment": "READY_FOR_ROOT_FULL_COHORT_ASSESSMENT" if complete else "NOT_ESTABLISHED_INCOMPLETE_COHORT",
        "censoring_policy": "No timeout/error treated as completion or silently discarded; completed-only fits explicitly descriptive",
        "runtime_primary": cfg["timing"]["primary"],
        "os_cache_policy": "No OS cache flushing; mmap load and all startup costs reported separately; CPU only, serial"}
    atomic(ROOT / "results/m6_prepared/summary.json", summary)
    keys = sorted({key for row in rows for key in row})
    target = ROOT / "results/m6_prepared/query_summary.csv"
    with target.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"M6: {len(completed)}/{len(rows)} completed; statuses={counts}")

if __name__ == "__main__":
    summarize()
