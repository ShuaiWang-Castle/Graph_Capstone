"""Sparse exterior assembly and a rational degree-weighted block certificate.

The eigenvalue is a floating diagnostic. Acceptance comes exclusively from
exact rational elimination, for the values represented by the supplied CSR.
Diagonal adjacency entries contribute to full degrees, but cancel from the
internal Laplacian. Thus quotient diagonals retain doubled internal edge mass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import math
from numbers import Integral, Real
from time import perf_counter
from typing import Iterable, Literal

import numpy as np
from scipy import sparse


def _fraction(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Integral):
        return Fraction(int(value))
    if isinstance(value, Real):
        value = float(value)
        if math.isfinite(value):
            return Fraction.from_float(value)
    raise ValueError("weights and resolution must be finite real numbers")


@dataclass(frozen=True, slots=True)
class PreparedGraph:
    """A copied, read-only CSR with cached full degrees and exact degree sums."""

    adjacency: sparse.csr_matrix
    degrees: np.ndarray
    total_degree: float
    fingerprint: str
    _rational_degrees: tuple[Fraction, ...] | None = field(default=None, repr=False)
    _rational_total: Fraction | None = field(default=None, repr=False)

    def exact_degrees(self) -> tuple[tuple[Fraction, ...], Fraction]:
        cached = self._rational_degrees
        if cached is None:
            a = self.adjacency
            cached = tuple(
                sum((_fraction(value) for value in a.data[a.indptr[u]:a.indptr[u + 1]]), Fraction())
                for u in range(a.shape[0])
            )
            object.__setattr__(self, "_rational_degrees", cached)
            object.__setattr__(self, "_rational_total", sum(cached, Fraction()))
        assert self._rational_total is not None
        return cached, self._rational_total


def prepare_graph(adjacency: sparse.csr_matrix | PreparedGraph) -> PreparedGraph:
    """Validate a symmetric nonnegative CSR and copy it without changing weights.

    Unsorted columns and explicit zeros are allowed. Duplicate entries must be
    combined by the caller: that operation can round, so this function never
    silently changes the exact graph it will subsequently certify.
    """
    if isinstance(adjacency, PreparedGraph):
        return adjacency
    if not sparse.issparse(adjacency) or adjacency.format != "csr":
        raise TypeError("adjacency must be a scipy CSR matrix or CSR array")
    if len(adjacency.shape) != 2 or adjacency.shape[0] != adjacency.shape[1]:
        raise ValueError("adjacency must be square")
    if adjacency.dtype.kind not in "biuf" or (
        adjacency.dtype.kind == "f" and adjacency.dtype.itemsize > 8
    ):
        raise ValueError("adjacency must contain real integers or binary floats up to float64")
    if not np.isfinite(adjacency.data).all() or (adjacency.data < 0).any():
        raise ValueError("adjacency weights must be finite and nonnegative")
    a = sparse.csr_matrix(adjacency, copy=True)
    a.sort_indices()
    if not a.has_canonical_format:
        raise ValueError("duplicate CSR entries must be combined explicitly before certification")
    if a.dtype.kind in "biu":
        converted = a.data.astype(np.float64)
        if any(int(source) != int(target) for source, target in zip(a.data, converted)):
            raise ValueError("integer weights must be represented exactly in float64")
    a = a.astype(np.float64)
    a.eliminate_zeros()
    if (a != a.T).nnz:
        raise ValueError("adjacency must be exactly symmetric")
    degrees = np.asarray(a.sum(axis=1)).ravel()
    total = float(math.fsum(map(float, degrees)))
    if not np.isfinite(degrees).all() or not math.isfinite(total):
        raise ValueError("degree sums must be finite in floating arithmetic")
    digest = hashlib.sha256()
    digest.update(np.asarray(a.shape, dtype="<i8").tobytes())
    digest.update(np.asarray(a.indptr, dtype="<i8").tobytes())
    digest.update(np.asarray(a.indices, dtype="<i8").tobytes())
    digest.update(np.asarray(a.data, dtype="<f8").tobytes())
    for values in (a.data, a.indices, a.indptr, degrees):
        values.flags.writeable = False
    return PreparedGraph(a, degrees, total, digest.hexdigest())


def _block_vertices(block: Iterable[int], n: int) -> tuple[int, ...]:
    vertices = tuple(block)
    if len(vertices) < 2:
        raise ValueError("a candidate block must contain at least two vertices")
    if any(not isinstance(u, Integral) for u in vertices):
        raise ValueError("block vertices must be integer indices")
    vertices = tuple(int(u) for u in vertices)
    if len(set(vertices)) != len(vertices):
        raise ValueError("a candidate block cannot contain duplicate vertices")
    if any(u < 0 or u >= n for u in vertices):
        raise ValueError("a candidate vertex is outside the adjacency")
    return vertices


def _median_with_zeros(values: list, size: int):
    """Ordinary median of nonnegative positive support and implicit zeros."""
    zeros = size - len(values)
    # A column below half support has a zero median; skip sorting it.
    if len(values) * 2 < size:
        return 0
    values = sorted(values)
    def order(rank: int):
        return 0 if rank < zeros else values[rank - zeros]
    if size % 2:
        return order(size // 2)
    return (order(size // 2 - 1) + order(size // 2)) / 2


@dataclass(frozen=True, slots=True)
class ExteriorDeviation:
    block: tuple[int, ...]
    delta: np.ndarray
    weighted_mean_delta: float
    center_nodes: np.ndarray
    center_values: np.ndarray
    exterior_incidences: int
    metadata: dict


def sparse_exterior_deviation(
    adjacency: sparse.csr_matrix | PreparedGraph, block: Iterable[int]
) -> ExteriorDeviation:
    """Compute normalized exterior-row median deviations without an n-by-k array.

    For c >= 0, delta_u = sum_out A_uw/d_u + sum_w c_w
    - 2 sum_out min(A_uw/d_u, c_w). Sorting is per touched exterior column.
    A nonzero median has at least k/2 incidences. Floating cancellation is
    recorded and a negative diagnostic delta is recomputed exactly for the
    rounded normalized rows; this repair does not constitute certification.
    """
    graph = prepare_graph(adjacency)
    a = graph.adjacency
    vertices = _block_vertices(block, a.shape[0])
    degree = graph.degrees[list(vertices)]
    if (degree <= 0).any():
        raise ValueError("zero-degree vertices are excluded from normalized candidate blocks")
    inside = set(vertices)
    columns: dict[int, list[float]] = {}
    rows: list[list[tuple[int, float]]] = []
    for i, u in enumerate(vertices):
        row = []
        for pos in range(a.indptr[u], a.indptr[u + 1]):
            w = int(a.indices[pos])
            if w not in inside:
                value = float(a.data[pos] / degree[i])
                row.append((w, value))
                columns.setdefault(w, []).append(value)
        rows.append(row)
    centers = {}
    for w, values in columns.items():
        center = float(_median_with_zeros(values, len(vertices)))
        if center:
            centers[w] = center
    center_total = math.fsum(centers.values())
    delta_values = []
    repairs = []
    exact_center_total = None
    for i, row in enumerate(rows):
        normalized_mass = math.fsum(value for _, value in row)
        overlap = math.fsum(min(value, centers.get(w, 0.0)) for w, value in row)
        value = math.fsum((normalized_mass, center_total, -2 * overlap))
        if value < 0:
            # Diagnose/correct cancellation without claiming an error bound for
            # the original matrix. The rational acceptance path is independent.
            if exact_center_total is None:
                exact_center_total = sum(map(_fraction, centers.values()), Fraction())
            exact_value = (
                sum((_fraction(x) for _, x in row), Fraction()) + exact_center_total
                - 2 * sum((_fraction(min(x, centers.get(w, 0.0))) for w, x in row), Fraction())
            )
            assert exact_value >= 0
            corrected = float(exact_value)
            repairs.append({"position": i, "raw_delta": value, "corrected_delta": corrected,
                            "absolute_correction": abs(corrected - value)})
            value = corrected
        delta_values.append(value)
    delta = np.asarray(delta_values, dtype=float)
    volume = float(math.fsum(map(float, degree)))
    mean = math.fsum(float(d) * float(v) for d, v in zip(degree, delta)) / volume
    nodes = np.asarray(sorted(centers), dtype=np.int64)
    center_values = np.asarray([centers[int(w)] for w in nodes], dtype=float)
    for values in (delta, nodes, center_values):
        values.flags.writeable = False
    incidences = sum(map(len, rows))
    return ExteriorDeviation(
        vertices, delta, mean, nodes, center_values, incidences,
        {"arithmetic": "floating diagnostic", "touched_exterior_columns": len(columns),
         "nonzero_center_columns": len(centers), "negative_delta_repairs": repairs,
         "center": "unweighted normalized-row median including implicit zeros",
         "center_support_bound_holds": len(vertices) * len(centers) <= 2 * incidences},
    )


def _rational_deviation(graph: PreparedGraph, vertices: tuple[int, ...]):
    degree, total = graph.exact_degrees()
    dk = [degree[u] for u in vertices]
    volume = sum(dk, Fraction())
    inside = set(vertices)
    columns: dict[int, list[Fraction]] = {}
    rows = []
    a = graph.adjacency
    for i, u in enumerate(vertices):
        row = []
        for pos in range(a.indptr[u], a.indptr[u + 1]):
            w = int(a.indices[pos])
            if w not in inside:
                value = _fraction(a.data[pos]) / dk[i]
                row.append((w, value))
                columns.setdefault(w, []).append(value)
        rows.append(row)
    centers = {w: _median_with_zeros(values, len(vertices)) for w, values in columns.items()}
    centers = {w: value for w, value in centers.items() if value}
    center_total = sum(centers.values(), Fraction())
    delta = [sum((x for _, x in row), Fraction()) + center_total
             - 2 * sum((min(x, centers.get(w, Fraction())) for w, x in row), Fraction())
             for row in rows]
    assert all(value >= 0 for value in delta)
    mean = sum((d * value for d, value in zip(dk, delta)), Fraction()) / volume
    return dk, total, volume, delta, mean


def _exact_projected_matrix(graph, vertices, gamma):
    dk, total, volume, delta, mean = _rational_deviation(graph, vertices)
    k = len(vertices)
    location = {u: i for i, u in enumerate(vertices)}
    matrix = [[Fraction() for _ in vertices] for _ in vertices]
    a = graph.adjacency
    for i, u in enumerate(vertices):
        internal_degree = Fraction()
        for pos in range(a.indptr[u], a.indptr[u + 1]):
            j = location.get(int(a.indices[pos]))
            if j is not None and j != i:
                weight = _fraction(a.data[pos])
                matrix[i][j] = -weight
                internal_degree += weight
        matrix[i][i] = internal_degree - dk[i] * (delta[i] + mean + gamma * volume / total)
    pivot = max(range(k), key=lambda i: dk[i])
    others = [i for i in range(k) if i != pivot]
    ratios = [dk[i] / dk[pivot] for i in others]
    projected = [[matrix[i][j] - ri * matrix[pivot][j] - rj * matrix[i][pivot]
                  + ri * rj * matrix[pivot][pivot]
                  for j, rj in zip(others, ratios)] for i, ri in zip(others, ratios)]
    return projected, pivot, delta, mean


def _exact_psd(matrix: list[list[Fraction]]) -> tuple[bool, bool, dict]:
    """Rational symmetric LDL elimination, including zero pivots for PSD.

    A PSD matrix with zero diagonal has a zero row. A positive pivot reduces
    PSD/PD to its exact Schur complement. These facts justify every decision.
    """
    a = [row.copy() for row in matrix]
    positive = zero = 0
    for i in range(len(a)):
        pivot = a[i][i]
        if pivot < 0:
            return False, False, {"positive_pivots": positive, "zero_pivots": zero,
                                  "obstruction": "negative Schur pivot", "position": i}
        if pivot == 0:
            if any(a[i][j] != 0 for j in range(i + 1, len(a))):
                return False, False, {"positive_pivots": positive, "zero_pivots": zero,
                                      "obstruction": "zero diagonal with nonzero residual row", "position": i}
            zero += 1
            continue
        positive += 1
        for j in range(i + 1, len(a)):
            if a[j][i] == 0:
                continue
            factor = a[j][i] / pivot
            for h in range(j, len(a)):
                a[j][h] -= factor * a[i][h]
                a[h][j] = a[j][h]
    return True, zero == 0, {"positive_pivots": positive, "zero_pivots": zero,
                             "obstruction": None}


@dataclass(frozen=True, slots=True)
class BlockCertificate:
    block: tuple[int, ...]
    gamma: float
    volume: float
    total_degree: float
    delta: np.ndarray | None
    weighted_mean_delta: float | None
    restricted_eigenvalue: float | None
    margin: float | None
    gamma_max: float | None
    certified: bool
    strict: bool
    verification_status: str
    metadata: dict

    @property
    def guarantee(self) -> str:
        if not self.certified:
            return "none"
        return "every optimum fuses the block" if self.strict else "a fused optimum exists"

    def to_dict(self) -> dict:
        return {
            "block": list(self.block), "size": len(self.block), "gamma": self.gamma,
            "volume": self.volume, "total_degree": self.total_degree,
            "delta": None if self.delta is None else self.delta.tolist(),
            "weighted_mean_delta": self.weighted_mean_delta,
            "restricted_eigenvalue": self.restricted_eigenvalue, "margin": self.margin,
            "gamma_max": self.gamma_max, "certified": self.certified, "strict": self.strict,
            "verification_status": self.verification_status, "guarantee": self.guarantee,
            "metadata": self.metadata,
        }


def certify_block(
    adjacency: sparse.csr_matrix | PreparedGraph,
    block: Iterable[int],
    gamma: float | Fraction = 1.0,
    *,
    verification: Literal["auto", "exact", "none"] = "auto",
    exact_max_size: int = 64,
    dense_max_size: int = 256,
    screen_tolerance: float = 1e-10,
) -> BlockCertificate:
    """Screen a block numerically and, when requested, verify it rationally.

    ``auto`` verifies comfortably positive margins; ``exact`` also checks weak
    boundaries and float-screen rejections. A size limit or negative diagnostic
    screen yields no certificate. No floating margin ever sets ``certified``.
    The resolution is interpreted exactly when supplied as Fraction, otherwise
    as its represented binary floating value. All candidate degrees must be >0.
    """
    if verification not in {"auto", "exact", "none"}:
        raise ValueError("verification must be 'auto', 'exact', or 'none'")
    if exact_max_size < 2 or dense_max_size < 2 or not math.isfinite(screen_tolerance) or screen_tolerance < 0:
        raise ValueError("size limits must be >=2 and screen_tolerance finite and nonnegative")
    graph = prepare_graph(adjacency)
    vertices = _block_vertices(block, graph.adjacency.shape[0])
    gamma_exact = _fraction(gamma)
    gamma_float = float(gamma_exact)
    if gamma_exact < 0 or not math.isfinite(gamma_float):
        raise ValueError("resolution gamma must be finite and nonnegative")
    dk = graph.degrees[list(vertices)]
    volume = float(math.fsum(map(float, dk)))
    metadata = {"graph_fingerprint": graph.fingerprint, "gamma_exact": str(gamma_exact),
                "diagnostic_arithmetic": "float64, unvalidated eigenvalue",
                "acceptance_arithmetic": "exact rational LDL" if verification != "none" else "not requested",
                "block_degree_source": "full graph including adjacency diagonal"}
    if (dk <= 0).any():
        metadata["excluded_vertices"] = [u for u, d in zip(vertices, dk) if d <= 0]
        return BlockCertificate(vertices, gamma_float, volume, graph.total_degree, None, None,
                                None, None, None, False, False, "zero_degree_excluded", metadata)
    start = perf_counter()
    deviation = sparse_exterior_deviation(graph, vertices)
    metadata["exterior_assembly_seconds"] = perf_counter() - start
    metadata.update(deviation.metadata)
    metadata["exterior_incidences"] = deviation.exterior_incidences
    eigenvalue = margin = gamma_max = None
    if len(vertices) <= dense_max_size:
        start = perf_counter()
        internal = graph.adjacency[list(vertices), :][:, list(vertices)].toarray()
        np.fill_diagonal(internal, 0.0)
        laplacian = np.diag(internal.sum(axis=1)) - internal
        inv_sqrt = 1 / np.sqrt(dk)
        matrix = inv_sqrt[:, None] * laplacian * inv_sqrt[None, :]
        matrix -= np.diag(deviation.delta) + deviation.weighted_mean_delta * np.eye(len(vertices))
        # Householder columns other than the pivot give an orthonormal basis of
        # sqrt(d)-perp, with a stable sign choice for positive degrees.
        pivot = int(np.argmax(dk))
        vector = np.sqrt(dk / volume)
        vector[pivot] += 1
        householder = np.eye(len(vertices)) - (2 / (vector @ vector)) * np.outer(vector, vector)
        q = np.delete(householder, pivot, axis=1)
        reduced = q.T @ matrix @ q
        reduced = (reduced + reduced.T) / 2
        eigenvalue = float(np.linalg.eigvalsh(reduced)[0])
        threshold = gamma_float * (volume / graph.total_degree)
        margin = eigenvalue - threshold
        gamma_max = eigenvalue * graph.total_degree / volume
        metadata["dense_eigensolve_seconds"] = perf_counter() - start
        metadata["diagnostic_matrix_norm"] = float(np.linalg.norm(reduced, ord=np.inf))
    verified = strict = False
    status = "not_requested"
    if verification != "none":
        if len(vertices) > exact_max_size:
            status = "exact_size_limit"
        elif verification == "auto" and (
            margin is None or margin <= screen_tolerance * max(1.0, metadata["diagnostic_matrix_norm"])
        ):
            status = "auto_screened_without_verification"
        else:
            start = perf_counter()
            projected, pivot, exact_delta, exact_mean = _exact_projected_matrix(graph, vertices, gamma_exact)
            verified, strict, elimination = _exact_psd(projected)
            status = ("verified_positive_definite" if strict else "verified_positive_semidefinite") if verified else "failed_exact_psd"
            metadata["exact_verification_seconds"] = perf_counter() - start
            metadata["exact_elimination"] = elimination
            metadata["exact_basis_pivot_vertex"] = vertices[pivot]
            metadata["exact_delta_float_difference_max"] = max(abs(float(x) - y) for x, y in zip(exact_delta, deviation.delta))
            metadata["exact_weighted_mean_delta_float_difference"] = abs(float(exact_mean) - deviation.weighted_mean_delta)
    return BlockCertificate(vertices, gamma_float, volume, graph.total_degree,
                            deviation.delta, deviation.weighted_mean_delta, eigenvalue,
                            margin, gamma_max, verified, strict, status, metadata)
