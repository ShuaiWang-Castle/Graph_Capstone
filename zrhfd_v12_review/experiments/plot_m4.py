"""Plot existing M4 summaries without recomputing bootstrap or loading graphs.

Schema preparation and --check-schema use only the standard library. Matplotlib
is imported only by the actual rendering stage; run that stage in an offline CPU
window after the independent cohort audit has passed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ORIGINAL_MAIN_MANIFESTS = {
    "ae8e1b57d465673c1ac14112e3e9ec13a1ba2b5166b0872d82c7a5d28ae8df3e",
    "caaf1ed4f65d2d51b1269856d1f944a59941e401a00cf99757775736b515150f",
}
LABELS = {"zrhfd": "ZR-HFD", "hfd": "HFD", "hfd_cd": "HFD-CD",
          "tlhfd": "TL*", "acl": "ACL", "pnorm": "p-norm", "leiden": "Leiden"}
PHI_EDGES = (.05, .15, .25, .35, .45, .55, .65)
CAPTION = (
    "Medians use completed requested budgets only; completion does not imply convergence. "
    "The horizontal axis is algorithm-wrapper wall, including native startup and conversion, "
    "excluding Graph.load and offline evaluation. Oracle-volume methods are a separate reference. "
    "Intervals are the existing graph-then-query bootstrap intervals, conditional on frozen regimes. "
    "Different missing outcome masks do not establish a paired comparison. All planned jobs remain "
    "in the status panel. Main diffusion-support volume is not total implementation I/O."
)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def relative_path(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected a project-relative path")
    return ROOT / path


def read_json(path):
    return json.loads(Path(path).read_text())


def numeric(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def is_completed(row):
    return row.get("status") == "COMPLETED" and row.get("completion_claim") in (True, "True", "true", "1")


def group_name(row):
    if row["method"] == "zrhfd_ablation":
        return row["variant"]
    if row["method"] == "zrhfd" and row.get("variant") != "main":
        return "zrhfd_" + row["variant"]
    return row["method"] + "_" + row["setting"]


def phi_bin(value):
    value = numeric(value)
    if value is None:
        return None
    for index, (left, right) in enumerate(zip(PHI_EDGES, PHI_EDGES[1:])):
        if left <= value < right:
            return str((index + 1) / 10)
    return None


def checked_metric(metric, rows, field):
    values = [numeric(r.get(field)) for r in rows]
    if field in ("F1", "outer_wall_seconds") and any(v is None for v in values):
        raise ValueError("Completed field is absent or nonfinite: " + field)
    values = [v for v in values if v is not None]
    if field == "F1" and any(not 0 <= v <= 1 for v in values):
        raise ValueError("Completed F1 lies outside [0,1]")
    if field == "outer_wall_seconds" and any(v <= 0 for v in values):
        raise ValueError("Completed algorithm-wrapper wall must be positive")
    if not values:
        if metric is not None:
            raise ValueError("Summary contains a statistic for an empty field: " + field)
        return None
    if not isinstance(metric, dict) or metric.get("queries") != len(values):
        raise ValueError("Summary observation count differs from CSV: " + field)
    median = statistics.median(values)
    if numeric(metric.get("median")) is None or not math.isclose(float(metric["median"]), median, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("Summary median differs from CSV: " + field)
    ci = metric.get("median_percentile_95_CI")
    if ci is not None and (not isinstance(ci, list) or len(ci) != 2 or any(numeric(v) is None for v in ci) or ci[0] > ci[1]):
        raise ValueError("Invalid existing median interval: " + field)
    return {"median": median, "observations": len(values), "median_95_CI": ci,
            "replicates": metric.get("replicates"), "seed": metric.get("seed")}


def prepare_panels(summary, rows):
    """Pure schema/consistency checks, also used by tiny artificial fixtures."""
    groups = defaultdict(list)
    for row in rows:
        groups[group_name(row)].append(row)
    if set(groups) != set(summary["panels"]):
        raise ValueError("Summary/CSV method panels differ")
    cost, strata, statuses = [], [], []
    for name, planned in sorted(groups.items()):
        panel = summary["panels"][name]
        counts = dict(Counter(r["status"] for r in planned))
        if panel.get("planned") != len(planned) or panel.get("statuses") != counts:
            raise ValueError("Summary/CSV planned statuses differ: " + name)
        done = [r for r in planned if is_completed(r)]
        method, setting = planned[0]["method"], planned[0]["setting"]
        label = LABELS.get(method, method) + (" oracle" if setting == "oracle" else "")
        role = "oracle_reference" if setting == "oracle" else "primary" if setting == "no_volume" or method == "leiden" else "supplementary"
        f1 = checked_metric(panel["completed_only"].get("F1"), done, "F1")
        wall = checked_metric(panel["completed_only"].get("outer_wall_seconds"), done, "outer_wall_seconds")
        if f1 is not None and wall is not None and wall["median"] > 0:
            cost.append({"method_setting": name, "method": method, "setting": setting, "role": role, "label": label,
                         "planned": len(planned), "completed_budget": len(done), "F1": f1, "wrapper_wall": wall})
        statuses.append({"method_setting": name, "label": label, "role": role, "planned": len(planned),
                         "completed_budget": len(done), "status_counts": counts,
                         "completed_without_valid_claim": sum(r["status"] == "COMPLETED" and not is_completed(r) for r in planned)})
        for center in ("0.1", "0.2", "0.3", "0.4", "0.5", "0.6"):
            stratum = panel["by_measured_truth_phi"][center]
            planned_bin = [r for r in planned if phi_bin(r.get("truth_phi")) == center]
            done_bin = [r for r in planned_bin if is_completed(r)]
            if stratum["planned"] != len(planned_bin) or stratum["statuses"] != dict(Counter(r["status"] for r in planned_bin)):
                raise ValueError("Summary/CSV measured truth-phi stratum differs: " + name)
            metric = checked_metric(stratum.get("completed_F1"), done_bin, "F1")
            if metric is not None:
                strata.append({"method_setting": name, "method": method, "role": role, "label": label,
                               "truth_phi_center": float(center), "planned": len(planned_bin),
                               "completed_budget": len(done_bin), "F1": metric})
    return {"quality_cost": cost, "truth_phi": strata, "statuses": statuses,
            "planned": len(rows), "completed_budget": sum(is_completed(r) for r in rows)}


def validate_cohort(run, manifest, summary, rows, reference_binding=None):
    actual_sha = digest(run / "manifest.json")
    if summary.get("run_manifest_sha256") != actual_sha:
        raise ValueError("Summary is bound to a different manifest")
    if summary.get("derived_view_sha256", {}).get("query_results.csv") != digest(run / "query_results.csv"):
        raise ValueError("CSV changed after aggregation or lacks its summary pin; refresh derived summary")
    if manifest.get("phase") != "main" or manifest.get("implementation", {}).get("version") != "formal-ordinary-v12-002" or manifest["implementation"].get("exact_cut_backend") != "prepared_region_workspace":
        raise ValueError("This figure requires the prepared v12-002 main cohort")
    binding = None
    if reference_binding is not None:
        from experiments.reproduction.cohort_binding import verify_m4_reference_binding
        binding = verify_m4_reference_binding(reference_binding, run_path=run, verify_files=False)
        if summary.get("cohort_origin") != "FRESH_REPRODUCTION" or summary.get("reference_binding", {}).get("binding_receipt_sha256") != binding.get("binding_receipt_sha256"):
            raise ValueError("Fresh summary/reference binding differs")
    elif actual_sha not in ORIGINAL_MAIN_MANIFESTS or summary.get("cohort_origin") != "ORIGINAL_FROZEN_COHORT":
        raise ValueError("Unrecognized original cohort; fresh results require --reference-binding")
    tasks = {Path(name).stem for name in manifest["jobs"]}
    if len(tasks) != len(manifest["jobs"]) or len(rows) != len(tasks) or {r["task"] for r in rows} != tasks or len({r["task"] for r in rows}) != len(rows):
        raise ValueError("CSV task plan differs from manifest")
    if any(r.get("protocol_sha256") != manifest["protocol_sha256"] or r.get("implementation_exact_cut_backend") != "prepared_region_workspace" for r in rows):
        raise ValueError("CSV includes a different protocol or cut backend")
    by_task = {r["task"]: r for r in rows}
    for name in manifest["jobs"]:
        job = read_json(relative_path(name))
        row, query = by_task[job["task"]], job["query"]
        config = job["configuration"]
        variant = config.get("variant", "R-cap-" + str(config.get("theta", .5)) if config.get("region") == "R-cap" else "main") if job["method"] in ("zrhfd", "zrhfd_ablation") else None
        expected = {"method": job["method"], "setting": job["setting"], "variant": variant,
                    "case_id": query["case_id"], "seed": str(query["seed"]), "query_index": str(query["query_index"])}
        actual = {key: row.get(key) or None if key == "variant" else str(row.get(key)) for key in expected}
        if actual != expected or Path(name).stem != job["task"] or job["protocol_sha256"] != manifest["protocol_sha256"] or job.get("implementation_exact_cut_backend") != "prepared_region_workspace":
            raise ValueError("CSV identity differs from its frozen job: " + name)
    return binding


def write_csv(path, records):
    fields = sorted({key for row in records for key in row})
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in records)


def render(prepared, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "pdf.fonttype": 42, "ps.fonttype": 42})
    names = sorted({r["method"] for r in prepared["quality_cost"] + prepared["truth_phi"]})
    colors = dict(zip(names, plt.get_cmap("tab10").colors))
    artifacts = []
    def save(fig, name):
        for extension in ("svg", "pdf", "png"):
            path = output / (name + "." + extension)
            fig.savefig(path, bbox_inches="tight", **({"dpi": 220} if extension == "png" else {}))
            artifacts.append(path)
        plt.close(fig)
    def interval(ax, x, y, metric, horizontal=False, color="black"):
        ci = metric["median_95_CI"]
        if ci:
            ax.plot(ci if horizontal else [x, x], [y, y] if horizontal else ci, color=color, linewidth=1)
    if prepared["quality_cost"]:
        fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.8), layout="constrained")
        for ax, role, title in zip(axes, ("primary", "oracle_reference"), ("No volume + Leiden", "Oracle-volume reference")):
            points = [p for p in prepared["quality_cost"] if p["role"] == role]
            for p in points:
                x, y, color = p["wrapper_wall"]["median"], p["F1"]["median"], colors[p["method"]]
                ax.plot(x, y, marker="s" if role == "oracle_reference" else "o", linestyle="none", color=color,
                        label=f"{p['label']} ({p['completed_budget']}/{p['planned']})")
                interval(ax, x, y, p["wrapper_wall"], True, color)
                interval(ax, x, y, p["F1"], False, color)
            if not points:
                ax.text(.5, .5, "NOT RUN: no completed observations", ha="center", transform=ax.transAxes)
            ax.set(xscale="log", ylim=(-.02, 1.02), xlabel="Median algorithm-wrapper wall (s)", ylabel="Median F1", title=title)
            ax.grid(True, alpha=.2)
            if points: ax.legend(frameon=False, fontsize=7)
        save(fig, "quality_cost")
    if prepared["truth_phi"]:
        fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.8), layout="constrained")
        for ax, role, title in zip(axes, ("primary", "oracle_reference"), ("Measured truth conductance", "Oracle reference by truth conductance")):
            for method in names:
                points = sorted((p for p in prepared["truth_phi"] if p["role"] == role and p["method"] == method), key=lambda p: p["truth_phi_center"])
                if not points: continue
                ax.plot([p["truth_phi_center"] for p in points], [p["F1"]["median"] for p in points], marker="s" if role == "oracle_reference" else "o", color=colors[method], label=points[0]["label"])
                for p in points: interval(ax, p["truth_phi_center"], p["F1"]["median"], p["F1"], False, colors[method])
            ax.set(xticks=[.1,.2,.3,.4,.5,.6], ylim=(-.02,1.02), xlabel="Measured truth phi, bin center", ylabel="Median completed F1", title=title)
            ax.grid(True,alpha=.2)
            if ax.lines: ax.legend(frameon=False,fontsize=7)
        save(fig, "truth_phi")
    if prepared["statuses"]:
        order = ("COMPLETED", "TIMEOUT", "MEMORY_LIMIT", "ERROR", "WORKER_ERROR", "INTERRUPTED", "NOT_RUN")
        keys = list(order) + sorted({s for row in prepared["statuses"] for s in row["status_counts"]} - set(order))
        fig, ax = plt.subplots(figsize=(8.2, max(3.2, .34 * len(prepared["statuses"]))), layout="constrained")
        left = [0] * len(prepared["statuses"])
        for key in keys:
            values = [r["status_counts"].get(key, 0) for r in prepared["statuses"]]
            if not any(values): continue
            ax.barh(range(len(values)), values, left=left, label=key)
            left = [a+b for a,b in zip(left,values)]
        ax.set(yticks=range(len(left)), yticklabels=[f"{r['label']} ({r['completed_budget']}/{r['planned']})" for r in prepared["statuses"]], xlabel="All planned jobs", title="Planned execution status; completed/plan in labels")
        ax.invert_yaxis(); ax.legend(frameon=False, fontsize=7, ncol=3)
        save(fig,"completion_denominators")
    return artifacts, {"matplotlib": matplotlib.__version__, "backend": matplotlib.get_backend()}


def plot(run, output, reference_binding=None):
    summary, manifest = read_json(run / "summary.json"), read_json(run / "manifest.json")
    with (run / "query_results.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    binding = validate_cohort(run, manifest, summary, rows, reference_binding)
    prepared = prepare_panels(summary, rows)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "quality_cost_points.csv", prepared["quality_cost"])
    write_csv(output / "truth_phi_points.csv", prepared["truth_phi"])
    write_csv(output / "completion_denominators.csv", prepared["statuses"])
    artifacts, runtime = render(prepared, output)
    provenance = {"created_utc": datetime.now(timezone.utc).isoformat(), "status": "COMPLETED" if prepared["quality_cost"] else "NOT_RUN_QUALITY",
                  "cohort_origin": summary["cohort_origin"], "reference_binding": binding,
                  "source_sha256": {"experiments/plot_m4.py": digest(__file__), "experiments/summarize_m4.py": digest(ROOT / "experiments/summarize_m4.py")},
                  "inputs": {name: digest(run / name) for name in ("manifest.json", "summary.json", "query_results.csv")},
                  "raw_source_sha256_recorded_by_summary": summary.get("raw_sha256", {}),
                  "artifact_sha256": {path.name: digest(path) for path in artifacts},
                  "table_sha256": {name: digest(output / name) for name in ("quality_cost_points.csv", "truth_phi_points.csv", "completion_denominators.csv")},
                  "planned": prepared["planned"], "completed_budget": prepared["completed_budget"], "caption": CAPTION,
                  "runtime": runtime, "bootstrap_recomputed": False, "graph_loaded": False,
                  "precondition": "Run the independent source/query/raw cohort audit before trusted scientific reporting"}
    (output / "figure_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (output / "CAPTION.md").write_text(CAPTION + "\n")
    return provenance


def check_schema():
    row = {"task":"fixture", "method":"zrhfd", "setting":"no_volume", "variant":"main", "status":"NOT_RUN", "completion_claim":False, "truth_phi":.1}
    strata = {str(i/10): {"planned": int(i==1), "statuses": {"NOT_RUN":1} if i==1 else {}, "completed_F1":None} for i in range(1,7)}
    panel = {"planned":1,"statuses":{"NOT_RUN":1},"completed_only":{"F1":None,"outer_wall_seconds":None},"by_measured_truth_phi":strata}
    summary = {"panels":{"zrhfd_no_volume":panel}}
    prepared = prepare_panels(summary,[row])
    checks = [prepared["quality_cost"]==[], prepared["truth_phi"]==[], prepared["planned"]==1, prepared["statuses"][0]["status_counts"]=={"NOT_RUN":1}]
    for bad in ("planned", "statuses"):
        mutated = json.loads(json.dumps(summary))
        mutated["panels"]["zrhfd_no_volume"][bad] = 2 if bad=="planned" else {"COMPLETED":1}
        try: prepare_panels(mutated,[row])
        except ValueError: checks.append(True)
        else: checks.append(False)
    for field, value in (("F1", 1.1), ("outer_wall_seconds", 0.0)):
        try: checked_metric({"queries":1,"median":value},[{field:value}],field)
        except ValueError: checks.append(True)
        else: checks.append(False)
    from unittest.mock import patch
    manifest_sha = sorted(ORIGINAL_MAIN_MANIFESTS)[0]
    fake_manifest = {"phase":"main","implementation":{"version":"formal-ordinary-v12-002","exact_cut_backend":"prepared_region_workspace"},"jobs":["results/m4/artificial/jobs/fixture.json"],"protocol_sha256":"fixture"}
    fake_summary = {"run_manifest_sha256":manifest_sha,"cohort_origin":"ORIGINAL_FROZEN_COHORT","derived_view_sha256":{"query_results.csv":manifest_sha}}
    fake_job = {"task":"fixture","method":"zrhfd","setting":"no_volume","configuration":{},"query":{"case_id":"case","seed":1,"query_index":0},"protocol_sha256":"fixture","implementation_exact_cut_backend":"prepared_region_workspace"}
    fake_row = {**row,"case_id":"case","seed":"1","query_index":"0","protocol_sha256":"fixture","implementation_exact_cut_backend":"prepared_region_workspace"}
    with patch(__name__ + ".digest", return_value=manifest_sha), patch(__name__ + ".read_json", return_value=fake_job):
        checks.append(validate_cohort(ROOT / "results/m4/artificial",fake_manifest,fake_summary,[fake_row]) is None)
        try: validate_cohort(ROOT / "results/m4/artificial",fake_manifest,{**fake_summary,"derived_view_sha256":{"query_results.csv":"stale"}},[fake_row])
        except ValueError: checks.append(True)
        else: checks.append(False)
        for field, value in (("method","hfd"),("setting","oracle"),("case_id","wrong"),("seed","2"),("variant","wrong")):
            try: validate_cohort(ROOT / "results/m4/artificial",fake_manifest,fake_summary,[{**fake_row,field:value}])
            except ValueError: checks.append(True)
            else: checks.append(False)
    if not all(checks): raise AssertionError("Artificial schema checks failed")
    return {"status":"PASS","checks":len(checks),"fixture_only":True,"algorithm_execution":False,"numpy_imported":False,"matplotlib_imported":False,"source_sha256":digest(__file__)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="M4 v12-002 run with summary.json and query_results.csv")
    parser.add_argument("--output", help="Project-relative figure directory within figures/m4")
    parser.add_argument("--reference-binding", help="Explicit verified fresh M4 reproduction binding")
    parser.add_argument("--check-schema", action="store_true", help="Tiny stdlib-only schema fixture, no scientific rendering")
    args = parser.parse_args()
    if args.check_schema:
        print(json.dumps(check_schema())); return
    if not args.run or not args.output: parser.error("--run and --output are required for rendering")
    output = relative_path(args.output)
    if not output.resolve().is_relative_to(ROOT / "figures/m4"): parser.error("Figure writes restricted to figures/m4")
    result = plot(relative_path(args.run), output, relative_path(args.reference_binding) if args.reference_binding else None)
    print(json.dumps({"status":result["status"],"planned":result["planned"],"completed":result["completed_budget"]}))


if __name__ == "__main__":
    main()
