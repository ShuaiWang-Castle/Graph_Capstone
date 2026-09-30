#!/usr/bin/env python3
"""Post-run presentation only; never scores covers or decides a gate.

Run only after analyze_gate.py has produced a complete, reviewed output.
The figure shows observed paired complete costs and labels all denominators.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true", help="Replace only this derived rendering; measurements and gate outputs remain unchanged.")
    args = parser.parse_args()
    analysis = Path(args.analysis_dir)
    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise FileExistsError("Figure output already exists; keep the earlier rendering")
    gate = json.loads((analysis / "gate-analysis.json").read_text(encoding="utf-8"))
    if gate.get("planned_jobs") != 288 or gate.get("planned_per_arm") != 72:
        raise ValueError("Unexpected denominator; refuse presentation")
    with (analysis / "pairs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    wanted = {"BMM_vs_elementwise": "BMM", "CSR_vs_elementwise": "sampled CSR"}
    observed = {n: {label: [] for label in wanted} for n in (1000, 5000)}
    planned = {n: {label: 0 for label in wanted} for n in (1000, 5000)}
    for row in rows:
        label = row["pair"]
        if label not in wanted:
            continue
        n = int(row["n"])
        planned[n][label] += 1
        if row["paired_valid"] == "True":
            observed[n][label].append((float(row["reference_seconds"]), float(row["compared_seconds"])))
    if any(planned[n][label] != 36 for n in planned for label in wanted):
        raise ValueError("Missing planned pair rows; refuse plot")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Separate cost ranges: sharing y silently clips every n1000 point when
    # the n5000 panel sets its much larger limits.
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
    colors = {"BMM_vs_elementwise": "#2574a9", "CSR_vs_elementwise": "#c85a17"}
    for ax, n in zip(axes, (1000, 5000)):
        values = [v for label in wanted for pair in observed[n][label] for v in pair]
        lo, hi = (min(values), max(values)) if values else (1.0, 100.0)
        lo, hi = lo * .8, hi * 1.25
        ax.plot([lo, hi], [lo, hi], color="0.35", linestyle="--", linewidth=1, label="equal full cost")
        for label, name in wanted.items():
            points = observed[n][label]
            if points:
                ax.scatter([p[0] for p in points], [p[1] for p in points],
                           s=19, alpha=.8, color=colors[label], label=f"{name} ({len(points)}/36 paired)")
            else:
                ax.plot([], [], color=colors[label], label=f"{name} (0/36 paired)")
        ax.set(xlim=(lo, hi), ylim=(lo, hi),
               title=f"n={n}; 36 planned case×seed pairs per backend",
               xlabel="elementwise complete pipeline seconds")
        ax.grid(alpha=.2)
        ax.legend(fontsize=7, loc="best")
        ax.set_ylabel("compared backend complete pipeline seconds")
    fig.suptitle("Development CPU/oracle-K paired costs; missing/failed pairs retained in denominators")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
