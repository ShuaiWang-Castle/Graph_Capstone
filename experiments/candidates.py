"""Certificate-independent candidate forest for fair supplied-block comparisons."""
from __future__ import annotations

from dataclasses import dataclass
import time

import networkx as nx
import numpy as np
from scipy.sparse import csgraph, diags
from scipy.sparse.linalg import ArpackNoConvergence, eigsh


@dataclass
class CandidateBank:
    blocks: list[tuple[int, ...]]
    discovery_labels: np.ndarray
    proposal_seconds: float
    refinement_seconds: float
    spectral_splits: int
    component_splits: int
    fallback_splits: int
    seed: int


def candidate_bank(graph: nx.Graph, *, seed: int = 0, resolution: float = 1.0,
                   minimum_size: int = 2) -> CandidateBank:
    """Louvain proposals plus a fixed full bisection forest, before any checks.

    Every method receives this same bank. Blocks are nested or disjoint. No
    certificate outcome changes the bank. Graph labels must be 0..n-1.
    """
    if set(graph) != set(range(len(graph))):
        raise ValueError("Relabel graph to consecutive integer nodes first.")
    if nx.number_of_selfloops(graph):
        raise ValueError("Proposal graph must be the original loopless input.")
    started = time.perf_counter()
    proposals = nx.community.louvain_communities(graph, resolution=resolution, seed=seed)
    discovery_labels = np.empty(len(graph), dtype=np.int64)
    for label, community in enumerate(proposals):
        discovery_labels[list(community)] = label
    proposal_seconds = time.perf_counter() - started
    started = time.perf_counter()
    A = nx.to_scipy_sparse_array(graph, nodelist=range(len(graph)), weight="weight", format="csr", dtype=float)
    degrees = np.asarray(A.sum(axis=1)).ravel()
    pending = [tuple(sorted(block)) for block in sorted(proposals, key=lambda x: min(x), reverse=True)]
    blocks = []
    spectral_splits = component_splits = fallback_splits = 0
    while pending:
        block = pending.pop()
        positive = tuple(u for u in block if degrees[u] > 0)
        if len(positive) < minimum_size:
            continue
        block = positive
        blocks.append(block)
        if len(block) < 2 * minimum_size:
            continue
        AK = A[list(block), :][:, list(block)]
        count, components = csgraph.connected_components(AK, directed=False)
        if count > 1:
            children = [tuple(block[i] for i in np.flatnonzero(components == label)) for label in range(count)]
            component_splits += 1
        else:
            internal_degree = np.asarray(AK.sum(axis=1)).ravel()
            inverse_sqrt = 1 / np.sqrt(degrees[list(block)])
            normalized = diags(inverse_sqrt) @ (diags(internal_degree) - AK) @ diags(inverse_sqrt)
            try:
                if len(block) <= 64:
                    _, vectors = np.linalg.eigh(normalized.toarray())
                    vector = vectors[:, 1]
                else:
                    # A fixed initial vector makes the candidate construction
                    # reproducible without changing numerical acceptance.
                    initial = np.linspace(1, 2, len(block))
                    _, vectors = eigsh(normalized, k=2, which="SM", v0=initial, tol=1e-7, maxiter=10000)
                    vector = vectors[:, 1]
                nonzero = np.flatnonzero(np.abs(vector) > 1e-12)
                if len(nonzero) and vector[nonzero[0]] < 0:
                    vector = -vector
                ordering = np.lexsort((np.asarray(block), vector * inverse_sqrt))
                spectral_splits += 1
            except (ArpackNoConvergence, np.linalg.LinAlgError):
                ordering = np.arange(len(block))
                fallback_splits += 1
            middle = len(block) // 2
            children = [tuple(sorted(block[i] for i in ordering[:middle])), tuple(sorted(block[i] for i in ordering[middle:]))]
        pending.extend(sorted(children, key=lambda x: min(x), reverse=True))
    return CandidateBank(blocks, discovery_labels, proposal_seconds, time.perf_counter() - started,
                         spectral_splits, component_splits, fallback_splits, seed)
