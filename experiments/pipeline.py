"""Interfaces shared by the frozen experiment runner and verification tests."""
from __future__ import annotations

from fractions import Fraction
import time

import networkx as nx
import numpy as np
from scipy import sparse

from degree_contraction import modularity, quotient_adjacency


def graph_adjacency(graph: nx.Graph):
    return sparse.csr_matrix(nx.to_scipy_sparse_array(
        graph, nodelist=range(len(graph)), weight="weight", format="csr", dtype=float))


def networkx_quotient(adjacency):
    """NetworkX counts loop weights twice; core A' already doubles internal mass."""
    a = sparse.csr_matrix(adjacency)
    graph = nx.Graph()
    graph.add_nodes_from(range(a.shape[0]))
    for u in range(a.shape[0]):
        for pos in range(a.indptr[u], a.indptr[u + 1]):
            v = int(a.indices[pos])
            if v >= u:
                weight = float(a.data[pos]) / (2 if u == v else 1)
                if weight:
                    graph.add_edge(u, v, weight=weight)
    return graph


def labels_from_partition(partition, n):
    labels = np.empty(n, dtype=np.int64)
    for label, community in enumerate(partition):
        labels[list(community)] = label
    return labels


def partition_from_labels(labels):
    groups = {}
    for u, label in enumerate(labels):
        groups.setdefault(int(label), set()).add(u)
    return list(groups.values())


def strict_edge_groups(n, edges):
    """Only use for strong published pair decisions, or proved-compatible twins."""
    parent = list(range(n))
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    for edge in edges:
        u, v = edge["u"], edge["v"]
        parent[find(v)] = find(u)
    groups = {}
    for u in range(n):
        groups.setdefault(find(u), []).append(u)
    return [group for group in groups.values() if len(group) > 1]


def reduction_summary(adjacency, groups, *, largest_component=None):
    quotient = quotient_adjacency(adjacency, groups)
    return quotient, summarize_quotient(adjacency, quotient, largest_component=largest_component)


def summarize_quotient(adjacency, quotient, *, largest_component=None):
    n = adjacency.shape[0]
    a = quotient.adjacency
    off_diagonal_edges = (a.nnz - np.count_nonzero(a.diagonal())) // 2
    original_edges = (adjacency.nnz - np.count_nonzero(adjacency.diagonal())) // 2
    result = {"original_vertices": n, "remaining_vertices": a.shape[0],
              "removed_vertices": n - a.shape[0], "removed_fraction": (n - a.shape[0]) / n,
              "original_off_diagonal_edges": int(original_edges),
              "remaining_off_diagonal_edges": int(off_diagonal_edges),
              "removed_off_diagonal_edges": int(original_edges - off_diagonal_edges),
              "merge_groups": [list(g) for g in quotient.groups if len(g) > 1]}
    if largest_component is not None:
        members = set(largest_component)
        removed = sum(max(0, sum(u in members for u in group) - 1) for group in quotient.groups)
        result["largest_component_under_original_objective"] = {
            "vertices": len(members), "removed_vertices": removed,
            "removed_fraction": removed / len(members) if members else 0.0}
    return result


def solve_louvain(graph, adjacency, gamma, seed):
    started = time.perf_counter()
    partition = nx.community.louvain_communities(graph, weight="weight",
                                               resolution=float(gamma), seed=seed)
    seconds = time.perf_counter() - started
    label_started = time.perf_counter()
    labels = labels_from_partition(partition, len(graph))
    label_seconds = time.perf_counter() - label_started
    evaluation_start = time.perf_counter()
    q_nx = nx.community.modularity(graph, partition, weight="weight", resolution=float(gamma))
    q_core = modularity(adjacency, labels, Fraction(str(gamma)))
    if abs(q_core - q_nx) > 1e-10:
        raise ArithmeticError("Core/NetworkX objective convention mismatch")
    return labels, {"seed": seed, "solver_seconds": seconds,
                    "label_conversion_seconds": label_seconds,
                    "objective_evaluation_seconds": time.perf_counter() - evaluation_start,
                    "modularity": q_core, "communities": len(partition)}


def discovery_quotient_labels(discovery_labels, quotient):
    labels = []
    for group in quotient.groups:
        values = {int(discovery_labels[u]) for u in group}
        if len(values) != 1:
            raise ValueError("Discovery incumbent is not feasible on this quotient")
        labels.append(values.pop())
    return np.asarray(labels, dtype=np.int64)
