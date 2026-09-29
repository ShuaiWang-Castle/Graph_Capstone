"""Degree-preserving sparse quotient construction and label lifting."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from numbers import Integral
from typing import Iterable, Sequence

import numpy as np
from scipy import sparse

from .certificate import BlockCertificate, PreparedGraph, _fraction, prepare_graph


@dataclass(frozen=True, slots=True)
class QuotientGraph:
    adjacency: sparse.csr_matrix
    membership: np.ndarray
    groups: tuple[tuple[int, ...], ...]
    aggregation: sparse.csr_matrix
    metadata: dict

    def lift_labels(self, quotient_labels: Sequence) -> np.ndarray:
        return lift_labels(quotient_labels, self.membership)


def quotient_adjacency(
    adjacency: sparse.csr_matrix | PreparedGraph,
    groups: Iterable[Iterable[int]],
    *,
    require_exact: bool = True,
) -> QuotientGraph:
    """Return A'=R.T A R; omitted vertices remain singleton groups.

    R has one 1 per original vertex. Thus diagonal quotient entries are doubled
    internal edge mass, and full quotient degrees are aggregated full degrees.
    Exact Fraction sums verify the output CSR represents every aggregate
    exactly. ``require_exact=False`` permits a rounded diagnostic quotient.
    """
    graph = prepare_graph(adjacency)
    a = graph.adjacency
    n = a.shape[0]
    result_groups = []
    used = set()
    for supplied in groups:
        group = tuple(supplied)
        if not group or any(not isinstance(u, Integral) for u in group):
            raise ValueError("quotient groups must be nonempty integer vertex collections")
        group = tuple(sorted(map(int, group)))
        if len(set(group)) != len(group) or any(u < 0 or u >= n for u in group):
            raise ValueError("quotient groups contain duplicate or out-of-range vertices")
        if used.intersection(group):
            raise ValueError("quotient groups must be disjoint")
        used.update(group)
        result_groups.append(group)
    result_groups.extend((u,) for u in range(n) if u not in used)
    groups_tuple = tuple(result_groups)
    membership = np.empty(n, dtype=np.int64)
    for index, group in enumerate(groups_tuple):
        membership[list(group)] = index
    aggregation = sparse.csr_matrix((np.ones(n), (np.arange(n), membership)), shape=(n, len(groups_tuple)))
    quotient = (aggregation.T @ a @ aggregation).tocsr()
    quotient.sort_indices()
    exact_values: dict[tuple[int, int], Fraction] = {}
    for u in range(n):
        for pos in range(a.indptr[u], a.indptr[u + 1]):
            key = (int(membership[u]), int(membership[a.indices[pos]]))
            exact_values[key] = exact_values.get(key, Fraction()) + _fraction(a.data[pos])
    rounded = []
    for u in range(quotient.shape[0]):
        for pos in range(quotient.indptr[u], quotient.indptr[u + 1]):
            key = (u, int(quotient.indices[pos]))
            error = _fraction(quotient.data[pos]) - exact_values[key]
            if error:
                rounded.append(error)
    if rounded and require_exact:
        raise ArithmeticError("quotient aggregation rounded exact weights; use an exact-representable graph or require_exact=False for diagnostics")
    metadata = {"quotient_identity": "A_quotient = R.T A R", "diagonal_convention": "doubled internal edge mass",
                "weights_exactly_preserved": not rounded, "rounded_aggregate_count": len(rounded),
                "max_absolute_aggregate_rounding": max(map(lambda x: float(abs(x)), rounded), default=0.0),
                "original_graph_fingerprint": graph.fingerprint}
    if not rounded:
        degree, total = graph.exact_degrees()
        quotient_degree = [Fraction() for _ in groups_tuple]
        for (u, _), value in exact_values.items():
            quotient_degree[u] += value
        assert all(quotient_degree[i] == sum((degree[u] for u in group), Fraction())
                   for i, group in enumerate(groups_tuple))
        assert sum(quotient_degree, Fraction()) == total
        metadata["degree_and_total_mass_identity_verified"] = True
    else:
        metadata["degree_and_total_mass_identity_verified"] = False
    for values in (membership, quotient.data, quotient.indices, quotient.indptr):
        values.flags.writeable = False
    return QuotientGraph(quotient, membership, groups_tuple, aggregation, metadata)


def lift_labels(quotient_labels: Sequence, membership: Sequence[int]) -> np.ndarray:
    """Lift any quotient partition through the original-vertex membership map."""
    labels = np.asarray(quotient_labels)
    indices = np.asarray(membership)
    if labels.ndim != 1 or indices.ndim != 1 or indices.dtype.kind not in "iu":
        raise ValueError("labels and integer membership must be one-dimensional")
    if indices.size and (indices.min() < 0 or indices.max() >= len(labels)):
        raise ValueError("membership indexes outside the quotient labels")
    return labels[indices].copy()


def modularity(
    adjacency: sparse.csr_matrix | PreparedGraph,
    labels: Sequence,
    gamma: float | Fraction = 1.0,
) -> float:
    """Floating full modularity Q, including adjacency diagonal entries."""
    graph = prepare_graph(adjacency)
    labels = tuple(labels)
    if len(labels) != graph.adjacency.shape[0] or graph.total_degree <= 0:
        raise ValueError("labels must cover a graph with positive total degree")
    gamma = _fraction(gamma)
    if gamma < 0:
        raise ValueError("resolution gamma must be nonnegative")
    a = graph.adjacency
    within = 0.0
    volumes = {}
    for u, label in enumerate(labels):
        volumes[label] = volumes.get(label, 0.0) + graph.degrees[u]
        within += sum(float(a.data[pos]) for pos in range(a.indptr[u], a.indptr[u + 1])
                      if labels[int(a.indices[pos])] == label)
    return float(within / graph.total_degree - float(gamma) * sum((v / graph.total_degree) ** 2 for v in volumes.values()))


def modularity_exact(
    adjacency: sparse.csr_matrix | PreparedGraph,
    labels: Sequence,
    gamma: float | Fraction = 1.0,
) -> Fraction:
    """Exact Q for the graph's represented weights and exact/binary gamma."""
    graph = prepare_graph(adjacency)
    labels = tuple(labels)
    degrees, total = graph.exact_degrees()
    if len(labels) != graph.adjacency.shape[0] or total <= 0:
        raise ValueError("labels must cover a graph with positive total degree")
    gamma = _fraction(gamma)
    if gamma < 0:
        raise ValueError("resolution gamma must be nonnegative")
    a = graph.adjacency
    within = Fraction()
    volumes = {}
    for u, label in enumerate(labels):
        volumes[label] = volumes.get(label, Fraction()) + degrees[u]
        within += sum((_fraction(a.data[pos]) for pos in range(a.indptr[u], a.indptr[u + 1])
                       if labels[int(a.indices[pos])] == label), Fraction())
    return within / total - gamma * sum((v * v for v in volumes.values()), Fraction()) / (total * total)


