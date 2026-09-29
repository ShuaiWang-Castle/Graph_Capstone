"""Independent rational weighted collective references, not published methods.

No production certificate or private acceptance routine is imported. Sparse
rows and full exact degrees are prepared once. All variants use positive-degree
blocks, retain quotient diagonals in degrees and restrict exact matrices to
d-perp. Floating generalized eigenvalues are diagnostics only.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
from numbers import Integral, Real
from time import perf_counter
from types import MappingProxyType

import numpy as np
from scipy import sparse


def _rational(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Integral):
        return Fraction(int(value))
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError("finite real/rational values required") from error
    if isinstance(value, np.floating) and value.dtype.itemsize > 8:
        raise ValueError("binary floating inputs are limited to float64")
    if isinstance(value, Real) and math.isfinite(float(value)):
        return Fraction.from_float(float(value))
    raise ValueError("finite real/rational values required")


@dataclass(frozen=True, slots=True)
class WeightedReferenceGraph:
    rows: tuple
    degrees: tuple[Fraction, ...]
    volume: Fraction
    fingerprint: str
    preparation_seconds: float

    @property
    def n(self):
        return len(self.rows)


def prepare_weighted_reference_graph(adjacency):
    """Copy/validate O(n+m) exact sparse rows, without using cached core degrees.

    Accept CSR, the production public PreparedGraph (through its CSR), or a
    public prepared sparse-row graph. Foreign degrees are independently rebuilt.
    Decimal strings are accepted for gamma; binary floats retain their exact
    represented value, matching the production rational arithmetic convention.
    """
    if isinstance(adjacency, WeightedReferenceGraph):
        return adjacency
    started = perf_counter()
    if hasattr(adjacency, "adjacency"):
        adjacency = adjacency.adjacency
    if hasattr(adjacency, "rows") and not sparse.issparse(adjacency):
        raw_rows = adjacency.rows
        rows = [{int(v): _rational(weight) for v, weight in row.items() if weight != 0}
                for row in raw_rows]
        if any(not isinstance(v, Integral) for row in raw_rows for v in row):
            raise ValueError("sparse row indices must be integers")
    else:
        if not sparse.issparse(adjacency) or adjacency.format != "csr":
            raise TypeError("reference requires CSR or a prepared sparse-row graph")
        if len(adjacency.shape) != 2 or adjacency.shape[0] != adjacency.shape[1]:
            raise ValueError("adjacency must be square")
        if (adjacency.dtype.kind not in "biuf" or not np.isfinite(adjacency.data).all()
                or (adjacency.dtype.kind == "f" and adjacency.dtype.itemsize > 8)):
            raise ValueError("finite real adjacency weights required")
        a = sparse.csr_matrix(adjacency, copy=True)
        a.sort_indices()
        if not a.has_canonical_format:
            raise ValueError("duplicate CSR edges must be combined explicitly")
        rows = [{int(v): _rational(weight) for v, weight in
                 zip(a.indices[a.indptr[u]:a.indptr[u + 1]], a.data[a.indptr[u]:a.indptr[u + 1]])
                 if weight != 0} for u in range(a.shape[0])]
    n = len(rows)
    for u, row in enumerate(rows):
        for v, weight in row.items():
            if v < 0 or v >= n or weight < 0:
                raise ValueError("nonnegative adjacency and valid sparse indices required")
            if rows[v].get(u, Fraction()) != weight:
                raise ValueError("adjacency must be exactly symmetric")
    degrees = tuple(sum(row.values(), Fraction()) for row in rows)
    digest = hashlib.sha256(str(n).encode("ascii"))
    for u, row in enumerate(rows):
        for v, weight in sorted(row.items()):
            digest.update(f";{u},{v},{weight.numerator}/{weight.denominator}".encode("ascii"))
    return WeightedReferenceGraph(tuple(MappingProxyType(row) for row in rows), degrees,
                                  sum(degrees, Fraction()), digest.hexdigest(),
                                  perf_counter() - started)


def _vertices(block, n):
    vertices = tuple(block)
    if len(vertices) < 2 or any(isinstance(u, bool) or not isinstance(u, Integral) for u in vertices):
        raise ValueError("block needs at least two integer vertices")
    vertices = tuple(map(int, vertices))
    if len(set(vertices)) != len(vertices) or any(u < 0 or u >= n for u in vertices):
        raise ValueError("block vertices must be distinct and within the graph")
    return vertices


def _parameters(center, penalty, exact_max_size):
    if center not in {"zero", "anchor", "median"}:
        raise ValueError("center must be zero, anchor or median")
    if penalty not in {"center", "full_pair_distance"}:
        raise ValueError("penalty must be center or full_pair_distance")
    if isinstance(exact_max_size, bool) or not isinstance(exact_max_size, Integral) or exact_max_size < 2:
        raise ValueError("exact_max_size must be an integer >=2")
    return min(int(exact_max_size), 64)


def _median(positive, size):
    positive = sorted(positive)
    missing = size - len(positive)
    def rank(index):
        return Fraction() if index < missing else positive[index - missing]
    return rank(size // 2) if size % 2 else (rank(size // 2 - 1) + rank(size // 2)) / 2


def _exterior_rows(graph, vertices):
    inside = set(vertices)
    return [{w: weight for w, weight in graph.rows[u].items() if w not in inside}
            for u in vertices]


def _center_deviation(exterior, degrees, center, anchor_position):
    normalized = [{w: weight / degree for w, weight in row.items()}
                  for row, degree in zip(exterior, degrees)]
    if center == "zero":
        reference = {}
    elif center == "anchor":
        reference = normalized[anchor_position].copy()
    else:
        columns = {}
        for row in normalized:
            for w, weight in row.items():
                columns.setdefault(w, []).append(weight)
        reference = {w: _median(values, len(degrees)) for w, values in columns.items()}
        reference = {w: value for w, value in reference.items() if value != 0}
    center_total = sum(reference.values(), Fraction())
    delta = [sum(row.values(), Fraction()) + center_total
             - 2 * sum((min(value, reference.get(w, Fraction())) for w, value in row.items()), Fraction())
             for row in normalized]
    assert all(value >= 0 for value in delta)
    mean = sum((degree * value for degree, value in zip(degrees, delta)), Fraction()) / sum(degrees)
    return delta, mean, reference


def _matrix(graph, vertices, gamma, center, penalty, anchor_position):
    degrees = [graph.degrees[u] for u in vertices]
    volume, total, k = sum(degrees), graph.volume, len(vertices)
    exterior = _exterior_rows(graph, vertices)
    matrix = [[Fraction() for _ in vertices] for _ in vertices]
    details = {"exterior_incidences": sum(map(len, exterior)),
               "touched_exterior_columns": len(set().union(*(set(row) for row in exterior)))}
    if penalty == "full_pair_distance":
        penalties = [[Fraction() for _ in vertices] for _ in vertices]
        union_visits = 0
        for i in range(k):
            for j in range(i + 1, k):
                union = exterior[i].keys() | exterior[j].keys()
                union_visits += len(union)
                value = sum((abs(degrees[j] * exterior[i].get(w, Fraction())
                                 - degrees[i] * exterior[j].get(w, Fraction()))
                             for w in union), Fraction()) / volume
                penalties[i][j] = penalties[j][i] = value
                affinity = (graph.rows[vertices[i]].get(vertices[j], Fraction())
                            - gamma * degrees[i] * degrees[j] / total - value)
                matrix[i][i] += affinity
                matrix[j][j] += affinity
                matrix[i][j] = matrix[j][i] = -affinity
        details.update({"pair_union_coordinate_visits": union_visits, "penalties": penalties})
    else:
        delta, mean, reference = _center_deviation(exterior, degrees, center, anchor_position)
        for i in range(k):
            for j in range(i + 1, k):
                weight = graph.rows[vertices[i]].get(vertices[j], Fraction())
                matrix[i][i] += weight
                matrix[j][j] += weight
                matrix[i][j] = matrix[j][i] = -weight
            matrix[i][i] -= degrees[i] * (delta[i] + mean + gamma * volume / total)
        details.update({"delta": delta, "weighted_mean_delta": mean, "reference": reference})
    return matrix, degrees, details


def _project(matrix, degrees):
    # Deliberately use the first vertex, rather than production's max-degree
    # pivot. Columns e_i-(d_i/d_0)e_0 span d-perp exactly.
    ratios = [degree / degrees[0] for degree in degrees[1:]]
    return [[matrix[i][j] - ri * matrix[0][j] - rj * matrix[i][0]
             + ri * rj * matrix[0][0]
             for j, rj in enumerate(ratios, 1)] for i, ri in enumerate(ratios, 1)]


def _exact_psd_reference(matrix):
    """Complete diagonal-pivot Fraction Schur test, including singular PSD.

    Any negative residual diagonal rejects PSD. Otherwise eliminate a largest
    positive diagonal. If every residual diagonal is zero, PSD requires every
    residual entry zero. No floating pivot or tolerance participates.
    """
    residual = [row.copy() for row in matrix]
    positives = 0
    while residual:
        if any(residual[i][i] < 0 for i in range(len(residual))):
            return False, False, {"positive_pivots": positives, "obstruction": "negative residual diagonal"}
        pivot = max(range(len(residual)), key=lambda i: residual[i][i])
        value = residual[pivot][pivot]
        if value == 0:
            all_zero = all(entry == 0 for row in residual for entry in row)
            return all_zero, False, {"positive_pivots": positives, "zero_directions": len(residual),
                                     "obstruction": None if all_zero else "zero diagonal with nonzero residual entry"}
        remaining = [i for i in range(len(residual)) if i != pivot]
        residual = [[residual[i][j] - residual[i][pivot] * residual[pivot][j] / value
                     for j in remaining] for i in remaining]
        positives += 1
    return True, True, {"positive_pivots": positives, "zero_directions": 0, "obstruction": None}


def _float_margin(matrix, degrees):
    """Diagnostic generalized eigenvalue on sqrt(d)-perp, never acceptance."""
    try:
        degree = np.array(list(map(float, degrees)))
        values = np.array([[float(entry) for entry in row] for row in matrix])
        if not np.isfinite(degree).all() or not np.isfinite(values).all() or (degree <= 0).any():
            return None
        root = np.sqrt(degree)
        # QR's first column spans sqrt(d); remaining columns are its complement.
        basis = np.linalg.qr(np.column_stack((root, np.eye(len(degree))[:, 1:])))[0][:, 1:]
        normalized = values / root[:, None] / root[None, :]
        projected = basis.T @ normalized @ basis
        projected = (projected + projected.T) / 2
        margin = float(np.linalg.eigvalsh(projected)[0])
        return margin if math.isfinite(margin) else None
    except (OverflowError, FloatingPointError, np.linalg.LinAlgError):
        return None


def _base(graph, vertices, gamma, center, penalty, cap, prepared):
    return {"criterion": "project-derived exact degree-weighted collective reference",
            "block": list(vertices), "gamma": str(gamma), "center": center if penalty == "center" else None,
            "penalty": penalty, "certified": False, "strict": False, "available": True,
            "margin": None, "guarantee": "none", "diagnostics": {"certifies": False, "margin": None},
            "metadata": {"graph_fingerprint": graph.fingerprint,
                         "acceptance_arithmetic": "exact Fraction complete-pivot Schur PSD",
                         "diagnostic_arithmetic": "unvalidated float64 generalized eigenvalue",
                         "input_weights": "integers/rationals, or exact represented binary floats",
                         "degree_source": "full original graph including adjacency diagonal",
                         "block_volume_exact": str(sum(graph.degrees[u] for u in vertices)),
                         "total_volume_exact": str(graph.volume), "gamma_exact": str(gamma),
                         "basis": "e_i-(d_i/d_first)e_first spanning d-perp",
                         "exact_block_limit": cap, "absolute_exact_block_limit": 64,
                         "prepared_storage": "O(n+m) immutable exact sparse rows; no dense exterior table",
                         "input_prepared": prepared,
                         "preparation_seconds_charged": 0.0 if prepared else graph.preparation_seconds}}


def weighted_collective_reference(adjacency, block, gamma=Fraction(1), *,
                                  center="median", penalty="center", anchor=None,
                                  exact_max_size=64, diagnostics=True, include_details=False):
    """Forced-EXACT zero/anchor/median/full-pair ablation, capped at64.

    An anchor is a vertex of K; default is the first supplied vertex, fixed
    before testing. All center deviations include implicit exterior zeros.
    Full-pair penalties use sparse union rows and cancel the null term exactly.
    ``margin`` and the separate ``diagnostics`` never determine acceptance.
    """
    cap = _parameters(center, penalty, exact_max_size)
    prepared = isinstance(adjacency, WeightedReferenceGraph)
    graph = prepare_weighted_reference_graph(adjacency)
    vertices, gamma = _vertices(block, graph.n), _rational(gamma)
    if gamma < 0:
        raise ValueError("gamma must be nonnegative")
    anchor_position = 0
    if anchor is not None:
        if center != "anchor" or penalty != "center" or anchor not in vertices:
            raise ValueError("anchor must be a block vertex for the anchor-center variant")
        anchor_position = vertices.index(anchor)
    result = _base(graph, vertices, gamma, center, penalty, cap, prepared)
    status = None
    if len(vertices) > cap:
        status = "exact_size_limit"
    elif graph.volume <= 0:
        status = "no_positive_volume"
    elif any(graph.degrees[u] <= 0 for u in vertices):
        status = "zero_degree_excluded"
        result["metadata"]["excluded_vertices"] = [u for u in vertices if graph.degrees[u] <= 0]
    if status:
        result.update(available=False, status=status, verification_status=status)
        return result
    started = perf_counter()
    matrix, degrees, details = _matrix(graph, vertices, gamma, center, penalty, anchor_position)
    projected = _project(matrix, degrees)
    result["metadata"]["assembly_seconds"] = perf_counter() - started
    started = perf_counter()
    certified, strict, elimination = _exact_psd_reference(projected)
    result["metadata"]["verification_seconds"] = perf_counter() - started
    status = ("verified_positive_definite" if strict else "verified_positive_semidefinite") if certified else "failed_exact_psd"
    result.update(certified=certified, strict=strict, status=status, verification_status=status)
    result["metadata"].update({"exact_elimination": elimination,
                              "exact_projected_dimension": len(vertices) - 1,
                              "exterior_incidences": details["exterior_incidences"],
                              "touched_exterior_columns": details["touched_exterior_columns"]})
    if penalty == "center":
        result["metadata"].update({"exact_delta": list(map(str, details["delta"])),
                                  "exact_weighted_mean_delta": str(details["weighted_mean_delta"]),
                                  "nonzero_center_columns": len(details["reference"]),
                                  "anchor_vertex": vertices[anchor_position] if center == "anchor" else None})
    else:
        result["metadata"]["pair_union_coordinate_visits"] = details["pair_union_coordinate_visits"]
    if include_details:
        result["metadata"]["exact_projected_matrix"] = [[str(entry) for entry in row] for row in projected]
        if penalty == "center":
            result["metadata"]["exact_center"] = {str(w): str(value) for w, value in details["reference"].items()}
        else:
            result["metadata"]["exact_pair_penalties"] = [[str(entry) for entry in row] for row in details["penalties"]]
    if diagnostics:
        margin = _float_margin(matrix, degrees)
        result["margin"] = margin
        result["diagnostics"].update(margin=margin, positive_screen=None if margin is None else margin > 0,
                                     status="unvalidated" if margin is not None else "unavailable_numerically")
    result["guarantee"] = ("every optimum fuses the block" if strict else "a fused optimum exists") if certified else "none"
    return result


# Public spelling requested by the experiment runner; same function/signature.
weighted_contrast = weighted_collective_reference


def dense_exterior_diagnostic(adjacency, block, gamma=Fraction(1), *, center="median",
                             penalty="center", anchor=None, max_vertices=20000,
                             max_block_size=64):
    """ISOLATED scaling reference: materialize k-by-(n-k), never certify.

    Limits are hard (n<=20000,k<=64). Memory metadata is payload shape/bytes,
    not a measured process peak. Exact references are separate API calls.
    """
    cap = _parameters(center, penalty, max_block_size)
    if isinstance(max_vertices, bool) or not isinstance(max_vertices, Integral) or max_vertices < 2:
        raise ValueError("max_vertices must be an integer >=2")
    prepared = isinstance(adjacency, WeightedReferenceGraph)
    graph = prepare_weighted_reference_graph(adjacency)
    vertices, gamma = _vertices(block, graph.n), _rational(gamma)
    if gamma < 0:
        raise ValueError("gamma must be nonnegative")
    result = _base(graph, vertices, gamma, center, penalty, cap, prepared)
    result["criterion"] = "isolated dense exterior floating diagnostic"
    result["metadata"]["acceptance_arithmetic"] = "none: floating diagnostic cannot certify"
    result["metadata"]["dense_vertex_limit"] = min(int(max_vertices), 20000)
    if graph.n > min(int(max_vertices), 20000) or len(vertices) > cap:
        result.update(available=False, status="dense_diagnostic_size_limit",
                      verification_status="not_verified")
        return result
    if graph.volume <= 0 or any(graph.degrees[u] <= 0 for u in vertices):
        result.update(available=False, status="zero_degree_excluded", verification_status="not_verified")
        return result
    if anchor is not None and (center != "anchor" or penalty != "center" or anchor not in vertices):
        raise ValueError("anchor must be a block vertex for the anchor-center variant")
    started = perf_counter()
    inside = set(vertices)
    outside = [u for u in range(graph.n) if u not in inside]
    location = dict(zip(outside, range(len(outside))))
    degrees = np.array([float(graph.degrees[u]) for u in vertices])
    exterior = np.zeros((len(vertices), len(outside)), dtype=np.float64)
    for i, u in enumerate(vertices):
        for w, value in graph.rows[u].items():
            if w in location:
                exterior[i, location[w]] = float(value) / degrees[i]
    k, volume, total = len(vertices), float(sum(graph.degrees[u] for u in vertices)), float(graph.volume)
    matrix = np.zeros((k, k), dtype=float)
    if penalty == "center":
        if center == "zero":
            reference = np.zeros(len(outside))
        elif center == "anchor":
            reference = exterior[0 if anchor is None else vertices.index(anchor)]
        else:
            reference = np.median(exterior, axis=0)
        delta = np.abs(exterior - reference).sum(axis=1)
        mean = float(delta @ degrees / volume)
        for i in range(k):
            for j in range(i + 1, k):
                weight = float(graph.rows[vertices[i]].get(vertices[j], 0))
                matrix[i, i] += weight
                matrix[j, j] += weight
                matrix[i, j] = matrix[j, i] = -weight
            matrix[i, i] -= degrees[i] * (delta[i] + mean + float(gamma) * volume / total)
        result["diagnostics"].update(delta=delta.tolist(), weighted_mean_delta=mean)
        result.update(delta=delta.tolist(), weighted_mean_delta=mean)
    else:
        for i in range(k):
            for j in range(i + 1, k):
                pair = degrees[i] * degrees[j] / volume * np.abs(exterior[i] - exterior[j]).sum()
                affinity = float(graph.rows[vertices[i]].get(vertices[j], 0)) - float(gamma) * degrees[i] * degrees[j] / total - pair
                matrix[i, i] += affinity
                matrix[j, j] += affinity
                matrix[i, j] = matrix[j, i] = -affinity
    result["metadata"].update({"dense_exterior_shape": list(exterior.shape),
                              "dense_exterior_payload_bytes": int(exterior.nbytes),
                              "memory_measurement": "shape-derived table payload only; not measured peak",
                              "dense_exterior_assembly_seconds": perf_counter() - started})
    result.update(assembly_seconds=result["metadata"]["dense_exterior_assembly_seconds"],
                  allocation_shape=list(exterior.shape), allocation_payload_bytes=int(exterior.nbytes))
    margin = _float_margin(matrix.tolist(), degrees)
    result.update(margin=margin, status="diagnostic_only", verification_status="not_verified", guarantee="none")
    result["diagnostics"].update(margin=margin, positive_screen=None if margin is None else margin > 0,
                                 status="unvalidated")
    return result
