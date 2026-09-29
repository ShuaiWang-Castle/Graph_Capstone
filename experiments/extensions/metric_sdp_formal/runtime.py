"""Formal complete-cost orchestration with durable preprocessing prefixes.

The objective, component and lift helpers are the unchanged pilot helpers.
Only execution/checkpoint orchestration differs from the sealed pilot version.
"""
from __future__ import annotations

from fractions import Fraction
import json
import os
from pathlib import Path
import time

import numpy as np

from degree_contraction import modularity_exact
from experiments.candidates import candidate_bank
from experiments.pipeline import graph_adjacency
from ..metric_sdp.runtime import (
    Ledger, coefficient_matrix, content_hash, signed_components,
    validate_lift, validate_quotient,
)
from ..metric_sdp.numerical import BudgetExpired, solve_component
from ..metric_sdp.freeze import sha256, write_once
from .composition import run_composition


def write_original_csr_once(path, adjacency):
    """Atomic exact stored CSR arrays; every I/O operation is charged by caller."""
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("xb") as handle:
        np.savez_compressed(handle, data=adjacency.data, indices=adjacency.indices,
                            indptr=adjacency.indptr,
                            shape=np.asarray(adjacency.shape, dtype=np.int64))
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path)
    temporary.unlink()


def run_arm(graph, case, arm, backend, config, output, *,
            wall_seconds, started_at):
    """Input decoding/imports precede started_at; every required stage follows."""
    output = Path(output)
    ledger = Ledger()
    gamma = Fraction(case["gamma"])
    deadline = started_at + wall_seconds
    components_results = []
    record = {"case_id": case["case_id"], "arm": arm, "backend": backend,
              "scientific_measurement": True, "status": "in_progress",
              "gamma_exact": str(gamma), "components": []}
    with ledger.measure("original_graph_preparation"):
        adjacency = graph_adjacency(graph)
        original, c0, d0, total = coefficient_matrix(adjacency, gamma)
        if original.adjacency.shape[0] > config["checker"]["max_vertices"]:
            raise ValueError("whole input exceeds frozen n<=300 domain")
    with ledger.measure("common_discovery_and_bank"):
        bank = candidate_bank(graph, **{
            k: config["discovery"][k] for k in ("seed", "resolution", "minimum_size")})
        bank_payload = {"blocks": [list(b) for b in bank.blocks],
                        "discovery_labels": [int(x) for x in bank.discovery_labels]}
        bank_identity = content_hash(bank_payload)
    with ledger.measure("original_discovery_incumbent"):
        incumbent = modularity_exact(original, bank.discovery_labels, gamma)
    with ledger.measure("original_input_checkpoint"):
        original_csr_path = output / "original-adjacency.npz"
        write_original_csr_once(original_csr_path, original.adjacency)
        original_csr_digest = sha256(original_csr_path)
        write_once(output / "original-preparation.json", {
            "case_id": case["case_id"], "arm": arm, "backend": backend,
            "original_n": len(graph), "gamma_exact": str(gamma),
            "S_exact": str(total), "degrees_exact": [str(x) for x in d0],
            "original_fingerprint": original.fingerprint,
            "original_csr_sha256": original_csr_digest,
            "bank": bank_payload, "bank_sha256": bank_identity,
            "incumbent_Q_exact": str(incumbent),
            "stage": "before_any_composition",
        })
    operation_files = []
    def composition_progress(event):
        index = event["operation"]["index"]
        if index != len(operation_files):
            raise ArithmeticError("accepted operation checkpoint order changed")
        filename = f"composition-operation-{index:04d}.json"
        write_once(output / filename, event)
        operation_files.append(filename)
    membership = np.arange(len(graph), dtype=int)
    composition = None
    if arm != "U":
        with ledger.measure("safe_composition"):
            composition = run_composition(
                adjacency, bank.blocks, gamma, mode=arm,
                max_graph_size=config["checker"]["max_vertices"],
                max_block_size=config["checker"]["max_block_size"],
                progress=composition_progress)
            adjacency, membership = composition.adjacency, composition.membership
    if composition is not None and len(operation_files) != len(composition.operations):
        raise ArithmeticError("accepted operation trace missing durable checkpoint")
    record.update(schema="metric-sdp-formal-arm-v1",
                  original_csr_sha256=original_csr_digest,
                  composition_checkpoint_files=operation_files)
    with ledger.measure("quotient_objective_and_validation"):
        quotient, cq, dq, tq = coefficient_matrix(adjacency, gamma)
        quotient_validation = validate_quotient(c0, cq, membership, d0, dq, total, tq)
    with ledger.measure("signed_component_presolve"):
        components = signed_components(cq)
        multiplicities = np.bincount(membership, minlength=len(cq))
        budgets = [Fraction(sum(int(multiplicities[u]) for u in group), len(graph)) *
                   Fraction(config["solver"]["width_target"]) for group in components]
        if sum(budgets, Fraction()) != Fraction(config["solver"]["width_target"]):
            raise ArithmeticError("component quality allocations changed global target")
    record.update(original_n=len(graph), quotient_n=len(cq), S_exact=str(total),
                  original_fingerprint=original.fingerprint, bank_sha256=bank_identity,
                  bank=bank_payload, incumbent_Q_exact=str(incumbent),
                  quotient_validation=quotient_validation,
                  membership=[int(x) for x in membership], component_nodes=components,
                  component_width_targets=[str(x) for x in budgets],
                  composition=None if composition is None else
                  {"operations": composition.operations, "metadata": composition.metadata})
    with ledger.measure("checkpoint"):
        write_once(output / "preprocessing.json", record)
    for component_index, (nodes, target) in enumerate(zip(components, budgets)):
        if time.perf_counter() >= deadline:
            raise BudgetExpired("preprocessing exceeded complete arm budget")
        coefficients = tuple(tuple(cq[i][j] for j in nodes) for i in nodes)
        if len(nodes) == 1:
            with ledger.measure("analytic_singleton_validation"):
                value = coefficients[0][0]
                result = {"status": "verified_target", "analytic": True,
                          "lower": value, "upper": value, "rounds": [], "interval": None}
        else:
            def progress(round_index, proposal, metrics):
                prefix = f"component-{component_index:03d}-round-{round_index:03d}"
                if proposal is not None:
                    with (output / (prefix + "-raw.npz")).open("xb") as handle:
                        np.savez_compressed(
                            handle, H=proposal["matrix"], y=proposal["diagonal_dual"],
                            lambdas=proposal["inequality_dual"],
                            psd_dual_slack=proposal["psd_dual_slack"],
                            triangles=np.array(proposal["active_triangles"],
                                               dtype=int).reshape((-1, 3)))
                if metrics is not None:
                    with (output / (prefix + "-metrics.json")).open("x") as handle:
                        json.dump(metrics, handle, indent=2)
                        handle.write("\n")
            result = solve_component(
                coefficients, backend=backend, width_target=target, deadline=deadline,
                stage=ledger.measure, policy=config["solver"], progress=progress)
            result["analytic"] = False
            if result["interval"] is not None:
                result["lower"], result["upper"] = (
                    result["interval"].lower, result["interval"].upper)
        components_results.append(result)
        record["components"].append({
            "index": component_index, "nodes": nodes, "status": result["status"],
            "analytic": result["analytic"], "width_target_exact": str(target),
            "rounds": result["rounds"],
            "terminal_solver_info": result.get("solver_info"),
            "terminal_unpack_error": result.get("unpack_error"),
            "lower_exact": str(result["lower"]) if "lower" in result else None,
            "upper_exact": str(result["upper"]) if "upper" in result else None})
    all_bounded = all("lower" in result for result in components_results)
    if all_bounded:
        with ledger.measure("lift_exact_validation"):
            lower = sum((r["lower"] for r in components_results), Fraction())
            upper = sum((r["upper"] for r in components_results), Fraction())
            lift = validate_lift(c0, membership, components, components_results, lower)
            if upper < incumbent:
                raise ArithmeticError("relaxed upper bound below original feasible partition")
        record.update(lower_exact=str(lower), upper_exact=str(upper),
                      width_exact=str(upper - lower),
                      discrete_incumbent_gap_exact=str(upper - incumbent),
                      lift_validation=lift)
        target = Fraction(config["solver"]["width_target"])
        record["status"] = ("verified_target" if upper - lower <= target else
                            "verified_interval_too_wide")
    else:
        record["status"] = "incomplete_component_bounds"
    record["stage_seconds"] = dict(ledger.seconds)
    record["full_compute_seconds"] = time.perf_counter() - started_at
    if record["full_compute_seconds"] > wall_seconds:
        record["status"] = "full_wall_limit"
    record["accounted_stage_seconds"] = sum(ledger.seconds.values())
    record["unassigned_compute_seconds"] = (
        record["full_compute_seconds"] - record["accounted_stage_seconds"])
    return record, components_results