def contract_certified_blocks(
    adjacency: sparse.csr_matrix | PreparedGraph,
    certificates: Iterable[BlockCertificate],
) -> QuotientGraph:
    """Union overlapping exactly verified positive-degree blocks and contract.

    All certificates must refer to this graph and the same exact resolution.
    Positive-degree weak blocks admit compatible fused optimal witnesses; zero
    degrees are never accepted. The returned quotient also verifies every sum.
    """
    graph = prepare_graph(adjacency)
    certificates = tuple(certificates)
    resolutions = {certificate.metadata.get("gamma_exact") for certificate in certificates}
    if len(resolutions) > 1:
        raise ValueError("certificates must have the same exact resolution")
    parent = list(range(graph.adjacency.shape[0]))
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    for certificate in certificates:
        if (not certificate.certified or certificate.verification_status not in {
            "verified_positive_definite", "verified_positive_semidefinite"
        } or certificate.metadata.get("graph_fingerprint") != graph.fingerprint):
            raise ValueError("only exact verified certificates for this graph can be contracted")
        if any(graph.degrees[u] <= 0 for u in certificate.block):
            raise ValueError("certified contraction excludes zero-degree vertices")
        root = find(certificate.block[0])
        for u in certificate.block[1:]:
            parent[find(u)] = root
    components = {}
    for u in range(len(parent)):
        components.setdefault(find(u), []).append(u)
    groups = sorted(components.values(), key=lambda group: group[0])
    quotient = quotient_adjacency(graph, groups)
    quotient.metadata.update({"certified_block_count": len(certificates),
                              "safe_resolution_exact": next(iter(resolutions), None),
                              "optimal_value_preserved": True,
                              "guarantee": "every optimum respects the contracted blocks" if all(c.strict for c in certificates)
                              else "a compatible fused optimum exists"})
    return quotient
