"""Standard static M5 scientific figure; no invented points for empty panels."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
try:
    from .inventory import ROOT, METHODS, OFFICIAL_BYTES_SHA, csv_write, digest, project_path, read_json, utc, validate_analysis_cohort
except ImportError:
    from inventory import ROOT, METHODS, OFFICIAL_BYTES_SHA, csv_write, digest, project_path, read_json, utc, validate_analysis_cohort

LABELS = {"zr_hfd": "ZR-HFD", "zh_prov": "ZH-prov", "hfd_no_volume": "HFD", "hfd_oracle": "HFD oracle",
    "tlhfd_no_volume": "TL*", "tlhfd_oracle": "TL* oracle", "clique_acl_no_volume": "Clique ACL", "clique_acl_oracle": "Clique ACL oracle"}


def point_records(summary):
    points = []
    for panel in ("contact-high-school", "trivago-clicks", "HSBM"):
        for method, data in summary["panels"].get(panel, {}).get("methods", {}).items():
            f1, cost = data["completed_only"]["F1"], data["completed_only"]["controller_wall_seconds"]
            if f1["median"] is None or cost["median"] is None or cost["median"] <= 0:
                continue
            points.append({"panel": panel, "method": method, "label": LABELS[method], "F1_median": f1["median"],
                "controller_wall_median_seconds": cost["median"], "planned": data["planned"], "completed_budget": data["completed_budget"],
                "F1_median_95_CI": f1.get("bootstrap_median", {}).get("percentile_95_CI"),
                "wall_median_95_CI": cost.get("bootstrap_median", {}).get("percentile_95_CI"),
                "scope": summary["panels"][panel]["statistical_scope"]})
    return points


def plot(input_directory, output_directory, reproduced_cohort=False, reference_binding=None):
    if reproduced_cohort and output_directory.resolve() == ROOT / "figures/m5/official_v12_001":
        raise ValueError("Fresh plot cannot overwrite original official figures")
    summary_path = input_directory / "summary.json"
    summary = read_json(summary_path)
    analysis_provenance = read_json(input_directory / "analysis_provenance.json")
    if digest(summary_path) != analysis_provenance["outputs"]["summary.json"]:
        raise RuntimeError("Summary differs from the analysis provenance")
    for name, expected in analysis_provenance["inputs"].items():
        if digest(input_directory / name) != expected:
            raise RuntimeError("Plot input differs from analysis provenance: " + name)
    report = read_json(input_directory / "inventory.json")
    binding = validate_analysis_cohort(report, reproduced_cohort, reference_binding)
    if summary.get("cohort_origin") != report.get("cohort_origin") or summary.get("reference_binding_sha256") != report.get("reference_binding_sha256") or summary["inventory_manifest_sha256"] != report["manifest"]["manifest_sha256"] or summary["inventory_frozen_sha256"] != report["manifest"]["frozen_sha256"]:
        raise RuntimeError("Summary differs from the inventory cohort/binding")
    if report.get("cohort_origin") not in ("ORIGINAL_FROZEN_COHORT", "FRESH_REPRODUCTION"):
        raise RuntimeError("Artificial fixtures cannot produce scientific result figures")
    points = point_records(summary)
    output_directory.mkdir(parents=True, exist_ok=True)
    provenance = {"created_utc": utc(), "plot_source_sha256": digest(__file__), "summary_sha256": digest(summary_path),
        "cohort_origin": report["cohort_origin"], "reference_binding": binding,
        "analysis_provenance_sha256": digest(input_directory / "analysis_provenance.json"),
        "manifest_sha256": summary["inventory_manifest_sha256"], "frozen_sha256": summary["inventory_frozen_sha256"],
        "status": "NOT_RUN" if not points else "READY", "point_count": len(points),
        "caption": "Completed requested budgets only, with all planned/completed counts. Cost is controller wall, archival excluded. Main touched support volume does not establish engineering locality.",
        "statistical_scope": "Contact/Trivago intervals condition on each fixed topology; HSBM graph/query hierarchy. No convergence claim."}
    if not points:
        provenance["reason"] = "No completed quality/cost observations; no synthetic points or empty numeric chart produced"
        (output_directory / "quality_cost_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        return provenance
    if summary["integrity_status"] != "PASS":
        raise RuntimeError("A scientific result plot requires verified PASS inventory")
    if not reproduced_cohort and summary["inventory_manifest_sha256"] != OFFICIAL_BYTES_SHA:
        raise RuntimeError("Scientific figure accepts only the pinned official M5 cohort; artificial fixtures cannot become result points")
    # Matplotlib is imported only when an authorized actual plotting stage runs.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    panels = [p for p in ("contact-high-school", "trivago-clicks", "HSBM") if any(r["panel"] == p for r in points)]
    colors = dict(zip(METHODS, plt.get_cmap("tab10").colors))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, axes = plt.subplots(1, len(panels), figsize=(4.0 * len(panels), 3.8), squeeze=False, layout="constrained")
    for ax, panel in zip(axes[0], panels):
        for point in [r for r in points if r["panel"] == panel]:
            x, y = point["controller_wall_median_seconds"], point["F1_median"]
            xc, yc = point["wall_median_95_CI"], point["F1_median_95_CI"]
            color = colors[point["method"]]
            ax.plot(x, y, color=color, marker="s" if point["method"].endswith("_oracle") else "o", markersize=5,
                linestyle="none", label=f"{point['label']} ({point['completed_budget']}/{point['planned']})")
            # Draw the actual interval endpoints, including a percentile CI
            # that need not contain the estimate; do not silently truncate it.
            if xc:
                ax.plot(xc, [y, y], color=color, linewidth=1)
            if yc:
                ax.plot([x, x], yc, color=color, linewidth=1)
        ax.set(xscale="log", ylim=(-.02, 1.02), title=panel, xlabel="Median controller wall (s)", ylabel="Median F1")
        ax.grid(True, which="major", alpha=.2)
        ax.legend(frameon=False, fontsize=7)
    target = output_directory / "quality_cost"
    fig.savefig(target.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(target.with_suffix(".png"), dpi=220, bbox_inches="tight")
    plt.close(fig)
    csv_write(output_directory / "quality_cost_points.csv", points)
    provenance.update({"status": "COMPLETED", "figure_sha256": {p.name: digest(p) for p in (target.with_suffix(".pdf"), target.with_suffix(".png"))},
        "points_sha256": digest(output_directory / "quality_cost_points.csv"), "plot_runtime": {"matplotlib_version": matplotlib.__version__, "backend": matplotlib.get_backend()}})
    (output_directory / "quality_cost_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="results/m5_analysis/official_v12_001")
    parser.add_argument("--output", default="figures/m5/official_v12_001")
    parser.add_argument("--reproduced-cohort", action="store_true")
    parser.add_argument("--reference-binding", help="Verified fresh reference binding, paired with --reproduced-cohort")
    args = parser.parse_args()
    output = project_path(args.output)
    if not output.is_relative_to(ROOT / "figures/m5"):
        parser.error("Figure writes must stay within figures/m5")
    if args.reproduced_cohort != bool(args.reference_binding):
        parser.error("Both --reproduced-cohort and --reference-binding are required for fresh mode")
    if args.reproduced_cohort and output.resolve() == ROOT / "figures/m5/official_v12_001":
        parser.error("Fresh figures cannot overwrite original official figures")
    result = plot(project_path(args.input), output, args.reproduced_cohort,
                  project_path(args.reference_binding) if args.reference_binding else None)
    print(json.dumps({"status": result["status"], "points": result["point_count"]}))


if __name__ == "__main__":
    main()
