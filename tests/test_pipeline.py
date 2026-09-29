from fractions import Fraction

import networkx as nx
import numpy as np

from degree_contraction import modularity_exact, quotient_adjacency
from experiments.pipeline import graph_adjacency, networkx_quotient, partition_from_labels, solve_louvain


def test_networkx_loop_interface_matches_exact_lifted_modularity():
    graph = nx.Graph()
    graph.add_weighted_edges_from([(0, 1, 3), (1, 2, 2), (2, 3, 1), (0, 3, 2), (3, 4, 4)])
    a = graph_adjacency(graph)
    quotient = quotient_adjacency(a, [(0, 1), (3, 4)])
    q_graph = networkx_quotient(quotient.adjacency)
    assert dict(q_graph.degree(weight="weight")) == dict(enumerate(np.asarray(quotient.adjacency.sum(axis=1)).ravel()))
    for labels in ([0, 1, 2], [0, 0, 1], [0, 0, 0], [0, 1, 0]):
        for gamma in (Fraction(1, 2), Fraction(1), Fraction(2)):
            expected = modularity_exact(a, quotient.lift_labels(labels), gamma)
            assert expected == modularity_exact(quotient.adjacency, labels, gamma)
            actual = nx.community.modularity(q_graph, partition_from_labels(labels), weight="weight", resolution=float(gamma))
            assert abs(float(expected) - actual) < 1e-12
    _, result = solve_louvain(q_graph, quotient.adjacency, Fraction(1), seed=10)
    assert np.isfinite(result["modularity"])
