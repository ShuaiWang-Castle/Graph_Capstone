"""Exact tiny-graph safety and recursion checks; not benchmark measurements."""
from fractions import Fraction
from itertools import combinations
import json
import random
from types import MappingProxyType

import numpy as np
import pytest
from scipy import sparse

from degree_contraction import modularity_exact, quotient_adjacency
from research.baselines import recursive_cheap as module
from research.baselines.sparse_criteria import PreparedIntegerGraph, prepare_integer_graph


def partitions(n):
    def visit(labels, maximum):
        if len(labels) == n:
            yield tuple(labels)
        else:
            for label in range(maximum + 2):
                yield from visit(labels + [label], max(maximum, label))
    yield from visit([0], 0)


def exact_score(dense, labels, gamma):
    degree = [sum(row) for row in dense]
    volume = sum(degree)
    within = sum(dense[u][v] for u in range(len(dense)) for v in range(len(dense)) if labels[u] == labels[v])
    masses = {}
    for u, label in enumerate(labels):
        masses[label] = masses.get(label, 0) + degree[u]
    return Fraction(within, volume) - gamma * sum(value * value for value in masses.values()) / (volume * volume)


def all_optima(dense, gamma):
    values = [(labels, exact_score(dense, labels, gamma)) for labels in partitions(len(dense))]
    best = max(score for _, score in values)
    return best, [labels for labels, score in values if score == best]


def test_random_weighted_quotients_jointly_preserve_an_optimum():
    rng = random.Random(20260930)
    for sample in range(24):
        n = rng.randrange(3, 7)
        dense = [[0] * n for _ in range(n)]
        for u in range(n):
            dense[u][u] = rng.randrange(3) if sample % 3 == 0 else 0
            for v in range(u + 1, n):
                dense[u][v] = dense[v][u] = rng.randrange(5)
        if not sum(map(sum, dense)):
            continue
        a = sparse.csr_matrix(dense)
        # All supplied subsets are independent of criterion outcomes.
        bank = list(combinations(range(n), 2)) + list(combinations(range(n), 3)) + [tuple(range(n))]
        for gamma in (Fraction(1, 2), Fraction(1), Fraction(2)):
            result = module.recursive_cheap(a, bank, gamma)
            best, optima = all_optima(dense, gamma)
            compatible = [labels for labels in optima
                          if all(len({labels[u] for u in group}) == 1 for group in result['merge_groups'])]
            assert compatible
            if result['strict']:
                assert len(compatible) == len(optima)
            quotient = quotient_adjacency(a, result['merge_groups'])
            q_dense = [[int(x) for x in row] for row in quotient.adjacency.toarray()]
            q_best, q_optima = all_optima(q_dense, gamma)
            assert q_best == best
            assert modularity_exact(a, quotient.lift_labels(q_optima[0]), gamma) == best
            assert result['round_count'] <= n
            for index, round_record in enumerate(result['round_stats']):
                if index:
                    assert round_record['input_vertices'] == result['round_stats'][index - 1]['remaining_vertices']
                if round_record['removed_vertices']:
                    assert round_record['remaining_vertices'] < round_record['input_vertices']
                    assert round_record['exact_degree_total_identity_verified']
                else:
                    assert index == len(result['round_stats']) - 1
            assert result['metadata']['round_limit'] is None
            assert not result['metadata']['cannot_link_constraints']
            json.dumps(result, allow_nan=False)


def test_zero_attraction_twins_and_strict_edges_compose_without_all_optimum_claim():
    a = sparse.csr_matrix([[0, 4, 0, 0], [4, 0, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]])
    gamma = Fraction(5, 2)
    result = module.recursive_cheap(a, [(0, 1), (2, 3), (0, 1, 2, 3)], gamma, include_round_decisions=True)
    assert result['merge_groups'] == [[0, 1], [2, 3]]
    assert result['round_stats'][0]['criteria']['positive_closure_edge']['decision_count'] == 1
    assert result['round_stats'][0]['criteria']['degree_proportional_twins']['compatible_component_count'] == 2
    assert not result['strict']
    _, optimal = all_optima(a.toarray().tolist(), gamma)
    assert any(labels[0] == labels[1] for labels in optimal)
    assert any(labels[0] != labels[1] for labels in optimal)
    assert all(labels[2] == labels[3] for labels in optimal)


