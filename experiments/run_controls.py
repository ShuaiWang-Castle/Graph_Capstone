"""Immutable controlled/development runs, gated by an independently reviewed freeze.

Generator reference blocks are consumed only by labeled criterion comparisons.
Discovery sees only the observed graph. Numerical MILP results never certify an
optimum or contraction, including reported zero gaps and numerical ties.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from fractions import Fraction
import importlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import time

import networkx as nx
import numpy as np
import scipy

from degree_contraction import (
    certify_block, contract_certified_blocks, modularity_exact, prepare_graph,
)
from experiments.candidates import candidate_bank
from experiments.datasets import load_development
from experiments.exact_oracle import check_c_subinstance, solve_modularity
from experiments.families import load_family
from experiments.grid import controlled_grid
from experiments.pipeline import (
    discovery_quotient_labels, graph_adjacency, reduction_summary,
    strict_edge_groups, summarize_quotient,
)
from experiments.run_public import (
    candidate_identity, evaluate_recursive_baseline, identifications,
    sha256, validate_freeze, write_once,
)
from research.baselines import block_criteria, sparse_criteria
from research.baselines.almost_clique import almost_clique
from research.baselines.run_kapoce import run_case as run_native_case
from research.full_kapoce.run_full import run_full_case


def jsonable(value):
    """Keep exact values as fractions and nonfinite diagnostics as string markers."""
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def peak_rss_bytes():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == "Darwin" else 1024)


def _graph_hash(graph):
    edges = sorted((min(u, v), max(u, v), str(Fraction(str(data.get("weight", 1)))))
                   for u, v, data in graph.edges(data=True))
    import hashlib
    payload = json.dumps({"n": len(graph), "edges": edges}, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _unavailable(method, reason, **metadata):
    return {"method": method, "available": False, "certified": False, "strict": False,
            "status": "unavailable", "verification_status": reason, "metadata": metadata}


def _weighted_module():
    """Lazy import permits construction/testing before the independent module lands."""
    try:
        return importlib.import_module("research.baselines.weighted_reference")
    except ModuleNotFoundError as error:
        if error.name != "research.baselines.weighted_reference":
            raise
        return None


def prepare_references(a):
    started = time.perf_counter()
    integer_graph = sparse_criteria.prepare_integer_graph(a)
    integer_seconds = time.perf_counter() - started
    module = _weighted_module()
    started = time.perf_counter()
    weighted_graph = None if module is None else module.prepare_weighted_reference_graph(a)
    return integer_graph, module, weighted_graph, {
        "integer_baseline_preparation_seconds": integer_seconds,
        "weighted_reference_preparation_seconds": time.perf_counter() - started,
        "weighted_reference_available": module is not None,
        "preparation_scope": "one shared immutable prepared representation per graph per baseline family",
    }


def _core_record(prepared, block, gamma, checker, *, verification=None):
    if len(block) > checker["exact_max_size"]:
        return None, {"block": list(block), "size": len(block), "gamma": str(gamma),
                      "certified": False, "strict": False, "available": False,
                      "verification_status": "exact_size_limit_preassembly"}
    certificate = certify_block(
        prepared, block, gamma, verification=verification or checker["verification"],
        exact_max_size=checker["exact_max_size"], dense_max_size=checker["dense_max_size"],
        screen_tolerance=checker["screen_tolerance"],
    )
    record = certificate.to_dict()
    record["available"] = True
    return certificate, record


def evaluate_global_baselines(a, integer_graph, gamma, config, lcc):
    records = {}
    for name in config["global_baselines"]:
        strict = config["global_baseline_policy"]["twin_strict" if name == "degree_proportional_twins" else "pair_strict"]
        if not strict and name != "degree_proportional_twins":
            raise ValueError("Weak generic pair decisions must remain individual, not simultaneous quotient groups")
        started = time.perf_counter()
        result = getattr(sparse_criteria, name)(integer_graph, gamma, strict=strict)
        checker_seconds = time.perf_counter() - started
        groups = result.get("merge_groups", strict_edge_groups(a.shape[0], result["safe_edges"]))
        started = time.perf_counter()
        _, reduction = reduction_summary(a, groups, largest_component=lcc)
        records[name] = {"status": "completed", "strict": strict, "checker_seconds": checker_seconds,
                         "quotient_seconds": time.perf_counter() - started,
                         "decision_count": len(result["safe_edges"]), "criterion": result["criterion"],
                         "algorithm_scope": result["algorithm_scope"], "decisions": result["safe_edges"],
                         "reduction": reduction}
    return records


def evaluate_block_references(prepared, integer_graph, weighted_module, weighted_graph,
                              block, gamma, config, *, include_weak_bocker=False):
    """Same supplied block in all named methods; no outcome alters the bank."""
    records = {}
    caps = config["supplied_block_config"]
    checker = config["checker"]
    for method in config["supplied_block_methods"]:
        started = time.perf_counter()
        if method == "degree_median":
            _, result = _core_record(prepared, block, gamma, checker)
            result["comparison_role"] = "production capped AUTO median checker, preserved unchanged"
            records[method] = {"checker_seconds": time.perf_counter() - started, "result": result}
            # This forced-exact core result is a side panel, never substituted
            # for AUTO acceptance or included in its measured checker time.
            started = time.perf_counter()
            _, exact = _core_record(prepared, block, gamma, checker, verification="exact")
            exact["comparison_role"] = "forced-EXACT core threshold side panel; not production AUTO"
            records["degree_median_forced_exact"] = {"checker_seconds": time.perf_counter() - started, "result": exact}
            if weighted_module is None:
                independent = _unavailable("degree_median_independent_exact", "independent_reference_module_missing")
                seconds = 0.0
            else:
                started = time.perf_counter()
                independent = weighted_module.weighted_collective_reference(
                    weighted_graph, block, gamma, center="median", penalty="center",
                    exact_max_size=caps["exact_max_size"], diagnostics=True,
                )
                seconds = time.perf_counter() - started
            independent["comparison_role"] = "independent exact-rational median threshold/reference side panel"
            records["degree_median_independent_exact"] = {"checker_seconds": seconds, "result": independent}
            continue
        if method in {"degree_zero", "degree_anchor", "degree_full_pair"}:
            if weighted_module is None:
                result = _unavailable(method, "independent_reference_module_missing")
            else:
                center = "zero" if method == "degree_zero" else "anchor" if method == "degree_anchor" else "median"
                penalty = "full_pair_distance" if method == "degree_full_pair" else "center"
                result = weighted_module.weighted_collective_reference(
                    weighted_graph, block, gamma, center=center, penalty=penalty,
                    exact_max_size=caps["exact_max_size"], diagnostics=True,
                )
                result["comparison_role"] = "independent forced-EXACT ablation; no AUTO algorithm substitution"
        elif method == "uniform_copy":
            result = block_criteria.uniform_copy_contrast(
                integer_graph, block, gamma, exact_max_size=caps["exact_max_size"],
                diagnostic_max_size=128, max_graph_size=caps["uniform_max_graph_vertices"],
                max_exterior_size=caps["uniform_max_exterior_vertices"],
            )
        elif method == "lange_positive_closure_star":
            result = block_criteria.positive_closure_block(
                integer_graph, block, gamma, max_block_size=caps["exact_max_size"],
                max_closure_vertices=caps["positive_closure_max_vertices"],
                signed_enumeration_max_size=caps["signed_internal_enumeration_max_size"],
            )
        elif method == "bocker_almost_clique":
            result = almost_clique(integer_graph, block, gamma,
                                   max_block_size=caps["exact_max_size"], strict=True)
        else:
            raise ValueError(f"Unknown configured supplied-block method: {method}")
        records[method] = {"checker_seconds": time.perf_counter() - started, "result": result}
        if method == "bocker_almost_clique" and include_weak_bocker:
            started = time.perf_counter()
            weak = almost_clique(integer_graph, block, gamma,
                                 max_block_size=caps["exact_max_size"], strict=False)
            weak["comparison_role"] = "standalone weak equality reference; never unioned or used in production coverage"
            records["bocker_almost_clique_weak_side"] = {
                "checker_seconds": time.perf_counter() - started, "result": weak}
    return records


def evaluate_c_subinstance(prepared, block, gamma, config):
    """Exact ten-active-vertex attempt, then bounded numerical diagnostic."""
    started = time.perf_counter()
    limits = config["c_subinstance"]
    exact = check_c_subinstance(
        prepared, block, gamma, arithmetic="exact",
        max_vertices=limits["exact_max_active_vertices"],
        reduce_nonpositive_exterior=True,
    )
    attempts = [{"arithmetic": "exact", "result": jsonable(exact)}]
    result = exact
    if exact.status == "unavailable":
        result = check_c_subinstance(
            prepared, block, gamma, arithmetic="numerical",
            max_vertices=limits["numerical_max_active_vertices"],
            time_limit=limits["numerical_time_limit_seconds"], tolerance=limits["tolerance"],
            reduce_nonpositive_exterior=True,
        )
        attempts.append({"arithmetic": "numerical", "result": jsonable(result)})
        if result.certified:
            raise ArithmeticError("Numerical C-subinstance output cannot be a certificate")
    return {"method": "SEA2022 C-subinstance isolation-score condition",
            "comparison_role": "supplied candidate oracle, never candidate generation",
            "status": result.status, "available": result.status not in {"unavailable", "unresolved"},
            "certified": result.certified, "strict": False,
            "checker_seconds": time.perf_counter() - started, "attempts": attempts,
            "tie_policy": "compare isolation score to optimum including ties; never infer isolation from witness labels"}


def evaluate_bank(a, prepared, bank, gamma, config, lcc, references, *, include_csub):
    integer_graph, module, weighted_graph, _ = references
    started = time.perf_counter()
    certificates, primary_records = [], []
    for block in bank.blocks:
        certificate, record = _core_record(prepared, block, gamma, config["checker"])
        primary_records.append(record)
        if certificate is not None and certificate.certified:
            certificates.append(certificate)
    checker_seconds = time.perf_counter() - started
    started = time.perf_counter()
    quotient = contract_certified_blocks(prepared, certificates)
    quotient_seconds = time.perf_counter() - started
    reduction = summarize_quotient(a, quotient, largest_component=lcc)
    before = modularity_exact(prepared, bank.discovery_labels, gamma)
    q_labels = discovery_quotient_labels(bank.discovery_labels, quotient)
    after = modularity_exact(quotient.adjacency, q_labels, gamma)
    if before != after:
        raise ArithmeticError("Discovery incumbent changed in the certified quotient")
    comparisons = []
    for block in bank.blocks:
        record = {"block": list(block), "block_source": "fixed independent bank",
                  "methods": evaluate_block_references(prepared, integer_graph, module, weighted_graph,
                                                        block, gamma, config)}
        if include_csub and 2 <= len(block) <= config["supplied_block_config"]["exact_max_size"]:
            record["c_subinstance"] = evaluate_c_subinstance(prepared, block, gamma, config)
        comparisons.append(record)
    return quotient, {"status": "completed", "checker_seconds": checker_seconds,
                      "quotient_seconds": quotient_seconds, "reduction": reduction,
                      "certification_status_counts": dict(Counter(x["verification_status"] for x in primary_records)),
                      "candidate_certificates": primary_records,
                      "modularity_discovery_exact": str(before),
                      "modularity_discovery_quotient_exact": str(after),
                      "comparison_panels_excluded_from_production_checker_time": True}, comparisons


def evaluate_native(a, discovery_labels, gamma, config, *, requested, case_name):
    settings = config["native_kapoce"]
    if not requested:
        return _unavailable("KaPoCE weighted preprocessing rules", "not_predeclared_for_case", full_solver=False)
    if settings["routine"] != "weighted_recursive" or settings["full_solver"]:
        raise ValueError("This runner implements only the named weighted preprocessing mode, never full KaPoCE")
    if a.shape[0] > settings["max_vertices"]:
        return _unavailable("KaPoCE weighted preprocessing rules", "native_input_vertex_limit", full_solver=False)
    if discovery_labels is None:
        return _unavailable("KaPoCE weighted preprocessing rules", "actual_discovery_incumbent_missing", full_solver=False)
    if np.any(a.data != np.floor(a.data)):
        return _unavailable("KaPoCE weighted preprocessing rules", "noninteger_adjacency_domain", full_solver=False)
    started = time.perf_counter()
    dense = [[int(value) for value in row] for row in a.toarray()]
    dense_seconds = time.perf_counter() - started
    result = run_native_case(
        {"name": case_name, "adjacency": dense, "gamma": str(gamma),
         "partition": [int(x) for x in discovery_labels]},
        routines=("weighted_recursive",), timeout_seconds=settings["timeout_seconds"],
    )
    result["runner_dense_input_conversion_seconds"] = dense_seconds
    result["runner_wall_seconds"] = time.perf_counter() - started
    build_path = Path("research/baselines/build-provenance.json")
    binary_path = Path("research/baselines/build/kapoce_selected")
    result["native_build_provenance"] = json.loads(build_path.read_text()) if build_path.exists() else None
    result["native_binary_sha256"] = sha256(binary_path) if binary_path.exists() else None
    result["incumbent_role"] = "fixed actual bank discovery partition; feasible for each gamma, not oracle substituted"
    result["comparison_role"] = "independent weighted preprocessing; cannot-link residual never composed with the new method"
    return result


def preserve_native_failure(run_dir, prefix, gamma_index, record, *, method):
    """Make unexpected nested failures visible to the outer halt policy."""
    records = [record, *record.get("records", [])]
    if not any(item.get("status") in {"failed", "validation_failure", "unavailable_build"}
               for item in records):
        return
    path = Path(run_dir) / f"{prefix}-gamma{gamma_index}-{method}-failed.json"
    write_once(path, jsonable({"status": "failed", "method": method,
                              "native_record": record}))
    raise RuntimeError(f"Unexpected native {method} failure; preserved at {path}")


def evaluate_full_native(a, quotient, discovery_labels, gamma, config, *, requested,
                         case_name, order):
    """Matched complete solver calls with the same retained feasible incumbent."""
    settings = config["native_full_solver"]
    if not requested:
        return _unavailable("full KaPoCE", "not_predeclared_for_case")
    if quotient is None or discovery_labels is None:
        raise ValueError("The matched full-solver study requires the actual bank quotient/incumbent")
    started = time.perf_counter()
    expected_q = modularity_exact(a, discovery_labels, gamma)
    original_incumbent_evaluation_seconds = time.perf_counter() - started
    started = time.perf_counter()
    quotient_labels = discovery_quotient_labels(discovery_labels, quotient)
    if modularity_exact(quotient.adjacency, quotient_labels, gamma) != expected_q:
        raise ArithmeticError("Full-solver incumbent differs between original and quotient")
    quotient_incumbent_alignment_seconds = time.perf_counter() - started
    records = {}
    for arm in order:
        adjacency = a if arm == "unreduced" else quotient.adjacency
        incumbent = discovery_labels if arm == "unreduced" else quotient_labels
        started = time.perf_counter()
        if adjacency.shape[0] == 1:
            q = modularity_exact(adjacency, np.array([0]), gamma)
            record = {"status": "optimal_trivial", "optimality_proved": True,
                      "full_solver_entry_called": False, "full_kapoce_solver": False,
                      "solution": {"labels": [0], "Q": str(q)},
                      "reason": "one feasible quotient partition; native minimum n=2"}
        elif adjacency.shape[0] > settings["max_vertices"]:
            record = {"status": "skipped_input_domain", "reason": "native vertex limit",
                      "full_solver_entry_called": False, "full_kapoce_solver": False}
        elif np.any(adjacency.data != np.floor(adjacency.data)):
            record = {"status": "skipped_input_domain", "reason": "noninteger adjacency",
                      "full_solver_entry_called": False, "full_kapoce_solver": False}
        else:
            dense = [[int(value) for value in row] for row in adjacency.toarray()]
            record = run_full_case(
                {"name": f"{case_name}-{arm}", "adjacency": dense, "gamma": str(gamma),
                 "partition": [int(x) for x in incumbent]},
                timeout_seconds=settings["timeout_seconds"],
            )
        record["incumbent_Q_original_exact"] = str(expected_q)
        record["runner_timing_scope"] = "input conversion, integer scaling, native process and independent validation"
        if record["status"] in {"optimal", "optimal_trivial"}:
            labels = np.array(record["solution"]["labels"], dtype=int)
            q = modularity_exact(adjacency, labels, gamma)
            if q != Fraction(record["solution"]["Q"]):
                record.update(status="validation_failure", reason="Full-solver objective failed independent core check")
            lifted = labels if arm == "unreduced" else quotient.lift_labels(labels)
            if modularity_exact(a, lifted, gamma) != q:
                record.update(status="validation_failure", reason="Full-solver solution failed exact lifting check")
            record["lifted_labels"] = lifted.tolist()
            record["lifted_Q_original_exact"] = str(q)
        record["runner_wall_seconds"] = time.perf_counter() - started
        records[arm] = record
    optimal = [record for record in records.values() if record.get("optimality_proved")]
    output = {"execution_order": order, "paired_arms": records,
            "records": list(records.values()),
            "same_feasible_incumbent_Q_exact": str(expected_q),
            "original_incumbent_evaluation_seconds": original_incumbent_evaluation_seconds,
            "quotient_incumbent_alignment_seconds": quotient_incumbent_alignment_seconds,
            "comparison_role": "complete unchanged exact solver; timeout bounds retain supplied incumbent and completed initial LB only"}
    if len(optimal) == 2 and optimal[0]["lifted_Q_original_exact"] != optimal[1]["lifted_Q_original_exact"]:
        output.update(status="validation_failure", reason="Certified quotient and original exact optimum disagree")
    return output


def evaluate_numerical_milp(a, quotient, gamma, config, *, order):
    """Keep numerical status/bounds, but re-evaluate every feasible Q exactly."""
    settings = config["numerical_milp"]
    records = {}
    for arm in order:
        adjacency = a if arm == "unreduced" else quotient.adjacency
        if adjacency.shape[0] > settings["max_vertices"]:
            records[arm] = _unavailable("numerical modularity MILP", "numerical_vertex_limit")
            continue
        started = time.perf_counter()
        result = solve_modularity(adjacency, gamma=gamma, time_limit=settings["time_limit_seconds"])
        record = jsonable(result)
        record.update({"available": True, "certified": False,
                       "global_optimum_certified": False,
                       "upper_bound_arithmetic": "floating numerical MILP diagnostic; not an exact bound",
                       "runner_wall_seconds": time.perf_counter() - started,
                       "feasible_Q_exact": None, "lifted_original_Q_exact": None})
        if result.labels is not None:
            exact_q = modularity_exact(adjacency, result.labels, gamma)
            record["feasible_Q_exact"] = str(exact_q)
            if arm == "reduced":
                lifted = quotient.lift_labels(result.labels)
                original_q = modularity_exact(a, lifted, gamma)
                if original_q != exact_q:
                    raise ArithmeticError("MILP feasible partition does not lift with equal exact modularity")
                record["lifted_original_Q_exact"] = str(original_q)
                record["lifted_labels"] = lifted.tolist()
            else:
                record["lifted_original_Q_exact"] = str(exact_q)
            record["numerical_feasible_Q_minus_exact_float"] = None if result.modularity is None else result.modularity - float(exact_q)
        records[arm] = record
    return {"execution_order": order, "paired_arms": records,
            "arithmetic_policy": "exact feasible/lifted Q; numerical optimization and bounds never certify global optimum"}


def _validate_case(stratum, identifier, config):
    if stratum == "controlled":
        declared = {item["case_id"]: item for item in controlled_grid()}
        configured_ids = [item["case_id"] for item in config["controlled_cases"]]
        if len(set(configured_ids)) != len(configured_ids) or set(configured_ids) != set(declared):
            raise ValueError("Frozen controlled configuration must retain the entire unique predeclared grid")
        configured = [item for item in config["controlled_cases"] if item["case_id"] == identifier]
        if len(configured) != 1 or identifier not in declared:
            raise ValueError("Controlled case outside the unique predeclared grid")
        spec = configured[0]
        if spec["candidate_bank_seed"] != 0:
            raise ValueError("Controlled comparisons require the predeclared independent bank seed0")
        for key in ("family", "parameters", "gamma"):
            if spec[key] != declared[identifier][key]:
                raise ValueError(f"Controlled spec differs from grid on {key}")
        return spec
    if stratum != "development" or identifier not in config["development_datasets"]:
        raise ValueError("Development dataset outside configured stratum")
    if config["supplied_block_config"].get("development_bank_seed", 0) != 0:
        raise ValueError("Development comparisons require the predeclared independent bank seed0")
    return {"case_id": identifier, "role": "development", "candidate_bank_seed": 0,
            "gamma": config["gamma"], "native_preprocessing": identifier in config["native_kapoce"]["datasets"]}


def _provenance(config_path, freeze_path, freeze, stratum, identifier, spec):
    return {"stratum": stratum, "case_id": identifier, "specification": spec,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_sha256": sha256(config_path), "freeze_sha256": sha256(freeze_path),
            "runtime_source_sha256": freeze["runtime_source_sha256"],
            "versions": {"python": platform.python_version(), "numpy": np.__version__,
                         "scipy": scipy.__version__, "networkx": nx.__version__},
            "platform": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
            "numerical_nonfinite_encoding": "string markers inf/-inf/nan; never certificates"}


def run_case(stratum, identifier, config, run_dir, config_path, freeze_path):
    """One full case, no overwrite or pre-freeze execution route."""
    freeze = validate_freeze(config_path, freeze_path)
    spec = _validate_case(stratum, identifier, config)
    if any(os.getenv(key) != value for key, value in config["threads"].items()):
        raise ValueError("Set frozen thread environment before importing/executing the runner")
    run_dir = Path(run_dir)
    prefix = identifier if stratum == "controlled" else f"development-{identifier}"
    provenance = _provenance(config_path, freeze_path, freeze, stratum, identifier, spec)
    provenance["thread_environment"] = {key: os.getenv(key) for key in config["threads"]}
    write_once(run_dir / f"{prefix}-started.json", provenance)
    case_started = time.perf_counter()
    try:
        started = time.perf_counter()
        if stratum == "controlled":
            graph, metadata = load_family(spec["family"], **spec["parameters"],
                                          include_oracle_blocks=spec["supplied_block_comparison"])
        else:
            graph, metadata = load_development(identifier)
        graph_loading_seconds = time.perf_counter() - started
        started = time.perf_counter()
        a = graph_adjacency(graph)
        prepared = prepare_graph(a)
        prepared.exact_degrees()
        preparation_seconds = time.perf_counter() - started
        references = prepare_references(a)
        lcc = max(nx.connected_components(graph), key=lambda nodes: (len(nodes), -min(nodes)), default=set())
        # Only an explicit frozen computation-only flag can skip discovery.
        skip_bank = not spec.get("candidate_bank_evaluation", True)
        if skip_bank and (stratum != "controlled" or spec.get("family") != "profile_scaling"
                          or spec["native_preprocessing"]):
            raise ValueError("Only a predeclared profile-scaling computation-only case without native preprocessing can skip the independent bank")
        bank = None if skip_bank else candidate_bank(
            graph, seed=spec["candidate_bank_seed"],
            resolution=float(Fraction(config["proposal"]["resolution"])),
            minimum_size=config["proposal"]["minimum_size"],
        )
        bank_hash = None if bank is None else candidate_identity(bank)
        supplied_blocks = metadata.get("oracle_blocks", []) if stratum == "controlled" and spec["supplied_block_comparison"] else []
        write_once(run_dir / f"{prefix}-input.json.gz", jsonable({
            "provenance": provenance, "dataset": metadata, "graph_content_sha256": _graph_hash(graph),
            "graph_fingerprint": prepared.fingerprint, "graph_loading_seconds": graph_loading_seconds,
            "graph_preparation_seconds": preparation_seconds, "baseline_preparation": references[3],
            "bank_status": "skipped_predeclared_profile_computation_only" if bank is None else "completed",
            "bank_sha256": bank_hash, "candidate_bank": None if bank is None else {
                "blocks": bank.blocks, "discovery_labels": bank.discovery_labels,
                "seed": bank.seed, "proposal_seconds": bank.proposal_seconds,
                "refinement_seconds": bank.refinement_seconds, "spectral_splits": bank.spectral_splits,
                "component_splits": bank.component_splits, "fallback_splits": bank.fallback_splits},
            "supplied_blocks": supplied_blocks,
            "supplied_block_role": "labeled mathematical-criterion comparison only; never candidate generator input",
        }))
        for gamma_index, gamma_text in enumerate(spec["gamma"]):
            gamma_started = time.perf_counter()
            gamma = Fraction(gamma_text)
            global_records = evaluate_global_baselines(a, references[0], gamma, config, lcc)
            if bank is None:
                quotient = None
                primary = _unavailable("production independent-bank method", "predeclared_computation_only_bank_skip")
                bank_comparisons = []
            else:
                quotient, primary, bank_comparisons = evaluate_bank(
                    a, prepared, bank, gamma, config, lcc, references, include_csub=stratum == "development",
                )
                global_records.update(evaluate_recursive_baseline(a, bank, gamma, config, lcc))
                new_groups = primary["reduction"]["merge_groups"]
                for comparison in global_records.values():
                    old_groups = comparison["reduction"]["merge_groups"]
                    joint = identifications(a.shape[0], new_groups + old_groups)
                    comparison["new_identifications_beyond_baseline"] = joint - identifications(a.shape[0], old_groups)
                    comparison["baseline_identifications_beyond_new"] = joint - identifications(a.shape[0], new_groups)
            supplied_records = []
            for block in supplied_blocks:
                supplied_records.append({"block": list(block), "block_source": "controlled generator optional reference",
                    "interpretation": metadata.get("oracle_block_interpretation", "reference block; no inferred community truth"),
                    "methods": evaluate_block_references(prepared, references[0], references[1], references[2], block, gamma, config,
                                                         include_weak_bocker=True),
                    "c_subinstance": evaluate_c_subinstance(prepared, block, gamma, config)})
            native = evaluate_native(a, None if bank is None else bank.discovery_labels, gamma, config,
                                     requested=spec["native_preprocessing"], case_name=f"{prefix}-gamma{gamma_index}")
            preserve_native_failure(run_dir, prefix, gamma_index, native, method="preprocessing")
            order = ["unreduced", "reduced"]
            case_index = ([item["case_id"] for item in config["controlled_cases"]].index(identifier)
                          if stratum == "controlled" else config["development_datasets"].index(identifier))
            if (case_index + gamma_index) % 2:
                order.reverse()
            full_native = evaluate_full_native(
                a, quotient, None if bank is None else bank.discovery_labels, gamma, config,
                requested=spec["native_preprocessing"], case_name=f"{prefix}-gamma{gamma_index}", order=order)
            preserve_native_failure(run_dir, prefix, gamma_index, full_native, method="full-solver")
            if "paired_arms" in full_native:
                full_native["shared_graph_preparation_seconds"] = preparation_seconds
                full_native["shared_discovery_seconds"] = bank.proposal_seconds
                full_native["reduced_additional_preprocessing_seconds"] = (
                    bank.refinement_seconds + primary["checker_seconds"] + primary["quotient_seconds"]
                    + full_native["quotient_incumbent_alignment_seconds"])
                full_native["matched_pipeline_seconds"] = {
                    arm: preparation_seconds + bank.proposal_seconds + record["runner_wall_seconds"]
                         + full_native["original_incumbent_evaluation_seconds"]
                         + (full_native["reduced_additional_preprocessing_seconds"] if arm == "reduced" else 0)
                    for arm, record in full_native["paired_arms"].items()}
                full_native["pipeline_scope"] = "prepared in-memory graph, discovery incumbent, optional refinement/certification/quotient, input conversion, complete solver, independent validation; shared raw loading and report panels excluded"
            numerical = None
            if stratum == "development" and identifier in config["numerical_milp"]["datasets"]:
                order = ["unreduced", "reduced"]
                if (config["development_datasets"].index(identifier) + gamma_index) % 2:
                    order.reverse()
                numerical = evaluate_numerical_milp(a, quotient, gamma, config, order=order)
            write_once(run_dir / f"{prefix}-gamma{gamma_index}.json.gz", jsonable({
                "status": "completed", "provenance": provenance, "gamma_exact": str(gamma),
                "dataset": metadata, "graph_fingerprint": prepared.fingerprint, "bank_sha256": bank_hash,
                "global_baselines": global_records, "production_independent_bank": primary,
                "same_bank_criterion_comparison": bank_comparisons,
                "controlled_supplied_block_comparison": supplied_records,
                "native_weighted_preprocessing": native, "native_full_solver": full_native,
                "numerical_modularity_milp": numerical,
                "gamma_compute_seconds": time.perf_counter() - gamma_started,
                "performance_scope": "controlled criterion/preprocessing study; no downstream speedup claim" if stratum == "controlled" else "development diagnostics; never holdout evidence",
                "peak_case_process_RSS_bytes": peak_rss_bytes(),
                "memory_semantics": "cumulative process peak including graph, all comparisons and retained objects; includes earlier cases under --all; isolate one case per process for case memory",
            }))
            print(json.dumps({"phase": "case_gamma_complete", "stratum": stratum,
                              "case": identifier, "gamma": str(gamma)}), flush=True)
        write_once(run_dir / f"{prefix}-completed.json", {
            "status": "completed", "case_seconds": time.perf_counter() - case_started,
            "peak_case_process_RSS_bytes": peak_rss_bytes(), "provenance": provenance})
    except Exception as error:
        write_once(run_dir / f"{prefix}-failed.json", {"status": "failed", "error_type": type(error).__name__,
            "error": str(error), "case_seconds": time.perf_counter() - case_started,
            "peak_case_process_RSS_bytes": peak_rss_bytes(), "provenance": provenance})
        raise


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="experiments/config.json")
    parser.add_argument("--freeze", default="experiments/freeze.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stratum", required=True, choices=("controlled", "development"))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case")
    selection.add_argument("--all", action="store_true")
    return parser


def main():
    args = make_parser().parse_args()
    config = json.loads(Path(args.config).read_text())
    # Validate before --all iteration too; no draft generation or timing starts.
    validate_freeze(args.config, args.freeze)
    names = ([item["case_id"] for item in config["controlled_cases"]] if args.stratum == "controlled"
             else config["development_datasets"]) if args.all else [args.case]
    for name in names:
        run_case(args.stratum, name, config, args.run_dir, args.config, args.freeze)


if __name__ == "__main__":
    main()
