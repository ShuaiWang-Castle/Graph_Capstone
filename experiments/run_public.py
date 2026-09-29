"""Immutable full public evaluation; requires a reviewed, hashed freeze manifest."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time
import traceback

import networkx as nx
import numpy as np
import scipy

from degree_contraction import certify_block, contract_certified_blocks, modularity, prepare_graph
from experiments.candidates import candidate_bank
from experiments.datasets import load_snap
from experiments.pipeline import (discovery_quotient_labels, graph_adjacency, networkx_quotient,
                                  reduction_summary, solve_louvain, strict_edge_groups,
                                  summarize_quotient)
from research.baselines import sparse_criteria
from research.baselines.almost_clique import almost_clique
from research.baselines.recursive_cheap import recursive_cheap


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    """Exclusive creation preserves old measurements, including incomplete runs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.suffix == ".gz":
        payload = gzip.compress(payload, mtime=0)
    with path.open("xb") as target:
        target.write(payload)


def validate_freeze(config_path, freeze_path):
    freeze = json.loads(Path(freeze_path).read_text())
    if freeze.get("status") != "frozen_after_independent_design_review":
        raise ValueError("A completed independent freeze review is required")
    if sha256(config_path) != freeze["config_sha256"]:
        raise ValueError("Configuration changed after freeze")
    for path, expected in freeze["runtime_source_sha256"].items():
        if sha256(path) != expected:
            raise ValueError(f"Runtime source changed after freeze: {path}")
    if sha256("data/registry.json") != freeze["data_registry_sha256"]:
        raise ValueError("Data registry changed after freeze")
    return freeze


