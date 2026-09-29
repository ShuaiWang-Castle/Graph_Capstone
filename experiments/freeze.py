"""Create a non-overwriting execution snapshot after independent design review."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

import networkx as nx
import numpy as np
import scipy

from experiments.run_public import sha256, write_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/config.json")
    parser.add_argument("--review", default="reviews/supervisor-experiment-design.md")
    parser.add_argument("--output", default="experiments/freeze.json")
    parser.add_argument("--validation", required=True)
    args = parser.parse_args()
    review = Path(args.review)
    if "approved_for_configuration_freeze" not in review.read_text():
        raise ValueError("Independent reviewer has not approved this configuration freeze")
    validation = json.loads(Path(args.validation).read_text())
    if validation.get("status") != "passed":
        raise ValueError("Engineering validation must pass before freeze")
    sources = set()
    for directory in ("src/degree_contraction", "experiments", "research/baselines", "research/full_kapoce"):
        for extension in ("*.py", "*.cpp"):
            sources.update(Path(directory).glob(extension))
    sources.update(Path(path) for path in (
        "research/baselines/build/kapoce_selected", "research/baselines/build-provenance.json",
        "research/full_kapoce/build/kapoce_full", "research/full_kapoce/build-provenance.json",
        "research/full_kapoce/source-provenance.json", "research/full_kapoce/dependency-provenance.json",
        "requirements-lock.txt",
    ))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    snapshot = {
        "status": "frozen_after_independent_design_review",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
        "config_sha256": sha256(args.config),
        "runtime_source_sha256": {str(path): sha256(path) for path in sorted(sources)},
        "data_registry_sha256": sha256("data/registry.json"),
        "processed_metadata_sha256": sha256("data/processed-metadata.json"),
        "protocol_sha256": sha256("experiments/protocol.md"),
        "independent_review": {"path": args.review, "sha256": sha256(review),
                               "verdict": "approved_for_configuration_freeze"},
        "engineering_validation": {"path": args.validation, "sha256": sha256(args.validation),
                                   "record": validation},
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "networkx": nx.__version__},
        "hardware": {"platform": platform.platform(), "machine": platform.machine()},
        "performance_status_at_freeze": "no public certification or confirmatory benchmark measured",
        "scope": "exactly the complete predeclared capped implementation and comparison configuration",
    }
    write_once(args.output, snapshot)
    print(json.dumps({"freeze": args.output, "sha256": sha256(args.output),
                      "runtime_files": len(sources), "source_commit": commit}))


if __name__ == "__main__":
    main()
