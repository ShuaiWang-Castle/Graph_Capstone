"""Exact represented sparse modularity with Python integer accumulation."""
from __future__ import annotations

from fractions import Fraction
import math

import numpy as np
from scipy import sparse

from .contracts import IntegerObjectiveCache, content_hash, groups_from_membership, integer_labels


def prepare_integer_objective(adjacency):
    if not sparse.issparse(adjacency) or adjacency.format != "csr":
        raise TypeError("objective input must be canonical CSR")
    if len(adjacency.shape) != 2 or adjacency.shape[0] != adjacency.shape[1] or adjacency.shape[0] < 1:
        raise ValueError("objective input must be a nonempty square graph")
    if not adjacency.has_canonical_format or not adjacency.has_sorted_indices:
        raise ValueError("objective CSR must have sorted unique column entries")
    if adjacency.dtype.kind not in "biuf" or adjacency.dtype.itemsize > 8:
        raise ValueError("objective weights must be represented real integers up to float64")
    weights = []
    for value in adjacency.data:
        if not math.isfinite(float(value)) or value < 0 or int(value) != value:
            raise ValueError("objective weights must be finite nonnegative represented integers")
        integer = int(value)
        if int(float(integer)) != integer or float(integer) != value:
            raise ArithmeticError("integer objective weight does not round-trip through float64")
        weights.append(integer)
    a = sparse.csr_matrix(adjacency, copy=True)
    rows = tuple(tuple((int(a.indices[p]), weights[p]) for p in range(a.indptr[u], a.indptr[u + 1])
                       if weights[p]) for u in range(a.shape[0]))
    row_maps = tuple(dict(row) for row in rows)
    if any(row_maps[v].get(u, 0) != weight for u, row in enumerate(rows) for v, weight in row):
        raise ValueError("objective graph must be exactly symmetric")
    degrees = tuple(sum(weight for _, weight in row) for row in rows)
    total = sum(degrees)
    if total <= 0:
        raise ValueError("objective graph must have positive total volume")
    for values in (a.data, a.indices, a.indptr):
        values.flags.writeable = False
    digest = content_hash({"n": len(rows), "rows": rows, "degrees": degrees, "S": total})
    return IntegerObjectiveCache(a, rows, tuple(weights), degrees, total, digest)


def integer_modularity(cache, labels, gamma):
    labels = integer_labels(labels, cache.n)
    if not isinstance(gamma, Fraction) or gamma < 0:
        raise ValueError("integer evaluator requires an exact nonnegative Fraction gamma")
    within = 0
    volumes = {}
    for u, row in enumerate(cache.rows):
        label = labels[u]
        volumes[label] = volumes.get(label, 0) + cache.degrees[u]
        within += sum(weight for v, weight in row if labels[v] == label)
    squares = sum(volume * volume for volume in volumes.values())
    p, q, total = int(gamma.numerator), int(gamma.denominator), cache.total
    return Fraction(q * total * within - p * squares, q * total * total)


def aggregate_integer_rows(cache, membership, n_current=None):
    membership = integer_labels(membership, cache.n)
    groups = groups_from_membership(membership, n_current)
    rows = [{} for _ in groups]
    for u, row in enumerate(cache.rows):
        target = rows[membership[u]]
        for v, weight in row:
            column = membership[v]
            target[column] = target.get(column, 0) + weight
    return tuple(tuple(sorted(row.items())) for row in rows)


def validate_quotient(original_cache, adjacency, membership):
    """Compare all represented entries, loops, degree sums and S to direct integers."""
    actual = prepare_integer_objective(adjacency)
    groups = groups_from_membership(membership, actual.n)
    expected = aggregate_integer_rows(original_cache, membership, actual.n)
    if expected != actual.rows:
        raise ArithmeticError("quotient differs from direct exact original aggregation")
    expected_degrees = tuple(sum(original_cache.degrees[u] for u in group) for group in groups)
    if actual.degrees != expected_degrees or actual.total != original_cache.total:
        raise ArithmeticError("quotient changed original full degree/volume identities")
    return actual, {"exact_original_aggregation_verified": True, "exact_symmetry_verified": True,
                    "all_diagonal_entries_verified": True, "degree_and_total_mass_identity_verified": True,
                    "weights_exactly_round_tripped": True, "S_exact": actual.total,
                    "degrees_exact": list(actual.degrees), "content_sha256": actual.content_sha256}