def candidate_identity(bank):
    payload = json.dumps(bank.blocks, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def identifications(n, groups):
    parent = list(range(n))
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    for group in groups:
        for u in group[1:]:
            parent[find(u)] = find(group[0])
    return n - len({find(u) for u in range(n)})


def evaluate_global_baselines(a, gamma, config, lcc):
    records = {}
    for name in config["global_baselines"]:
        strict = config["global_baseline_policy"]["twin_strict" if name == "degree_proportional_twins" else "pair_strict"]
        started = time.perf_counter()
        result = getattr(sparse_criteria, name)(a, gamma, strict=strict)
        checker_seconds = time.perf_counter() - started
        groups = result.get("merge_groups", strict_edge_groups(a.shape[0], result["safe_edges"]))
        started = time.perf_counter()
        _, summary = reduction_summary(a, groups, largest_component=lcc)
        records[name] = {"status": "completed", "checker_seconds": checker_seconds,
                         "quotient_seconds": time.perf_counter() - started,
                         "decision_count": len(result["safe_edges"]), "strict": strict,
                         "criterion": result["criterion"], "algorithm_scope": result["algorithm_scope"],
                         "decisions": result["safe_edges"], "reduction": summary}
        print(json.dumps({"phase": "baseline", "method": name, "gamma": str(gamma),
                          "removed": summary["removed_vertices"], "seconds": checker_seconds}), flush=True)
    return records


def evaluate_supplied_baselines(a, bank, gamma, config, lcc):
    records = {}
    for name in config["public_supplied_baselines"]:
        if name != "bocker_almost_clique_strict":
            raise ValueError(f"Unknown configured public supplied-block method: {name}")
        started = time.perf_counter()
        prepared = sparse_criteria.prepare_integer_graph(a)
        decisions = [almost_clique(prepared, block, gamma, strict=True,
                                  max_block_size=config["checker"]["exact_max_size"])
                     for block in bank.blocks]
        checker_seconds = time.perf_counter() - started
        accepted = [record["block"] for record in decisions if record["certified"]]
        groups = strict_edge_groups(a.shape[0], [{"u": block[0], "v": u}
                                                for block in accepted for u in block[1:]])
        started = time.perf_counter()
        _, summary = reduction_summary(a, groups, largest_component=lcc)
        records[name] = {"status": "completed", "checker_seconds": checker_seconds,
                         "quotient_seconds": time.perf_counter() - started,
                         "decision_count": len(accepted), "strict": True,
                         "criterion": "Bocker2011 Rule4 supplied-block almost-clique",
                         "algorithm_scope": "one fixed bank of supplied blocks; not full published search",
                         "decisions": decisions, "reduction": summary,
                         "status_counts": dict(Counter(record["verification_status"] for record in decisions))}
        print(json.dumps({"phase": "baseline", "method": name, "gamma": str(gamma),
                          "removed": summary["removed_vertices"], "seconds": checker_seconds}), flush=True)
    return records


def evaluate_recursive_baseline(a, bank, gamma, config, lcc):
    settings = config["recursive_cheap"]
    started = time.perf_counter()
    result = recursive_cheap(a, bank.blocks, gamma,
                             max_block_size=settings["max_block_size"],
                             include_round_decisions=settings["include_round_decisions"])
    checker_seconds = time.perf_counter() - started
    started = time.perf_counter()
    _, summary = reduction_summary(a, result["merge_groups"], largest_component=lcc)
    return {"recursive_cheap": {
        "status": "completed", "checker_seconds": checker_seconds,
        "quotient_seconds": time.perf_counter() - started,
        "strict": result["strict"], "criterion": result["method"],
        "algorithm_scope": result["metadata"]["algorithm_scope"],
        "result": result, "reduction": summary,
        "timing_scope": "whole recursive checking including exact current-quotient construction; separate final reporting quotient"}}


def run_case(dataset, proposal_seed, config, run_dir, config_path, freeze_path, *, progress=None):
    progress = {} if progress is None else progress
    progress.update(phase="freeze_validation")
    freeze = validate_freeze(config_path, freeze_path)
    run_dir = Path(run_dir)
    case_prefix = f"{dataset}-proposal{proposal_seed}"
    write_once(run_dir / f"{case_prefix}-started.json", {
        "dataset": dataset, "proposal_seed": proposal_seed,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_sha256": sha256(config_path), "freeze_sha256": sha256(freeze_path),
        "runtime_source_sha256": freeze["runtime_source_sha256"],
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "networkx": nx.__version__},
        "platform": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "thread_environment": {key: os.getenv(key) for key in config["threads"]}})
    case_started = time.perf_counter()
    progress.update(phase="graph_loading")
    started = time.perf_counter()
    graph, data_metadata = load_snap(dataset)
    lcc = max(nx.connected_components(graph), key=lambda c: (len(c), -min(c)))
    graph_loading_seconds = time.perf_counter() - started
    started = time.perf_counter()
    a = graph_adjacency(graph)
    prepared = prepare_graph(a)
    prepared.exact_degrees()
    preparation_seconds = time.perf_counter() - started
    progress.update(phase="candidate_discovery")
    bank = candidate_bank(graph, seed=proposal_seed,
                          resolution=float(Fraction(config["proposal"]["resolution"])),
                          minimum_size=config["proposal"]["minimum_size"])
    bank_hash = candidate_identity(bank)
    write_once(run_dir / f"{case_prefix}-candidates.json.gz", {
        "bank_sha256": bank_hash, "blocks": bank.blocks,
        "discovery_labels": bank.discovery_labels.tolist(), "seed": proposal_seed,
        "proposal_seconds": bank.proposal_seconds, "refinement_seconds": bank.refinement_seconds,
        "spectral_splits": bank.spectral_splits, "component_splits": bank.component_splits,
        "fallback_splits": bank.fallback_splits, "dataset": data_metadata})
    print(json.dumps({"phase": "candidates", "dataset": dataset, "proposal_seed": proposal_seed,
                      "candidates": len(bank.blocks), "seconds": bank.proposal_seconds + bank.refinement_seconds}), flush=True)
    for gamma_index, gamma_text in enumerate(config["gamma"]):
        gamma = Fraction(gamma_text)
        progress.update(phase="global_baselines", gamma=str(gamma))
        baseline_records = evaluate_global_baselines(a, gamma, config, lcc)
        progress.update(phase="supplied_block_baselines")
        baseline_records.update(evaluate_supplied_baselines(a, bank, gamma, config, lcc))
        progress.update(phase="recursive_cheap_baseline")
        baseline_records.update(evaluate_recursive_baseline(a, bank, gamma, config, lcc))
        checker_started = time.perf_counter()
        progress.update(phase="degree_median_certification")
        certificates, records = [], []
        checker = config["checker"]
        for block in bank.blocks:
            if len(block) > checker["exact_max_size"]:
                records.append({"block": list(block), "size": len(block), "certified": False,
                                "strict": False, "verification_status": "exact_size_limit_preassembly"})
                continue
            certificate = certify_block(prepared, block, gamma, verification=checker["verification"],
                                        exact_max_size=checker["exact_max_size"],
                                        dense_max_size=checker["dense_max_size"],
                                        screen_tolerance=checker["screen_tolerance"])
            records.append(certificate.to_dict())
            if certificate.certified:
                certificates.append(certificate)
        checker_seconds = time.perf_counter() - checker_started
        progress.update(phase="quotient")
        started = time.perf_counter()
        quotient = contract_certified_blocks(prepared, certificates)
        quotient_seconds = time.perf_counter() - started
        summary = summarize_quotient(a, quotient, largest_component=lcc)
        started = time.perf_counter()
        q_graph = networkx_quotient(quotient.adjacency)
        quotient_conversion_seconds = time.perf_counter() - started
        started = time.perf_counter()
        q_discovery = modularity(prepared, bank.discovery_labels, gamma)
        original_discovery_evaluation_seconds = time.perf_counter() - started
        started = time.perf_counter()
        q_discovery_quotient = modularity(quotient.adjacency, discovery_quotient_labels(bank.discovery_labels, quotient), gamma)
        if abs(q_discovery - q_discovery_quotient) > 1e-10:
            raise ArithmeticError("Discovery incumbent was not retained by quotient")
        quotient_discovery_evaluation_seconds = time.perf_counter() - started
        discovery_incumbent_seconds = original_discovery_evaluation_seconds + quotient_discovery_evaluation_seconds
        new_groups = summary["merge_groups"]
        for result in baseline_records.values():
            old_groups = result["reduction"]["merge_groups"]
            joint = identifications(len(graph), new_groups + old_groups)
            result["new_identifications_beyond_baseline"] = joint - identifications(len(graph), old_groups)
            result["baseline_identifications_beyond_new"] = joint - identifications(len(graph), new_groups)
        statuses = Counter(record["verification_status"] for record in records)
        print(json.dumps({"phase": "certification", "dataset": dataset, "proposal_seed": proposal_seed,
                          "gamma": str(gamma), "accepted": len(certificates),
                          "removed": summary["removed_vertices"], "seconds": checker_seconds}), flush=True)
        downstream = []
        preprocessing_seconds = preparation_seconds + bank.proposal_seconds + bank.refinement_seconds + checker_seconds + quotient_seconds + quotient_conversion_seconds + discovery_incumbent_seconds
        dataset_index = config["public_datasets"].index(dataset)
        for downstream_index, seed in enumerate(config["downstream"]["seeds"]):
            progress.update(phase="downstream", downstream_seed=seed)
            order = ["unreduced", "reduced"]
            if (dataset_index + proposal_seed + gamma_index + downstream_index) % 2:
                order.reverse()
            pair = {"seed": seed, "execution_order": order}
            for arm in order:
                labels, result = solve_louvain(graph if arm == "unreduced" else q_graph,
                                               a if arm == "unreduced" else quotient.adjacency, gamma, seed)
                if arm == "reduced":
                    started = time.perf_counter()
                    lifted = quotient.lift_labels(labels)
                    q_lifted = modularity(prepared, lifted, gamma)
                    if abs(q_lifted - result["modularity"]) > 1e-10:
                        raise ArithmeticError("Lifted objective differs from quotient")
                    result["lift_and_original_evaluation_seconds"] = time.perf_counter() - started
                    result["modularity_lifted"] = q_lifted
                    result["labels"] = lifted.tolist()
                else:
                    result["labels"] = labels.tolist()
                result["best_of_discovery_and_downstream"] = max(q_discovery, result["modularity"])
                pair[arm] = result
            downstream.append(pair)
        workloads = []
        for count in config["downstream"]["workload_prefixes"]:
            unreduced = sum(p["unreduced"]["solver_seconds"] + p["unreduced"]["label_conversion_seconds"] + p["unreduced"]["objective_evaluation_seconds"] for p in downstream[:count])
            reduced = sum(p["reduced"]["solver_seconds"] + p["reduced"]["label_conversion_seconds"] + p["reduced"]["objective_evaluation_seconds"] + p["reduced"]["lift_and_original_evaluation_seconds"] for p in downstream[:count])
            discovery_control = bank.proposal_seconds + original_discovery_evaluation_seconds + unreduced
            workloads.append({"solves": count, "unreduced_seconds": unreduced,
                              "discovery_plus_unreduced_seconds": discovery_control,
                              "full_reduced_seconds": preprocessing_seconds + reduced,
                              "speedup_vs_cold_unreduced": unreduced / (preprocessing_seconds + reduced),
                              "speedup_vs_discovery_control": discovery_control / (preprocessing_seconds + reduced)})
        write_once(run_dir / f"{case_prefix}-gamma{gamma_index}.json.gz", {
            "status": "completed", "dataset": data_metadata, "proposal_seed": proposal_seed,
            "gamma": str(gamma), "bank_sha256": bank_hash, "graph_fingerprint": prepared.fingerprint,
            "graph_loading_seconds": graph_loading_seconds, "preparation_seconds": preparation_seconds,
            "proposal_seconds": bank.proposal_seconds, "refinement_seconds": bank.refinement_seconds,
            "checker_seconds": checker_seconds, "quotient_seconds": quotient_seconds,
            "quotient_conversion_seconds": quotient_conversion_seconds, "preprocessing_seconds": preprocessing_seconds,
            "discovery_incumbent_seconds": discovery_incumbent_seconds,
            "original_discovery_evaluation_seconds": original_discovery_evaluation_seconds,
            "quotient_discovery_evaluation_seconds": quotient_discovery_evaluation_seconds,
            "timing_scope": "in-memory computation; reporting summaries, serialization and shared raw graph loading excluded from speedup",
            "certification_status_counts": dict(statuses), "candidate_certificates": records,
            "reduction": summary, "global_baselines": baseline_records,
            "modularity_discovery": q_discovery, "downstream": downstream, "workloads": workloads,
            "peak_case_process_RSS_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == "Darwin" else 1024),
            "memory_semantics": "peak RSS; complete process with shared/retained objects, not isolated method memory"})
        print(json.dumps({"phase": "gamma_complete", "dataset": dataset, "proposal_seed": proposal_seed,
                          "gamma": str(gamma), "workloads": workloads}), flush=True)
    write_once(run_dir / f"{case_prefix}-completed.json", {"status": "completed", "seconds": time.perf_counter() - case_started})


