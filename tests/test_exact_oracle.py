"""Oracle definition, ties, exact arithmetic and quotient consistency."""
from fractions import Fraction
from itertools import combinations

import numpy as np
import pytest
from scipy import sparse

from degree_contraction import modularity_exact, quotient_adjacency
from experiments.exact_oracle import (
    PairOracleResult,
    build_c_subinstance,
    check_c_subinstance,
    enumerate_pair_affinities,
    solve_affinities,
    solve_modularity,
    solve_pair_affinities,
)


def adjacency(n, edges):
    dense = np.zeros((n, n))
    for u, v, value in edges:
        dense[u, v] = dense[v, u] = value
    return sparse.csr_matrix(dense)


def partitions(n):
    def visit(labels, maximum):
        if len(labels) == n:
            yield tuple(labels)
        else:
            for label in range(maximum + 2):
                yield from visit(labels + [label], max(label, maximum))
    if n:
        yield from visit([0], 0)
    else:
        yield ()


def test_signed_pair_milp_agrees_with_independent_fraction_enumeration():
    rng = np.random.default_rng(20260929)
    for n in (3, 4, 5):
        for _ in range(4):
            coefficients = tuple(Fraction(int(x), 3) for x in rng.integers(-5, 6, size=n * (n - 1) // 2))
            pairs = tuple(combinations(range(n), 2))
            values = [sum((weight for (u, v), weight in zip(pairs, coefficients)
                           if labels[u] == labels[v]), Fraction()) for labels in partitions(n)]
            exact = enumerate_pair_affinities(n, coefficients)
            assert exact.objective == max(values)
            assert exact.optimum_count == values.count(max(values))
            assert exact.partitions_evaluated == len(values)
            numerical = solve_pair_affinities(n, coefficients, time_limit=10)
            assert numerical.status == 0
            assert numerical.objective == pytest.approx(float(exact.objective))
            assert numerical.upper_bound == pytest.approx(float(exact.objective))
            assert numerical.arithmetic == "numerical MILP diagnostic"
    signed = np.array([[100, -0.5, 2], [-0.5, -4, 2], [2, 2, 7]])
    result = solve_affinities(sparse.csr_matrix(signed))
    assert result.objective == pytest.approx(3.5)
    assert len(set(result.labels)) == 1


def test_isolated_score_equality_recognizes_ties_even_when_witness_is_not_isolated():
    a = adjacency(3, [(0, 1, 1), (0, 2, 1), (1, 2, 1)])
    # Gamma=3/2 makes all ORIGINAL off-diagonal affinities exactly zero.
    result = check_c_subinstance(a, (0, 1), Fraction(3, 2), arithmetic="exact",
                                 reduce_nonpositive_exterior=False)
    assert result.status == "exact_match" and result.certified
    assert result.isolation_score == result.optimum == 0
    assert result.oracle.optimum_count == 5
    # The enumeration returns the first tied optimum, one cluster containing
    # all vertices. Reading isolation off that witness would incorrectly fail.
    assert result.oracle.labels == (0, 0, 0)
    numerical = check_c_subinstance(a, (0, 1), Fraction(3, 2), arithmetic="numerical",
                                    reduce_nonpositive_exterior=False)
    assert numerical.status == "numerical_match" and not numerical.certified


def test_subinstance_uses_global_degrees_and_zeros_exterior_pairs():
    a = adjacency(5, [(0, 1, 1), (2, 3, 1)])
    instance = build_c_subinstance(a, (0, 1), Fraction(1),
                                  reduce_nonpositive_exterior=False)
    weights = dict(zip(combinations(instance.vertices, 2), instance.pair_coefficients))
    assert instance.isolation_score == Fraction(3, 4)
    assert weights[0, 1] == Fraction(3, 4)
    assert weights[0, 2] == Fraction(-1, 4)
    assert weights[2, 3] == 0  # Original outside edge is deliberately zeroed.
    # Recomputing modularity on the retained adjacency would instead give 1/2.
    assert instance.isolation_score != Fraction(1, 2)
    result = check_c_subinstance(a, (0, 1))
    assert result.certified and result.active_vertices == (0, 1)


def test_sparse_nonpositive_exterior_elimination_preserves_exact_optimum():
    rng = np.random.default_rng(918)
    for _ in range(8):
        upper = np.triu(rng.integers(0, 4, size=(6, 6)), 1)
        a = sparse.csr_matrix(upper + upper.T)
        for gamma in (Fraction(0), Fraction(1), Fraction(2)):
            for block in ((0, 1), (1, 2, 3)):
                reduced = check_c_subinstance(a, block, gamma)
                full = check_c_subinstance(a, block, gamma, reduce_nonpositive_exterior=False)
                assert reduced.optimum == full.optimum
                assert reduced.isolation_score == full.isolation_score
                assert reduced.status == full.status
                if full.certified:
                    original_values = [(labels, modularity_exact(a, labels, gamma)) for labels in partitions(6)]
                    maximum = max(value for _, value in original_values)
                    assert any(value == maximum and len({labels[u] for u in block}) == 1
                               and all(labels[w] != labels[block[0]] for w in range(6) if w not in block)
                               for labels, value in original_values)


def test_matching_and_common_hub_families_are_distinguished_by_isolation_score():
    k = 3
    edges = [(u, v, 1) for start in (0, k)
             for u, v in combinations(range(start, start + k), 2)]
    edges += [(u, u + k, 1) for u in range(k)]
    matching = adjacency(2 * k, edges)
    matched = check_c_subinstance(matching, range(k))
    assert matched.status == "exact_match" and matched.oracle.optimum_count > 1
    hub = adjacency(2 * k + 1, edges + [(u, 2 * k, 1) for u in range(k)])
    nonmatch = check_c_subinstance(hub, range(k))
    assert nonmatch.status == "exact_nonmatch" and not nonmatch.certified
    assert nonmatch.optimum > nonmatch.isolation_score
    numerical = check_c_subinstance(hub, range(k), arithmetic="numerical")
    assert numerical.status == "numerical_nonmatch" and not numerical.certified


def test_large_sparse_graph_is_reduced_or_explicitly_unavailable():
    n = 1000
    a = adjacency(n, [(0, 1, 1)] + [(u, u + 1, 1) for u in range(2, n - 1)])
    reduced = check_c_subinstance(a, (0, 1), max_vertices=10)
    assert reduced.status == "exact_match" and reduced.active_vertices == (0, 1)
    assert reduced.metadata["omitted_nonpositive_exterior_vertices"] == n - 2
    unavailable = check_c_subinstance(a, (0, 1), reduce_nonpositive_exterior=False)
    assert unavailable.status == "unavailable" and not unavailable.certified
    star = adjacency(20, [(0, u, 1) for u in range(1, 20)])
    unavailable = check_c_subinstance(star, (0,), Fraction(0), max_vertices=10)
    assert unavailable.status == "unavailable"
    with pytest.raises(ValueError, match="n<=10"):
        enumerate_pair_affinities(11, [])
    with pytest.raises(ValueError, match="n<=150"):
        solve_pair_affinities(151, [])
    with pytest.raises(ValueError, match="n<=150"):
        solve_pair_affinities(151, [], max_vertices=1000)
    largest = enumerate_pair_affinities(10, [Fraction()] * 45)
    assert largest.partitions_evaluated == largest.optimum_count == 115975
    assert largest.objective == 0


def test_timeout_is_unresolved_and_numerical_matches_are_not_certificates(monkeypatch):
    import experiments.exact_oracle as module
    a = adjacency(2, [(0, 1, 1)])
    def timed_out(n, coefficients, time_limit, **kwargs):
        return PairOracleResult(np.zeros(n, dtype=int), 0.5, 1.0, 1, "time limit", 0.5,
                                0.01, 0.02, n * (n - 1) // 2, 0)
    monkeypatch.setattr(module, "solve_pair_affinities", timed_out)
    result = check_c_subinstance(a, (0, 1), arithmetic="numerical")
    assert result.status == "unresolved" and not result.certified
    assert result.optimum is None
    assert result.oracle.objective == 0.5 and result.oracle.upper_bound == 1.0


def test_numerical_modularity_includes_quotient_diagonal_and_single_vertex():
    a = adjacency(4, [(0, 1, 1), (1, 2, 1), (2, 3, 1)])
    quotient = quotient_adjacency(a, [(0, 1), (2, 3)])
    original = solve_modularity(a)
    reduced = solve_modularity(quotient.adjacency)
    assert original.status == reduced.status == 0
    assert original.modularity == pytest.approx(Fraction(1, 6))
    assert reduced.modularity == pytest.approx(original.modularity)
    assert reduced.upper_bound == pytest.approx(original.upper_bound)
    assert modularity_exact(a, quotient.lift_labels(reduced.labels)) == Fraction(1, 6)
    single = quotient_adjacency(a, [range(4)])
    assert solve_modularity(single.adjacency, gamma=Fraction(1, 2)).modularity == pytest.approx(0.5)
    assert solve_modularity(single.adjacency, gamma=2).modularity == pytest.approx(-1)
