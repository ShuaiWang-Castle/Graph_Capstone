"""Active metric cuts; floating proposals followed by exact interval repair.

This module performs no scientific call at import time. Its native SCS
interface is pinned to the inspected 3.3 API. A new cone receives only a
compatible primal warm start; previous dual/slack dimensions are not reused.
"""
from __future__ import annotations

from fractions import Fraction
import heapq
import math
import time

import cvxpy as cp
import numpy as np
import scs
from cvxpy.reductions.solvers.conic_solvers.scs_conif import dims_to_solver_dict

from .rational import Inequality, propose_gram_factor, repair_interval


class BudgetExpired(RuntimeError):
    pass


def native_diagnostics(value):
    """Keep nonfinite native diagnostics explicit in ordinary portable JSON."""
    if isinstance(value, dict):
        return {str(k): native_diagnostics(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [native_diagnostics(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return {"diagnostic_type": "nonfinite_float", "value": str(value)}
    return value


def separate_triangles(matrix, active=(), *, threshold=1e-7, limit=5000):
    """Scan every distinct triangle; retain only a bounded deterministic heap.

    A key (i,j,k) represents Yij+Yjk-Yik<=1, with i<k. The middle
    index j may be smaller/larger. Repeated-index triangles follow from boxes.
    """
    matrix = np.asarray(matrix, dtype=float)
    n = len(matrix)
    if matrix.shape != (n, n) or not np.isfinite(matrix).all():
        raise ValueError("finite square numerical matrix required")
    active = set(active)
    heap = []
    maximum = 0.0
    violations = 0
    for a in range(n - 2):
        r, c = np.triu_indices(n - a - 1, 1)
        b, d = r + a + 1, c + a + 1
        expressions = (
            (matrix[a, b] + matrix[b, d] - matrix[a, d] - 1, 0),
            (matrix[a, b] + matrix[a, d] - matrix[b, d] - 1, 1),
            (matrix[a, d] + matrix[b, d] - matrix[a, b] - 1, 2),
        )
        for values, orientation in expressions:
            maximum = max(maximum, float(np.max(values, initial=0)))
            for pos in np.flatnonzero(values > threshold):
                bb, dd = int(b[pos]), int(d[pos])
                key = ((a, bb, dd), (bb, a, dd), (a, dd, bb))[orientation]
                if key in active:
                    continue
                violations += 1
                entry = (float(values[pos]), -key[0], -key[1], -key[2])
                if len(heap) < limit:
                    heapq.heappush(heap, entry)
                elif entry > heap[0]:
                    heapq.heapreplace(heap, entry)
    picked = [(-x[1], -x[2], -x[3]) for x in
              sorted(heap, key=lambda x: (-x[0], -x[1], -x[2], -x[3]))]
    return {"maximum_raw_violation": maximum,
            "new_violations_above_threshold": violations, "add": picked}


def build_problem(exact_coefficients, variable, active):
    """Vectorize unique boxes and active cuts; retain full trace diagonals."""
    n = len(exact_coefficients)
    coefficients = np.array([[float(x) for x in row]
                             for row in exact_coefficients])
    ii, jj = np.triu_indices(n, 1)
    psd = variable >> 0
    diagonal = cp.diag(variable) == 1
    lower = -variable[ii, jj] <= 0
    upper = variable[ii, jj] <= 1
    constraints = [psd, diagonal, lower, upper]
    ordered = sorted(active)
    triangle = None
    if ordered:
        i, j, k = np.asarray(ordered, dtype=int).T
        triangle = variable[i, j] + variable[j, k] - variable[i, k] <= 1
        constraints.append(triangle)
    problem = cp.Problem(cp.Maximize(cp.sum(cp.multiply(coefficients, variable))),
                         constraints)
    inequalities = [Inequality("lower", int(i), int(j))
                    for i, j in zip(ii, jj)]
    inequalities += [Inequality("upper", int(i), int(j))
                     for i, j in zip(ii, jj)]
    inequalities += [Inequality("triangle", *key) for key in ordered]
    return problem, psd, diagonal, lower, upper, triangle, inequalities


def solve_component(exact_coefficients, *, backend, width_target,
                    deadline, stage, policy, progress=None):
    """Return all raw rounds and a rigorously repaired full-domain interval.

    deadline is the arm's absolute perf_counter deadline. stage(name) is a
    caller-owned disjoint accounting context manager. No output I/O occurs.
    A one-node component is handled by the caller's exact analytic path.
    """
    n = len(exact_coefficients)
    if n < 2 or backend not in {"direct", "indirect"}:
        raise ValueError("nontrivial component and fixed SCS backend required")
    if any(len(row) != n for row in exact_coefficients):
        raise ValueError("square exact coefficient matrix required")
    if not isinstance(width_target, Fraction) or width_target <= 0:
        raise ValueError("positive exact interval-width target required")
    variable = cp.Variable((n, n), symmetric=True)
    active, previous_x = set(), None
    tolerance_index = 0
    rounds, raw = [], []
    last_interval = None
    for round_index in range(policy["max_rounds"]):
        if time.perf_counter() >= deadline:
            raise BudgetExpired("component construction exceeded full arm budget")
        with stage("model_canonicalization"):
            built = build_problem(exact_coefficients, variable, active)
            problem, psd, diagonal, lower, upper, triangle, inequalities = built
            data, chain, inverse_data = problem.get_problem_data(cp.SCS)
            cone = dims_to_solver_dict(data["dims"])
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise BudgetExpired("canonicalization exceeded full arm budget")
        epsilon = policy["eps_sequence"][tolerance_index]
        settings = dict(eps_abs=epsilon, eps_rel=epsilon,
                        max_iters=policy["max_iters"],
                        normalize=True, verbose=False,
                        time_limit_secs=remaining,
                        linear_solver="qdldl" if backend == "direct"
                        else "cpu_indirect")
        native_data = {k: data[k] for k in ("A", "b", "c")}
        if "P" in data:
            native_data["P"] = data["P"]
        compatible = bool(previous_x is not None and
                      len(previous_x) == len(data["c"]) and
                      np.isfinite(previous_x).all())
        with stage("solver"):
            solver = scs.SCS(native_data, cone, **settings)
            solution = solver.solve(warm_start=compatible,
                                    x=previous_x if compatible else None)
            try:
                problem.unpack_results(solution, chain, inverse_data)
                unpack_error = None
            except cp.error.SolverError as error:
                unpack_error = str(error)
        info = native_diagnostics(solution["info"])
        have_values = (unpack_error is None and variable.value is not None and
                       diagonal.dual_value is not None and psd.dual_value is not None and
                       lower.dual_value is not None and upper.dual_value is not None and
                       (triangle is None or triangle.dual_value is not None))
        if not have_values:
            terminal = {"round": round_index, "status": "no_finite_solver_proposal",
                        "solver_info": info, "unpack_error": unpack_error}
            if progress is not None:
                with stage("checkpoint"):
                    progress(round_index, None, terminal)
            return {"status": "no_finite_solver_proposal", "rounds": rounds,
                    "raw": raw, "interval": last_interval,
                    "solver_info": info, "unpack_error": unpack_error}
        with stage("proposal_extraction"):
            matrix = np.asarray(variable.value, dtype=float).copy()
            yy = np.asarray(diagonal.dual_value, dtype=float).copy()
            parts = [np.asarray(lower.dual_value, dtype=float).ravel(),
                     np.asarray(upper.dual_value, dtype=float).ravel()]
            if triangle is not None:
                parts.append(np.asarray(triangle.dual_value, dtype=float).ravel())
            lambdas = np.concatenate(parts)
            previous_x = np.asarray(solution["x"], dtype=float).copy()
            dual_slack = np.asarray(psd.dual_value, dtype=float).copy()
        proposal = {"matrix": matrix, "diagonal_dual": yy,
                    "inequality_dual": lambdas, "psd_dual_slack": dual_slack,
                    "active_triangles": sorted(active)}
        if not all(np.isfinite(x).all() for x in (matrix, yy, lambdas, dual_slack)):
            terminal = {"round": round_index, "status": "nonfinite_solver_proposal",
                        "solver_info": info, "nonfinite_proposal": True}
            if progress is not None:
                with stage("checkpoint"):
                    progress(round_index, proposal, terminal)
            return {"status": "nonfinite_solver_proposal", "rounds": rounds,
                    "raw": raw + [proposal], "interval": last_interval, "solver_info": info}
        if progress is not None:
            with stage("checkpoint"):
                progress(round_index, proposal, None)
        with stage("triangle_separation"):
            separation = separate_triangles(
                matrix, active, threshold=policy["addition_threshold"],
                limit=policy["cuts_per_round"])
        with stage("rational_repair_and_exact_validation"):
            # repair_interval performs the complete exact verifier internally.
            # Do not add a second Gram/triangle replay to every measured round.
            interval = repair_interval(
                exact_coefficients, matrix, yy, inequalities, lambdas,
                denominator=policy["rational_denominator"],
                primal_factor=propose_gram_factor(matrix),
                dual_factor=propose_gram_factor(dual_slack))
        last_interval = interval
        rounds.append({"round": round_index, "active_triangles": len(active),
                       "epsilon": epsilon, "compatible_primal_warm_start": compatible,
                       "cvxpy_status": problem.status, "solver_info": info,
                       "separation": {k: v for k, v in separation.items() if k != "add"},
                       "lower_exact": str(interval.lower),
                       "upper_exact": str(interval.upper),
                       "width_exact": str(interval.width)})
        raw.append(proposal)
        if progress is not None:
            with stage("checkpoint"):
                progress(round_index, None, rounds[-1])
        if interval.width <= width_target:
            return {"status": "verified_target", "rounds": rounds,
                    "raw": raw, "interval": interval}
        if time.perf_counter() >= deadline:
            raise BudgetExpired("full arm budget expired after exact validation")
        if separation["add"]:
            active.update(separation["add"])
        elif tolerance_index + 1 < len(policy["eps_sequence"]):
            tolerance_index += 1
        else:
            return {"status": "verified_interval_too_wide", "rounds": rounds,
                    "raw": raw, "interval": interval}
    return {"status": "round_limit", "rounds": rounds,
            "raw": raw, "interval": last_interval}