def make_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="experiments/config.json")
    parser.add_argument("--freeze", default="experiments/freeze.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--proposal-seed", type=int, required=True)
    return parser


def main():
    args = make_parser().parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.dataset not in config["public_datasets"] or args.proposal_seed not in config["proposal"]["seeds"]:
        raise ValueError("Case outside frozen public grid")
    if any(os.getenv(key) != value for key, value in config["threads"].items()):
        raise ValueError("Set the frozen BLAS/OpenMP thread environment before import/execution")
    progress = {}
    try:
        run_case(args.dataset, args.proposal_seed, config, args.run_dir, args.config, args.freeze, progress=progress)
    except BaseException as error:
        prefix = Path(args.run_dir) / f"{args.dataset}-proposal{args.proposal_seed}"
        if Path(str(prefix) + "-started.json").exists() and not Path(str(prefix) + "-completed.json").exists():
            failure = {"status": "failed_or_interrupted", "dataset": args.dataset,
                       "proposal_seed": args.proposal_seed, "last_progress": progress,
                       "error_type": type(error).__name__, "message": str(error),
                       "traceback": traceback.format_exc(), "time_utc": datetime.now(timezone.utc).isoformat()}
            try:
                write_once(Path(str(prefix) + "-failure.json"), failure)
            except FileExistsError:
                pass
        raise


if __name__ == "__main__":
    main()
