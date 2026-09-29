"""Bounded signed-pair oracles and the SEA2022 C-subinstance condition.

Numerical MILP output, bounds and equality are diagnostics. Exact acceptance is
available through Fraction/integer enumeration, guarded at ten active vertices.
The C-subinstance keeps ORIGINAL global pair coefficients incident to C and
zeroes outside-outside coefficients; it never recomputes a local null model.

Primary definition: Bläsius et al., SEA2022, section 3.3 Theorem 2; appendix proof
and Eq.(2), https://doi.org/10.4230/LIPIcs.SEA.2022.13. In maximization form, the
premise is optimum(B_C) == sum_{u<v in C} B_uv, including tied optima.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations
import math
from numbers import Integral, Real
import time
from typing import Iterable, Literal

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array, csr_array

from degree_contraction import PreparedGraph, prepare_graph


def _as_fraction(value) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Integral):
        return Fraction(int(value))
    if isinstance(value, Real) and math.isfinite(float(value)):
        return Fraction.from_float(float(value))
    raise ValueError("pair coefficients and resolution must be finite real numbers")


def _validate_n(n: int, maximum: int):
    if not isinstance(n, Integral) or n < 0:
        raise ValueError("the number of vertices must be a nonnegative integer")
    if n > maximum:
        raise ValueError(f"oracle is intentionally limited to n<={maximum}")


@dataclass
class PairOracleResult:
    labels: np.ndarray | None
    objective: float | None
    upper_bound: float | None
    status: int
    message: str
    mip_gap: float | None
    solver_seconds: float
    total_seconds: float
    pair_variables: int
    triangle_constraints: int
    arithmetic: str = "numerical MILP diagnostic"


@dataclass
class OracleResult:
    """Backward-compatible numerical modularity result; bounds use Q units."""
    labels: np.ndarray | None
    modularity: float | None
    upper_bound: float | None
    status: int
    message: str
    mip_gap: float | None
    solver_seconds: float
    total_seconds: float
    pair_variables: int
    triangle_constraints: int
    arithmetic: str = "numerical MILP diagnostic"


def solve_pair_affinities(n: int, pair_coefficients: Iterable, time_limit: float = 60.0,
                          *, max_vertices: int = 150) -> PairOracleResult:
    """Maximize sum_{u<v} B_uv [same label] using complete transitivity.

    Coefficients follow itertools.combinations(range(n), 2), including zero and
    negative pairs. A zero reported MIP gap remains a numerical solver result.
    """
    started = time.perf_counter()
    _validate_n(n, min(max_vertices, 150))
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("time_limit must be positive and finite")
    coefficients = np.asarray(tuple(pair_coefficients), dtype=float)
    if coefficients.shape != (n * (n - 1) // 2,) or not np.isfinite(coefficients).all():
        raise ValueError("supply one finite coefficient per unordered vertex pair")
    if n < 2:
        return PairOracleResult(np.arange(n), 0.0, 0.0, 0, "trivial", 0.0, 0.0,
                                time.perf_counter() - started, 0, 0)
    i, j = np.triu_indices(n, 1)
    pair_indices = -np.ones((n, n), dtype=np.int64)
    pair_indices[i, j] = np.arange(len(i))
    pair_indices[j, i] = pair_indices[i, j]
    triangles = list(combinations(range(n), 3))
    rows = np.empty(9 * len(triangles), dtype=np.int32)
    columns = np.empty_like(rows)
    values = np.empty(len(rows), dtype=float)
    for t, (u, v, w) in enumerate(triangles):
        pairs = (pair_indices[u, v], pair_indices[u, w], pair_indices[v, w])
        for negative in range(3):
            offset = 9 * t + 3 * negative
            rows[offset:offset + 3] = 3 * t + negative
            columns[offset:offset + 3] = pairs
            values[offset:offset + 3] = 1
            values[offset + negative] = -1
    constraints = LinearConstraint(
        coo_array((values, (rows, columns)), shape=(3 * len(triangles), len(i))).tocsc(),
        -np.inf, np.ones(3 * len(triangles)),
    )
    scale = max(1.0, float(np.max(np.abs(coefficients))))
    solver_started = time.perf_counter()
    result = milp(
        -coefficients / scale,
        integrality=np.ones(len(i), dtype=np.uint8), bounds=Bounds(0, 1),
        constraints=constraints, options={"time_limit": time_limit, "mip_rel_gap": 0.0},
    )
    solver_seconds = time.perf_counter() - solver_started
    labels = None
    objective = None
    if result.x is not None:
        parent = np.arange(n)
        def find(u):
            while parent[u] != u:
                parent[u] = parent[parent[u]]
                u = parent[u]
            return u
        for u, v, x in zip(i, j, result.x):
            if x > 0.5:
                parent[find(u)] = find(v)
        labels = np.array([find(u) for u in range(n)])
        same = labels[i] == labels[j]
        if not np.array_equal(same, result.x > 0.5):
            raise ArithmeticError("MILP incumbent is not a transitive partition")
        objective = float(math.fsum(map(float, coefficients[same])))
    dual_bound = getattr(result, "mip_dual_bound", None)
    upper = None if dual_bound is None else float(-dual_bound * scale)
    gap = getattr(result, "mip_gap", None)
    return PairOracleResult(labels, objective, upper, result.status, result.message,
                            None if gap is None else float(gap), solver_seconds,
                            time.perf_counter() - started, len(i), 3 * len(triangles))


def solve_affinities(affinities, time_limit: float = 60.0, *, max_vertices: int = 150):
    """Square signed-matrix adapter; diagonal values are partition constants."""
    shape = getattr(affinities, "shape", None)
    if shape is None or len(shape) != 2 or shape[0] != shape[1]:
        raise ValueError("affinities must be a square signed matrix")
    n = shape[0]
    _validate_n(n, min(max_vertices, 150))
    if hasattr(affinities, "toarray"):
        affinities = affinities.toarray()
    values = np.asarray(affinities, dtype=float)
    if not np.isfinite(values).all() or not np.array_equal(values, values.T):
        raise ValueError("affinities must be finite and exactly symmetric")
    return solve_pair_affinities(n, values[np.triu_indices(n, 1)], time_limit,
                                max_vertices=max_vertices)


def solve_modularity(A, gamma: float = 1.0, time_limit: float = 60.0) -> OracleResult:
    """Numerical full-Q adapter, retaining quotient adjacency diagonal mass."""
    started = time.perf_counter()
    shape = getattr(A, "shape", None)
    if isinstance(A, PreparedGraph):
        shape = A.adjacency.shape
    if shape is not None and len(shape) == 2:
        _validate_n(shape[0], 150)
    graph = prepare_graph(A if isinstance(A, PreparedGraph) else csr_array(A))
    a = graph.adjacency
    n = a.shape[0]
    _validate_n(n, 150)
    gamma = float(_as_fraction(gamma))
    if gamma < 0 or not math.isfinite(gamma):
        raise ValueError("gamma must be nonnegative and finite")
    total = graph.total_degree
    if total == 0:
        return OracleResult(np.arange(n), 0.0, 0.0, 0, "trivial", 0.0, 0.0,
                            time.perf_counter() - started, 0, 0)
    i, j = np.triu_indices(n, 1)
    pair_values = np.asarray(a[i, j]).ravel() - gamma * graph.degrees[i] * graph.degrees[j] / total
    constant = (a.diagonal().sum() - gamma * (graph.degrees @ graph.degrees) / total) / total
    result = solve_pair_affinities(n, pair_values, time_limit)
    objective = None if result.objective is None else float(2 * result.objective / total + constant)
    upper = None if result.upper_bound is None else float(2 * result.upper_bound / total + constant)
    return OracleResult(result.labels, objective, upper, result.status, result.message, result.mip_gap,
                        result.solver_seconds, time.perf_counter() - started,
                        result.pair_variables, result.triangle_constraints)


@dataclass
class ExactOracleResult:
    labels: tuple[int, ...]
    objective: Fraction
    optimum_count: int
    partitions_evaluated: int
    total_seconds: float
    pair_variables: int
    status: str = "exact_optimum"
    arithmetic: str = "exact Fraction enumeration"


def enumerate_pair_affinities(n: int, pair_coefficients: Iterable, *,
                              max_vertices: int = 10) -> ExactOracleResult:
    """Enumerate all set partitions exactly, retaining ties and one witness.

    A common denominator turns the recursive score updates into exact integer
    arithmetic. The ten-vertex guard bounds Bell-number growth (B_10=115975).
    """
    started = time.perf_counter()
    _validate_n(n, min(max_vertices, 10))
    coefficients = tuple(map(_as_fraction, pair_coefficients))
    if len(coefficients) != n * (n - 1) // 2:
        raise ValueError("supply one coefficient per unordered vertex pair")
    denominator = math.lcm(*(value.denominator for value in coefficients))
    matrix = [[0] * n for _ in range(n)]
    for (u, v), value in zip(combinations(range(n), 2), coefficients):
        matrix[u][v] = matrix[v][u] = value.numerator * (denominator // value.denominator)
    labels = [0] * n
    best = None
    witness = ()
    ties = count = 0
    def visit(vertex, maximum, score):
        nonlocal best, witness, ties, count
        if vertex == n:
            count += 1
            if best is None or score > best:
                best, witness, ties = score, tuple(labels), 1
            elif score == best:
                ties += 1
            return
        for label in range(maximum + 2):
            labels[vertex] = label
            gain = sum(matrix[vertex][u] for u in range(vertex) if labels[u] == label)
            visit(vertex + 1, max(maximum, label), score + gain)
    if n:
        visit(1, 0, 0)
    else:
        visit(0, -1, 0)
    assert best is not None
    return ExactOracleResult(witness, Fraction(best, denominator), ties, count,
                             time.perf_counter() - started, len(coefficients))


class CSubinstanceUnavailable(ValueError):
    pass


@dataclass
class CSubinstance:
    block: tuple[int, ...]
    vertices: tuple[int, ...]
    pair_coefficients: tuple[Fraction, ...]
    isolation_score: Fraction
    original_vertices: int
    omitted_nonpositive_exterior_vertices: int
    metadata: dict = field(default_factory=dict)


def build_c_subinstance(A, block: Iterable[int], gamma=1.0, *, max_vertices: int = 150,
                        reduce_nonpositive_exterior: bool = True) -> CSubinstance:
    """Build a bounded original-global-modularity C-subinstance sparsely.

    Exterior vertices whose affinities to every C vertex are <=0 can be made
    singleton without lowering this subinstance's objective: their other
    exterior pairs are zero. Removing them preserves its optimum exactly.
    The retained pair coefficients still use ORIGINAL full degrees and S.
    """
    graph = prepare_graph(A if isinstance(A, PreparedGraph) else csr_array(A))
    a = graph.adjacency
    n = a.shape[0]
    block = tuple(block)
    if not block or any(not isinstance(u, Integral) for u in block):
        raise ValueError("C must be a nonempty collection of integer vertices")
    block = tuple(sorted(map(int, block)))
    if len(set(block)) != len(block) or any(u < 0 or u >= n for u in block):
        raise ValueError("C contains duplicate or out-of-range vertices")
    if max_vertices < 1:
        raise ValueError("max_vertices must be positive")
    if len(block) > max_vertices:
        raise CSubinstanceUnavailable("C alone exceeds the active-vertex guard")
    gamma = _as_fraction(gamma)
    if gamma < 0:
        raise ValueError("gamma must be nonnegative")
    degrees, total = graph.exact_degrees()
    if total <= 0:
        raise CSubinstanceUnavailable("modularity requires positive total degree")
    inside = set(block)
    active = set(block)
    row_weights = {}
    for u in block:
        row = {}
        for pos in range(a.indptr[u], a.indptr[u + 1]):
            w = int(a.indices[pos])
            value = _as_fraction(a.data[pos])
            row[w] = value
            if (reduce_nonpositive_exterior and w not in inside
                    and value - gamma * degrees[u] * degrees[w] / total > 0):
                active.add(w)
                if len(active) > max_vertices:
                    raise CSubinstanceUnavailable("positive-affinity neighborhood exceeds the active-vertex guard")
        row_weights[u] = row
    if not reduce_nonpositive_exterior:
        if n > max_vertices:
            raise CSubinstanceUnavailable("full C-subinstance exceeds the active-vertex guard")
        active = set(range(n))
    vertices = tuple(sorted(active))
    coefficients = []
    isolation = Fraction()
    for u, v in combinations(vertices, 2):
        if u in inside or v in inside:
            value = (row_weights[u].get(v, Fraction()) if u in inside else row_weights[v].get(u, Fraction()))
            value -= gamma * degrees[u] * degrees[v] / total
        else:
            value = Fraction()
        coefficients.append(value)
        if u in inside and v in inside:
            isolation += value
    return CSubinstance(block, vertices, tuple(coefficients), isolation, n, n - len(vertices),
                        {"source": "https://doi.org/10.4230/LIPIcs.SEA.2022.13",
                         "definition": "global B incident to C, zero exterior-exterior",
                         "degree_source": "original graph including adjacency diagonal",
                         "gamma_exact": str(gamma), "graph_fingerprint": graph.fingerprint,
                         "original_vertices": n, "active_vertices": len(vertices),
                         "omitted_nonpositive_exterior_vertices": n - len(vertices),
                         "nonpositive_exterior_reduction": reduce_nonpositive_exterior})


@dataclass
class CSubinstanceResult:
    block: tuple[int, ...]
    active_vertices: tuple[int, ...]
    isolation_score: Fraction | float | None
    optimum: Fraction | float | None
    status: str
    certified: bool
    oracle: ExactOracleResult | PairOracleResult | None
    message: str
    metadata: dict = field(default_factory=dict)


def check_c_subinstance(A, block: Iterable[int], gamma=1.0, *,
                        arithmetic: Literal["exact", "numerical"] = "exact",
                        max_vertices: int | None = None, time_limit: float = 60.0,
                        tolerance: float = 1e-8,
                        reduce_nonpositive_exterior: bool = True) -> CSubinstanceResult:
    """Compare isolated-C score with subinstance optimum, never witness labels.

    Only exact_match sets certified=True. numerical_match denotes floating
    equality reported by a numerical MILP with compatible bounds. Timeouts
    remain unresolved; active-size restrictions return unavailable.
    """
    if arithmetic not in {"exact", "numerical"}:
        raise ValueError("arithmetic must be 'exact' or 'numerical'")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and nonnegative")
    block = tuple(block)
    limit = (10 if arithmetic == "exact" else 150) if max_vertices is None else max_vertices
    limit = min(limit, 10 if arithmetic == "exact" else 150)
    try:
        instance = build_c_subinstance(A, block, gamma, max_vertices=limit,
                                       reduce_nonpositive_exterior=reduce_nonpositive_exterior)
    except CSubinstanceUnavailable as error:
        return CSubinstanceResult(block, (), None, None, "unavailable", False, None, str(error),
                                   {"arithmetic": arithmetic, "active_vertex_limit": limit})
    if arithmetic == "exact":
        result = enumerate_pair_affinities(len(instance.vertices), instance.pair_coefficients,
                                           max_vertices=limit)
        match = result.objective == instance.isolation_score
        assert result.objective >= instance.isolation_score
        status = "exact_match" if match else "exact_nonmatch"
        return CSubinstanceResult(instance.block, instance.vertices, instance.isolation_score,
                                   result.objective, status, match, result,
                                   "exact score comparison includes all tied optima", instance.metadata)
    result = solve_pair_affinities(len(instance.vertices), instance.pair_coefficients, time_limit,
                                   max_vertices=limit)
    isolation = float(instance.isolation_score)
    status = "unresolved"
    if result.status == 0 and result.objective is not None and result.upper_bound is not None:
        scale = tolerance * max(1.0, abs(isolation), abs(result.objective), abs(result.upper_bound))
        if abs(result.objective - result.upper_bound) <= scale:
            if abs(result.objective - isolation) <= scale:
                status = "numerical_match"
            elif result.objective > isolation + scale:
                status = "numerical_nonmatch"
    metadata = dict(instance.metadata)
    metadata.update({"arithmetic": "numerical MILP diagnostic", "equality_tolerance": tolerance,
                     "numerical_objective_role": "incumbent, with numerical bound in oracle.upper_bound",
                     "active_vertex_limit": limit, "omitted_exterior_vertices": instance.omitted_nonpositive_exterior_vertices})
    numerical_optimum = result.objective if status != "unresolved" else None
    return CSubinstanceResult(instance.block, instance.vertices, isolation, numerical_optimum,
                               status, False, result, "floating equality is not a certificate", metadata)
