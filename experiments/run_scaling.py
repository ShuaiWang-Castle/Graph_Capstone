"""One isolated process per configured checker/block and measurement type."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import json
import os
from pathlib import Path
import platform
import resource
import time
import tracemalloc

import networkx as nx
import numpy as np
import scipy

from degree_contraction import certify_block, prepare_graph
from experiments.families import load_family
from experiments.pipeline import graph_adjacency
from experiments.run_public import sha256, validate_freeze, write_once
from research.baselines.weighted_reference import (dense_exterior_diagnostic,
    prepare_weighted_reference_graph, weighted_collective_reference)


def peak_rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == "Darwin" else 1024)


def run_scaling(case, method, replicate, measurement, config, run_dir, *, provenance):
    started = time.perf_counter()
    graph, metadata = load_family(case["family"], **case["parameters"], include_oracle_blocks=True)
    a = graph_adjacency(graph)
    loading_seconds = time.perf_counter() - started
    block = tuple(metadata["oracle_blocks"][0])
    started = time.perf_counter()
    if method == "degree_median":
        prepared = prepare_graph(a)
        prepared.exact_degrees()  # available graph-wide quantities are charged separately
    else:
        prepared = prepare_weighted_reference_graph(a)
    preparation_seconds = time.perf_counter() - started
    rss_before = peak_rss()
    if measurement == "memory":
        tracemalloc.start()
    started = time.perf_counter()
    if method == "degree_median":
        result = certify_block(prepared, block, Fraction(1), **{
            key: value for key, value in config["checker"].items() if key != "oversize_policy"}).to_dict()
    elif method == "degree_full_pair":
        result = weighted_collective_reference(prepared, block, Fraction(1),
                    penalty="full_pair_distance", exact_max_size=config["checker"]["exact_max_size"])
    elif method == "dense_exterior_diagnostic":
        result = dense_exterior_diagnostic(prepared, block, Fraction(1),
                    max_vertices=20000, max_block_size=config["checker"]["exact_max_size"])
    else:
        raise ValueError("Unknown scaling method")
    checker_seconds = time.perf_counter() - started
    if measurement == "memory":
        traced_current, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        traced_current = traced_peak = None
    record = {"status": "completed", "case_id": case["case_id"], "dataset": metadata,
              "method": method, "replicate": replicate, "measurement": measurement, "gamma": "1",
              "loading_seconds": loading_seconds, "preparation_seconds": preparation_seconds,
              "checker_seconds": checker_seconds, "checker_result": result,
              "process_peak_RSS_before_checker_bytes": rss_before, "process_peak_RSS_bytes": peak_rss(),
              "checker_traced_current_bytes": traced_current, "checker_traced_peak_bytes": traced_peak,
              "memory_semantics": "isolated complete process RSS includes graph/preparation; tracemalloc covers Python and registered NumPy allocations, excludes untracked native allocations",
              "timing_semantics": "memory-profiled timings are excluded from performance summaries",
              "provenance": provenance,
              "time_utc": datetime.now(timezone.utc).isoformat()}
    path = Path(run_dir) / f"scaling-{case['case_id']}-{method}-{measurement}-{replicate}.json.gz"
    write_once(path, record)
    print(json.dumps({"phase": "scaling_complete", "case_id": case["case_id"], "method": method,
                      "measurement": measurement, "replicate": replicate, "seconds": checker_seconds,
                      "certified": result["certified"]}), flush=True)


def make_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/config.json")
    parser.add_argument("--freeze", default="experiments/freeze.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--replicate", type=int, default=0)
    parser.add_argument("--measurement", choices=("timing", "memory"), default="timing")
    return parser


def main():
    args = make_parser().parse_args()
    freeze = validate_freeze(args.config, args.freeze)
    config = json.loads(Path(args.config).read_text())
    if any(os.getenv(key) != value for key, value in config["threads"].items()):
        raise ValueError("Set the frozen thread environment before execution")
    case = next(s for s in config["controlled_cases"] if s["case_id"] == args.case_id)
    if case["family"] != "profile_scaling" or args.method not in config["scaling"]["methods"]:
        raise ValueError("Case/method outside frozen scaling stratum")
    maximum = config["scaling"]["replicate_count"] if args.measurement == "timing" else config["scaling"]["memory_replicate_count"]
    if not 0 <= args.replicate < maximum:
        raise ValueError("Replicate outside frozen grid")
    provenance = {"config_sha256": sha256(args.config), "freeze_sha256": sha256(args.freeze),
                  "runtime_source_sha256": freeze["runtime_source_sha256"],
                  "versions": {"python": platform.python_version(), "numpy": np.__version__,
                               "scipy": scipy.__version__, "networkx": nx.__version__},
                  "platform": platform.platform(), "machine": platform.machine(),
                  "thread_environment": {key: os.getenv(key) for key in config["threads"]}}
    run_scaling(case, args.method, args.replicate, args.measurement, config, args.run_dir, provenance=provenance)


if __name__ == "__main__":
    main()