def test_mapped_original_bank_dedup_and_current_size_cap_after_merges():
    a = sparse.csr_matrix([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]])
    bank = [(0, 1, 2, 3), (3, 2, 1, 0)]
    before = list(bank)
    result = module.recursive_cheap(a, bank, Fraction(1), max_block_size=2)
    assert bank == before
    first, second = result['round_stats']
    assert first['mapped_bank']['current_size_cap_exclusions'] == 1
    assert first['mapped_bank']['duplicate_nontrivial_blocks_removed'] == 1
    assert second['mapped_bank']['admissible_block_count'] == 1
    assert second['mapped_bank']['current_size_cap_exclusions'] == 0
    assert second['criteria']['bocker_almost_clique']['candidate_count'] == 1


def test_exact_integer_quotient_keeps_loops_and_large_nonfloat_weights():
    weight = 2 ** 54 + 1
    graph = PreparedIntegerGraph(
        tuple(MappingProxyType(row) for row in ({0: 3, 1: weight, 2: 7},
                                               {0: weight, 1: 5, 2: 11}, {0: 7, 1: 11, 2: 13})),
        (weight + 10, weight + 16, 31), 2 * weight + 57)
    checked = module._checked_snapshot(graph)
    quotient, membership = module._exact_quotient(checked, [[0, 1], [2]])
    assert membership == [0, 0, 1]
    assert quotient.rows[0][0] == 2 * weight + 8
    assert quotient.rows[0][1] == quotient.rows[1][0] == 18
    assert quotient.rows[1][1] == 13
    assert quotient.degrees == (2 * weight + 26, 31)
    assert quotient.volume == graph.volume
    with pytest.raises(TypeError):
        quotient.rows[0][0] = 0


def test_cached_degree_mismatch_and_invalid_caps_fail_explicitly():
    bad = PreparedIntegerGraph((MappingProxyType({1: 1}), MappingProxyType({0: 1})), (99, 1), 2)
    with pytest.raises(ValueError, match='degree/volume'):
        module.recursive_cheap(bad, [(0, 1)])
    for cap in (1, 65):
        with pytest.raises(ValueError, match='in 2..64'):
            module.recursive_cheap(sparse.csr_matrix([[0, 1], [1, 0]]), [(0, 1)], max_block_size=cap)


def test_recursion_recomputes_without_a_three_round_limit(monkeypatch):
    # One valid subset of compatible twins is exposed per call to exercise the
    # controller. Complete gamma0 graphs have a unique all-fused optimum, so
    # every staged pair below is a genuine safe decision, not a fake oracle.
    actual = module.degree_proportional_twins
    calls = []
    def one_compatible_pair(graph, gamma, strict=False):
        result = actual(graph, gamma, strict=strict)
        calls.append(graph.n)
        result['merge_groups'] = [[0, 1]] if result['merge_groups'] else []
        result['safe_edges'] = result['safe_edges'][:1]
        return result
    monkeypatch.setattr(module, 'degree_proportional_twins', one_compatible_pair)
    a = sparse.csr_matrix(np.ones((8, 8), dtype=int) - np.eye(8, dtype=int))
    result = module.recursive_cheap(a, [], Fraction(0))
    assert result['remaining_vertices'] == 1
    assert result['merge_round_count'] >= 4
    assert all(left > right for left, right in zip(calls, calls[1:]))


def test_no_weak_almost_clique_is_requested_or_unioned(monkeypatch):
    calls = []
    actual = module.almost_clique
    def strict_only(graph, block, gamma, **kwargs):
        calls.append(kwargs['strict'])
        return actual(graph, block, gamma, **kwargs)
    monkeypatch.setattr(module, 'almost_clique', strict_only)
    a = sparse.csr_matrix([[0, 1, 0], [1, 0, 1], [0, 1, 0]])
    module.recursive_cheap(a, [(0, 1), (0, 1, 2)], Fraction(1))
    assert calls and all(calls)
