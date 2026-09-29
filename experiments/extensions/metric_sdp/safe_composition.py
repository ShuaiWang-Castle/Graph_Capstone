"""Exact sequential preprocessing for the plain PSD/box/metric relaxation.

S is a project-derived two-copy/uniform-copy composition, not full Rule5 or
KaPoCE. D reuses the unchanged core's rational actual-median acceptance.
SW runs S to a fixed point, then the stronger exact fixed-degree pair-distance
reference to a fresh fixed point. Every weak operation is rechecked on the
current exact quotient; no union of independently weak original groups occurs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import math
from numbers import Integral, Real
from time import perf_counter
from types import MappingProxyType

import numpy as np
from scipy import sparse

from degree_contraction import PreparedGraph, prepare_graph
from degree_contraction.certificate import _exact_projected_matrix, _exact_psd
from research.baselines.weighted_reference import (
    prepare_weighted_reference_graph, weighted_collective_reference,
)


def _fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Integral):
        return Fraction(int(value))
    if isinstance(value, np.floating) and value.dtype.itemsize > 8:
        raise ValueError("represented binary floating weights are limited to float64")
    if isinstance(value, Real) and math.isfinite(float(value)):
        return Fraction.from_float(float(value))
    raise ValueError("weights must be finite rational or represented real values")


def _gamma(value):
    if isinstance(value, (Fraction, Integral, str)):
        value = Fraction(value)
    else:
        raise TypeError("gamma must be a Fraction, integer or rational string")
    if value < 0:
        raise ValueError("gamma must be nonnegative")
    return value


def _json_exact(value):
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_exact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_exact(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class ExactGraph:
    """Validated immutable rational rows; cached degrees are derived, not trusted."""

    rows: tuple
    degrees: tuple[Fraction, ...] = field(init=False)
    volume: Fraction = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self):
        n = len(self.rows)
        if n < 1:
            raise ValueError("a nonempty graph is required")
        rows = []
        for source in self.rows:
            row = {}
            for v, raw in source.items():
                if isinstance(v, bool) or not isinstance(v, Integral) or not 0 <= v < n:
                    raise ValueError("invalid sparse vertex index")
                weight = _fraction(raw)
                if weight < 0:
                    raise ValueError("adjacency must be nonnegative")
                if weight:
                    row[int(v)] = weight
            rows.append(row)
        if any(rows[v].get(u, Fraction()) != x
               for u, row in enumerate(rows) for v, x in row.items()):
            raise ValueError("adjacency must be exactly symmetric")
        degrees = tuple(sum(row.values(), Fraction()) for row in rows)
        volume = sum(degrees, Fraction())
        if volume <= 0:
            raise ValueError("positive total volume is required")
        payload = [(u, v, str(x)) for u, row in enumerate(rows)
                   for v, x in sorted(row.items())]
        digest = hashlib.sha256(json.dumps(
            {"n": n, "entries": payload}, separators=(",", ":")).encode()).hexdigest()
        object.__setattr__(self, "rows", tuple(MappingProxyType(row) for row in rows))
        object.__setattr__(self, "degrees", degrees)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(self, "fingerprint", digest)

    @property
    def n(self):
        return len(self.rows)


def prepare_exact_graph(adjacency):
    if isinstance(adjacency, ExactGraph):
        return adjacency
    if isinstance(adjacency, PreparedGraph):
        adjacency = adjacency.adjacency
    if not sparse.issparse(adjacency) or adjacency.format != "csr":
        raise TypeError("CSR adjacency or this module's ExactGraph is required")
    if adjacency.shape[0] != adjacency.shape[1] or adjacency.shape[0] < 1:
        raise ValueError("a nonempty square adjacency is required")
    if adjacency.dtype.kind not in "biuf" or (
            adjacency.dtype.kind == "f" and adjacency.dtype.itemsize > 8):
        raise ValueError("CSR must contain integers or binary floats up to float64")
    a = sparse.csr_matrix(adjacency, copy=True)
    a.sort_indices()
    if not a.has_canonical_format:
        raise ValueError("duplicate CSR entries must be explicitly combined upstream")
    return ExactGraph(tuple(
        {int(v): _fraction(x) for v, x in zip(
            a.indices[a.indptr[u]:a.indptr[u + 1]],
            a.data[a.indptr[u]:a.indptr[u + 1]])}
        for u in range(a.shape[0])))


def _to_csr(graph):
    """Materialize only if every aggregate is exactly float64-representable."""
    indices, indptr, values = [], [0], []
    for row in graph.rows:
        for v, weight in sorted(row.items()):
            try:
                value = float(weight)
            except OverflowError as error:
                raise ArithmeticError("exact quotient cannot be represented in float64") from error
            if not math.isfinite(value) or Fraction.from_float(value) != weight:
                raise ArithmeticError("exact quotient cannot be represented in float64")
            indices.append(v)
            values.append(value)
        indptr.append(len(values))
    a = sparse.csr_matrix((np.asarray(values, dtype=np.float64),
                           np.asarray(indices, dtype=np.int64),
                           np.asarray(indptr, dtype=np.int64)), shape=(graph.n, graph.n))
    for array in (a.data, a.indices, a.indptr):
        array.flags.writeable = False
    return a


def _vertices(block, n):
    block = tuple(block)
    if len(block) < 2 or any(isinstance(u, bool) or not isinstance(u, Integral) for u in block):
        raise ValueError("a block needs at least two integer vertices")
    block = tuple(sorted(map(int, block)))
    if len(set(block)) != len(block) or block[0] < 0 or block[-1] >= n:
        raise ValueError("duplicate or out-of-range block vertex")
    return block


def _limits(graph, max_graph_size, max_block_size):
    if (isinstance(max_graph_size, bool) or not isinstance(max_graph_size, Integral)
            or not 1 <= max_graph_size <= 300):
        raise ValueError("max_graph_size must be an integer in [1,300]")
    if (isinstance(max_block_size, bool) or not isinstance(max_block_size, Integral)
            or not 2 <= max_block_size <= 64):
        raise ValueError("max_block_size must be an integer in [2,64]")
    if graph.n > max_graph_size:
        raise ValueError("input exceeds the metric-SDP graph domain")


def _signed(graph, u, v, beta):
    return graph.rows[u].get(v, Fraction()) - beta * graph.degrees[u] * graph.degrees[v]


def optimized_pair(adjacency, u, v, gamma=Fraction(1)):
    """Exact lower weighted-median minimizer, including ALL nonnegative pairs.

    p copies v to u. Exterior columns absent from both rows are represented by
    one full-degree-volume term. Roots outside [0,1] still contribute to the
    median; the unconstrained lower median is then clipped to the interval.
    """
    graph, g = prepare_exact_graph(adjacency), _gamma(gamma)
    _vertices((u, v), graph.n)
    u, v = sorted((int(u), int(v)))
    beta = g / graph.volume
    active = (graph.rows[u].keys() | graph.rows[v].keys()) - {u, v}
    inactive_volume = graph.volume - graph.degrees[u] - graph.degrees[v]
    inactive_volume -= sum((graph.degrees[w] for w in active), Fraction())
    if inactive_volume < 0:
        raise ArithmeticError("negative rank-one complement volume")
    terms, constant = [], Fraction()
    for w in sorted(active):
        bu, bv = _signed(graph, u, w, beta), _signed(graph, v, w, beta)
        slope = bu + bv
        if slope:
            terms.append((bu / slope, abs(slope)))
        else:
            constant += abs(bu)
    inactive_weight = beta * inactive_volume * (graph.degrees[u] + graph.degrees[v])
    if inactive_weight:
        terms.append((graph.degrees[u] / (graph.degrees[u] + graph.degrees[v]),
                      inactive_weight))
    total_weight = sum((weight for _, weight in terms), Fraction())
    p = Fraction()
    if total_weight:
        accumulated = Fraction()
        for root, weight in sorted(terms):
            accumulated += weight
            if 2 * accumulated >= total_weight:
                p = max(Fraction(), min(Fraction(1), root))
                break
    loss = constant + sum((weight * abs(p - root) for root, weight in terms), Fraction())
    affinity = _signed(graph, u, v, beta)
    margin = affinity - loss
    return {"criterion": "exact optimized constant-mixture pair copy",
            "u": u, "v": v, "p": p, "loss": loss, "margin": margin,
            "affinity": affinity, "certified": margin >= 0, "strict": margin > 0,
            "active_exterior_columns": len(active), "inactive_volume": inactive_volume,
            "tie_policy": "smallest minimizing probability",
            "weak_anchor_support": [u] if p == 1 else [v] if p == 0 else [u, v]}


def _schur_psd(matrix):
    residual = [list(row) for row in matrix]
    pivots = []
    for i in range(len(residual)):
        pivot = residual[i][i]
        pivots.append(pivot)
        if pivot < 0 or (pivot == 0 and any(residual[i][j]
                                            for j in range(i + 1, len(residual)))):
            return False, False, {"pivots": pivots, "obstruction_position": i}
        if pivot:
            for j in range(i + 1, len(residual)):
                factor = residual[j][i] / pivot
                if not factor:
                    continue
                for h in range(j, len(residual)):
                    residual[j][h] -= factor * residual[i][h]
                    residual[h][j] = residual[j][h]
    return True, all(p > 0 for p in pivots), {"pivots": pivots, "obstruction_position": None}


def uniform_collective(adjacency, block, gamma=Fraction(1), *,
                       max_graph_size=300, max_block_size=64):
    """Full uniform pair distances via sparse support plus exact null complement."""
    graph, g = prepare_exact_graph(adjacency), _gamma(gamma)
    _limits(graph, max_graph_size, max_block_size)
    vertices = _vertices(block, graph.n)
    if len(vertices) > max_block_size:
        return {"criterion": "exact uniform collective copy", "certified": False,
                "strict": False, "available": False, "status": "mapped_block_size_limit"}
    inside, k, beta = set(vertices), len(vertices), g / graph.volume
    outside_volume = graph.volume - sum((graph.degrees[u] for u in vertices), Fraction())
    matrix = [[Fraction() for _ in vertices] for _ in vertices]
    distances = [[Fraction() for _ in vertices] for _ in vertices]
    for i, u in enumerate(vertices):
        for j in range(i + 1, k):
            v = vertices[j]
            active = (graph.rows[u].keys() | graph.rows[v].keys()) - inside
            inactive = outside_volume - sum((graph.degrees[w] for w in active), Fraction())
            if inactive < 0:
                raise ArithmeticError("negative uniform complement volume")
            null_difference = beta * (graph.degrees[u] - graph.degrees[v])
            distance = abs(null_difference) * inactive
            distance += sum((abs(graph.rows[u].get(w, Fraction())
                                 - graph.rows[v].get(w, Fraction())
                                 - null_difference * graph.degrees[w])
                             for w in active), Fraction())
            distances[i][j] = distances[j][i] = distance
            weight = _signed(graph, u, v, beta) - distance / k
            matrix[i][i] += weight
            matrix[j][j] += weight
            matrix[i][j] = matrix[j][i] = -weight
    pivot = k - 1
    projected = [[matrix[i][j] - matrix[i][pivot] - matrix[pivot][j] + matrix[pivot][pivot]
                  for j in range(k - 1)] for i in range(k - 1)]
    accepted, strict, elimination = _schur_psd(projected)
    return {"criterion": "exact uniform collective copy", "block": vertices,
            "certified": accepted, "strict": strict, "available": True,
            "status": "verified_exact_psd" if accepted else "failed_exact_psd",
            "margin_exact": None, "distances": distances,
            "projected_matrix": projected, "elimination": elimination,
            "basis": "e_i-e_last spanning ones-perp; pivots are not eigenvalue margins"}


def _degree_collective(graph, vertices, g, cap, prepared):
    if len(vertices) > cap or any(graph.degrees[u] <= 0 for u in vertices):
        return {"criterion": "core exact actual-median degree copy", "certified": False,
                "strict": False, "available": False,
                "status": "mapped_block_size_limit" if len(vertices) > cap else "zero_degree_excluded"}
    matrix, pivot, delta, mean = _exact_projected_matrix(prepared, vertices, g)
    accepted, strict, elimination = _exact_psd(matrix)
    return {"criterion": "core exact actual-median degree copy", "block": vertices,
            "certified": accepted, "strict": strict, "available": True,
            "status": "verified_exact_psd" if accepted else "failed_exact_psd",
            "margin_exact": None, "projected_matrix": matrix, "basis_pivot": vertices[pivot],
            "delta": delta, "weighted_mean_delta": mean, "elimination": elimination,
            "acceptance": "unchanged core rational actual-median projected matrix and LDL"}


def weighted_collective(adjacency, block, gamma=Fraction(1), *,
                        max_graph_size=300, max_block_size=64):
    """Unchanged fixed-degree full-pair reference; no adaptive anchor search."""
    graph, g = prepare_exact_graph(adjacency), _gamma(gamma)
    _limits(graph, max_graph_size, max_block_size)
    vertices = _vertices(block, graph.n)
    prepared = prepare_weighted_reference_graph(graph)
    return _weighted_collective(prepared, vertices, g, max_block_size)


def _weighted_collective(prepared, vertices, g, max_block_size):
    return weighted_collective_reference(
        prepared, vertices, g, penalty="full_pair_distance",
        exact_max_size=max_block_size, diagnostics=False, include_details=True)


def _bank(bank, n):
    raw = getattr(bank, "blocks", bank)
    return tuple(sorted({_vertices(block, n) for block in raw}))


def _mapped_bank(bank, membership):
    sources = {}
    for original in bank:
        current = tuple(sorted({membership[u] for u in original}))
        if len(current) >= 2:
            sources.setdefault(current, []).append(original)
    return [(block, sources[block]) for block in sorted(sources)]


def _merge(graph, vertices):
    selected, first = set(vertices), min(vertices)
    groups = [(tuple(vertices) if u == first else (u,)) for u in range(graph.n)
              if u == first or u not in selected]
    membership = [None] * graph.n
    for new, group in enumerate(groups):
        for old in group:
            membership[old] = new
    rows = [{} for _ in groups]
    for u, row in enumerate(graph.rows):
        target = rows[membership[u]]
        for v, weight in row.items():
            new_v = membership[v]
            target[new_v] = target.get(new_v, Fraction()) + weight
    result = ExactGraph(tuple(rows))
    expected = tuple(sum((graph.degrees[u] for u in group), Fraction()) for group in groups)
    if result.degrees != expected or result.volume != graph.volume or result.n >= graph.n:
        raise ArithmeticError("invalid exact merge quotient degree/mass/termination identity")
    return result, membership


@dataclass(frozen=True, slots=True)
class CompositionResult:
    graph: ExactGraph
    adjacency: sparse.csr_matrix
    membership: np.ndarray
    groups: tuple[tuple[int, ...], ...]
    degrees: tuple[Fraction, ...]
    total_degree: Fraction
    operations: tuple[dict, ...]
    metadata: dict

    @property
    def trace(self):
        return self.operations


def run_composition(adjacency, original_bank, gamma=Fraction(1), *,
                    mode="S", max_graph_size=300, max_block_size=64):
    """Run deterministic S/D/SD/SW; return actual CSR IDs and exact operation proof.

    S: all NONNEGATIVE signed pairs lexicographically, then mapped-bank blocks
    lexicographically. One accepted operation is merged, then all checks restart.
    D and W: the same original bank mapped/deduplicated BEFORE cap checks, with
    a fresh check and exact merge after each acceptance. SD/SW never return to S.
    Common signed-component presolve is owned by the downstream runtime.
    """
    started = perf_counter()
    graph, g = prepare_exact_graph(adjacency), _gamma(gamma)
    _limits(graph, max_graph_size, max_block_size)
    if mode not in {"S", "D", "SD", "SW"}:
        raise ValueError("mode must be S, D, SD or SW")
    bank = _bank(original_bank, graph.n)
    original = graph
    membership = list(range(graph.n))
    operations, phases, counts = [], [], Counter()
    seconds = {"preparation": perf_counter() - started, "checking": 0.0,
               "quotient": 0.0, "final_materialization": 0.0}
    sequence = ("S", "D") if mode == "SD" else ("S", "W") if mode == "SW" else (mode,)
    for stage in sequence:
        stage_n, stage_ops = graph.n, len(operations)
        while graph.n > 1:
            check_started = perf_counter()
            chosen, certificate, source_blocks = None, None, []
            if stage == "S":
                beta = g / graph.volume
                for u in range(graph.n):
                    for v in range(u + 1, graph.n):
                        if _signed(graph, u, v, beta) < 0:
                            continue
                        counts["pair_checks"] += 1
                        candidate = optimized_pair(graph, u, v, g)
                        if candidate["certified"]:
                            chosen, certificate = (u, v), candidate
                            break
                    if chosen is not None:
                        break
            if chosen is None:
                prepared = None
                for block, sources in _mapped_bank(bank, membership):
                    if len(block) > max_block_size:
                        counts[f"{stage}_mapped_cap_exclusions"] += 1
                        continue
                    counts[{"S": "uniform_checks", "D": "degree_checks",
                            "W": "weighted_checks"}[stage]] += 1
                    if stage == "S":
                        candidate = uniform_collective(graph, block, g,
                            max_graph_size=max_graph_size, max_block_size=max_block_size)
                    elif stage == "D":
                        if any(graph.degrees[u] <= 0 for u in block):
                            counts["D_zero_degree_exclusions"] += 1
                            continue
                        if prepared is None:
                            prepared = prepare_graph(_to_csr(graph))
                        candidate = _degree_collective(graph, block, g, max_block_size, prepared)
                    else:
                        if prepared is None:
                            prepared = prepare_weighted_reference_graph(graph)
                        candidate = _weighted_collective(prepared, block, g, max_block_size)
                    if not candidate.get("available", True):
                        counts[f"{stage}_unavailable_{candidate['status']}"] += 1
                    if candidate["certified"]:
                        chosen, certificate, source_blocks = block, candidate, sources
                        break
            if chosen is None:
                seconds["checking"] += perf_counter() - check_started
                break
            before = list(membership)
            operation = {"index": len(operations), "stage": stage,
                         "current_n_before": graph.n, "block_current": list(chosen),
                         "original_groups_before": [[u for u, c in enumerate(before) if c == v]
                                                    for v in chosen],
                         "original_bank_blocks": [list(x) for x in source_blocks],
                         "original_membership_before": before,
                         "current_graph_sha256": graph.fingerprint,
                         "gamma_exact": str(g), "S_exact": str(graph.volume),
                         "block_volume_exact": str(sum((graph.degrees[v] for v in chosen), Fraction())),
                         "certificate": _json_exact(certificate)}
            seconds["checking"] += perf_counter() - check_started
            quotient_started = perf_counter()
            graph, old_to_new = _merge(graph, chosen)
            membership = [old_to_new[c] for c in before]
            expected = [sum((original.degrees[u] for u, c in enumerate(membership) if c == v),
                            Fraction()) for v in range(graph.n)]
            if tuple(expected) != graph.degrees or graph.volume != original.volume:
                raise ArithmeticError("composed original membership changed exact degrees or S")
            operation.update(current_n_after=graph.n, old_to_new_membership=old_to_new,
                             original_membership_after=list(membership),
                             quotient_graph_sha256=graph.fingerprint,
                             quotient_degrees_exact=list(map(str, graph.degrees)))
            operations.append(operation)
            counts[f"{stage}_accepted_operations"] += 1
            seconds["quotient"] += perf_counter() - quotient_started
        phases.append({"stage": stage, "start_n": stage_n, "end_n": graph.n,
                       "accepted_operations": len(operations) - stage_ops, "fixed_point": True})
    materialize_started = perf_counter()
    final = _to_csr(graph)
    groups = tuple(tuple(u for u, c in enumerate(membership) if c == v) for v in range(graph.n))
    mapping = np.asarray(membership, dtype=np.int64)
    mapping.flags.writeable = False
    seconds["final_materialization"] = perf_counter() - materialize_started
    metadata = {"schema": "plain-metric-sdp-safe-composition-v1", "mode": mode,
                "gamma_exact": str(g), "original_S_exact": str(original.volume),
                "original_n": original.n, "final_n": graph.n,
                "original_graph_sha256": original.fingerprint,
                "quotient_graph_sha256": graph.fingerprint,
                "original_bank": [list(x) for x in bank],
                "counts": dict(counts), "phases": phases,
                "stage_seconds": seconds, "outer_call_seconds": perf_counter() - started,
                "exact_block_cap": max_block_size, "graph_cap": max_graph_size,
                "pair_policy": "ALL B_uv>=0, lower weighted median, lexicographic sequential restart",
                "bank_policy": "original bank mapped/deduplicated before cap; lexicographic; no resampling",
                "weak_policy": "one current-quotient merge and full restart; no original weak union",
                "quotient_identity": "A_next=R.T A_current R; loops retain doubled internal mass",
                "objective_identity_verified": True,
                "scope": "derived relaxed-safe S/D/SD/SW, not generic discrete R or full published methods"}
    return CompositionResult(graph, final, mapping, groups, graph.degrees, graph.volume,
                             tuple(operations), metadata)
