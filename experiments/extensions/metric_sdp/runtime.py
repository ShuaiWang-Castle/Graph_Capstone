"""Complete-cost single-arm application, with exact original-objective lift."""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy import sparse

from degree_contraction import modularity_exact, prepare_graph
from experiments.candidates import candidate_bank
from experiments.pipeline import graph_adjacency
from .freeze import write_once
from .numerical import BudgetExpired, solve_component
from .safe_composition import run_composition


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


class Ledger:
    def __init__(self):
        self.seconds = defaultdict(float)
        self.depth = 0

    @contextmanager
    def measure(self, name):
        if self.depth:
            raise ValueError("stage accounting must be disjoint")
        self.depth = 1
        started = time.perf_counter()
        try:
            yield
        finally:
            self.seconds[name] += time.perf_counter() - started
            self.depth = 0


def coefficient_matrix(adjacency, gamma):
    """Full trace coefficients B/S from exact represented CSR and degrees."""
    graph = prepare_graph(sparse.csr_matrix(adjacency))
    degrees, total = graph.exact_degrees()
    if total <= 0 or not isinstance(gamma, Fraction) or gamma < 0:
        raise ValueError("positive original volume and exact resolution required")
    rows = []
    for i in range(graph.adjacency.shape[0]):
        row = graph.adjacency.getrow(i)
        rows.append({int(j): Fraction.from_float(float(x))
                     for j, x in zip(row.indices, row.data)})
    coefficients = tuple(tuple(
        rows[i].get(j, Fraction()) / total -
        gamma * degrees[i] * degrees[j] / (total * total)
        for j in range(len(rows))) for i in range(len(rows)))
    return graph, coefficients, degrees, total


def signed_components(coefficients):
    """All nonpositive cross affinities receive a common block-diagonal map."""
    n = len(coefficients)
    parent = list(range(n))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if coefficients[i][j] > 0:
                parent[find(j)] = find(i)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    answer = sorted(groups.values(), key=lambda g: g[0])
    component_of = {}
    for c, group in enumerate(answer):
        for i in group:
            component_of[i] = c
    if any(coefficients[i][j] > 0 for i in range(n) for j in range(i + 1, n)
           if component_of[i] != component_of[j]):
        raise ArithmeticError("positive signed component decomposition failed")
    return answer


def validate_quotient(original_coefficients, quotient_coefficients,
                      membership, original_degrees, quotient_degrees,
                      original_total, quotient_total):
    """Independent exact aggregation covers loops, all costs and full degrees."""
    n, q = len(original_coefficients), len(quotient_coefficients)
    membership = tuple(int(i) for i in membership)
    if (len(membership) != n or set(membership) != set(range(q)) or
            quotient_total != original_total):
        raise ArithmeticError("invalid quotient membership or changed original S")
    sums = [[Fraction() for _ in range(q)] for _ in range(q)]
    dd = [Fraction() for _ in range(q)]
    for i, a in enumerate(membership):
        dd[a] += original_degrees[i]
        for j, b in enumerate(membership):
            sums[a][b] += original_coefficients[i][j]
    if tuple(dd) != tuple(quotient_degrees):
        raise ArithmeticError("quotient degrees changed original full degrees")
    if any(sums[i][j] != quotient_coefficients[i][j]
           for i in range(q) for j in range(q)):
        raise ArithmeticError("quotient full trace coefficients changed objective")
    return {"exact_full_trace_aggregation": True, "exact_degrees": True,
            "original_total_preserved": True,
            "membership": list(membership), "original_n": n, "quotient_n": q}


def validate_lift(original_coefficients, membership, components, results, lower):
    """Check original trace and structural PSD/metric lift, without extra SDP."""
    where = {}
    for ci, group in enumerate(components):
        for local, node in enumerate(group):
            where[node] = (ci, local)
    lifted_trace = Fraction()
    for i, a in enumerate(membership):
        ci, ai = where[int(a)]
        for j, b in enumerate(membership):
            cj, bj = where[int(b)]
            if ci == cj:
                result = results[ci]
                value = (Fraction(1) if result["analytic"] else
                         Fraction(result["interval"].primal.matrix.numerators[ai][bj],
                                  result["interval"].primal.matrix.denominator))
                lifted_trace += original_coefficients[i][j] * value
    if lifted_trace != lower:
        raise ArithmeticError("repaired relaxed primal lift changed original Q")
    return {"original_lifted_trace_exact": str(lifted_trace),
            "psd_lift": "membership congruence of verified block-diagonal Gram+DD",
            "metric_lift": "index substitution; repeated indices checked by boxes",
            "dual_transfer": "each preceding operation relaxation-safe plus exact quotient identity",
            "all_cross_coefficients_nonpositive": True}


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
    membership = np.arange(len(graph), dtype=int)
    composition = None
    if arm != "U":
        with ledger.measure("safe_composition"):
            composition = run_composition(
                adjacency, bank.blocks, gamma, mode=arm,
                max_graph_size=config["checker"]["max_vertices"],
                max_block_size=config["checker"]["max_block_size"])
            adjacency, membership = composition.adjacency, composition.membership
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
