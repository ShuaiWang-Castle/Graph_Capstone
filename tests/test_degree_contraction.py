"""Substantive correctness diagnostics; these are not comparative experiments."""
from fractions import Fraction
import itertools

import numpy as np
import pytest
from scipy import sparse

from degree_contraction import (
    certify_block,
    contract_certified_blocks,
    modularity,
    modularity_exact,
    prepare_graph,
    quotient_adjacency,
    sparse_exterior_deviation,
)
from degree_contraction.certificate import _exact_psd


def adjacency(n, weighted_edges, diagonal=None):
    dense = np.zeros((n, n), dtype=float)
    for u, v, weight in weighted_edges:
        dense[u, v] = dense[v, u] = weight
    if diagonal is not None:
        np.fill_diagonal(dense, diagonal)
    return sparse.csr_matrix(dense)


def partitions(n):
    if n == 0:
        yield ()
        return
    def visit(prefix, maximum):
        if len(prefix) == n:
            yield tuple(prefix)
        else:
            for label in range(maximum + 2):
                yield from visit(prefix + [label], max(maximum, label))
    yield from visit([0], 0)


def fused(labels, block):
    return len({labels[u] for u in block}) == 1


def test_sparse_median_deviation_matches_independent_dense_reference():
    rng = np.random.default_rng(20260929)
    for n in (8, 17, 41):
        values = rng.integers(0, 9, size=(n, n)) / 4
        keep = rng.random((n, n)) < 0.2
        dense = np.triu(values * keep, 1)
        dense += dense.T
        # Quotient-style diagonals affect full normalization but not exterior
        # support. Positive diagonal ensures every tested row has positive d.
        np.fill_diagonal(dense, rng.integers(1, 5, size=n) / 2)
        a = sparse.csr_matrix(dense)
        for k in (2, 3, min(6, n), n):
            block = tuple(map(int, rng.choice(n, size=k, replace=False)))
            outside = [u for u in range(n) if u not in block]
            d = dense.sum(axis=1)[list(block)]
            exterior = dense[np.ix_(block, outside)] / d[:, None]
            center = np.median(exterior, axis=0)
            expected = np.abs(exterior - center).sum(axis=1)
            result = sparse_exterior_deviation(a, block)
            np.testing.assert_allclose(result.delta, expected, atol=5e-16, rtol=5e-15)
            np.testing.assert_allclose(result.weighted_mean_delta, expected @ d / d.sum(), atol=5e-16)
            reconstructed = dict(zip(result.center_nodes, result.center_values))
            np.testing.assert_allclose([reconstructed.get(w, 0) for w in outside], center)
            assert k * len(result.center_nodes) <= 2 * result.exterior_incidences


def test_even_median_includes_implicit_zeros_at_half_support():
    a = adjacency(5, [(0, 4, 1), (1, 4, 1), (0, 2, 1), (1, 3, 1), (2, 3, 1)])
    result = sparse_exterior_deviation(a, (0, 1, 2, 3))
    assert result.center_nodes.tolist() == [4]
    assert result.center_values.tolist() == [0.25]
    np.testing.assert_array_equal(result.delta, [0.25, 0.25, 0.25, 0.25])


def test_diagnostics_cannot_accept_and_exact_boundary_is_weak():
    a = adjacency(2, [(0, 1, 1)])
    diagnostic = certify_block(a, (0, 1), gamma=1, verification="none")
    assert diagnostic.margin > 0
    assert not diagnostic.certified and not diagnostic.strict
    assert diagnostic.verification_status == "not_requested"
    weak = certify_block(a, (0, 1), gamma=2, verification="exact")
    assert weak.certified and not weak.strict
    assert weak.verification_status == "verified_positive_semidefinite"
    assert modularity_exact(a, (0, 0), 2) == modularity_exact(a, (0, 1), 2)
    strict = certify_block(a, (0, 1), gamma=Fraction(3, 2), verification="exact")
    assert strict.certified and strict.strict
    rejected = certify_block(a, (0, 1), gamma=Fraction(5, 2), verification="exact")
    assert not rejected.certified
    assert rejected.verification_status == "failed_exact_psd"


def test_rational_ldl_handles_singular_and_indefinite_zero_pivots():
    def f(matrix):
        return [[Fraction(x) for x in row] for row in matrix]
    assert _exact_psd(f([[1, 1], [1, 1]]))[:2] == (True, False)
    assert _exact_psd(f([[0, 0], [0, 1]]))[:2] == (True, False)
    assert _exact_psd(f([[2, 1], [1, 2]]))[:2] == (True, True)
    assert _exact_psd(f([[0, 1], [1, 0]]))[:2] == (False, False)
    assert _exact_psd(f([[1, 2], [2, 1]]))[:2] == (False, False)


def test_negative_internal_affinity_can_still_have_a_strict_certificate():
    a = adjacency(3, [(0, 1, 1), (1, 2, 1)])
    graph = prepare_graph(a)
    gamma = Fraction(1, 2)
    degrees, total = graph.exact_degrees()
    assert Fraction() - gamma * degrees[0] * degrees[2] / total < 0
    result = certify_block(graph, (0, 1, 2), gamma, verification="exact")
    assert result.certified and result.strict
    values = {labels: modularity_exact(graph, labels, gamma) for labels in partitions(3)}
    optima = [labels for labels, value in values.items() if value == max(values.values())]
    assert all(fused(labels, result.block) for labels in optima)


def test_all_four_vertex_unweighted_graphs_against_exact_partition_enumeration():
    edges = list(itertools.combinations(range(4), 2))
    blocks = [block for k in range(2, 5) for block in itertools.combinations(range(4), k)]
    all_partitions = list(partitions(4))
    positive = weak = 0
    for mask in range(1, 1 << len(edges)):
        a = adjacency(4, [(u, v, 1) for i, (u, v) in enumerate(edges) if mask & (1 << i)])
        graph = prepare_graph(a)
        for gamma in (Fraction(1, 2), Fraction(1), Fraction(2)):
            values = [modularity_exact(graph, labels, gamma) for labels in all_partitions]
            maximum = max(values)
            optima = [labels for labels, value in zip(all_partitions, values) if value == maximum]
            accepted = []
            for block in blocks:
                certificate = certify_block(graph, block, gamma, verification="exact")
                if not certificate.certified:
                    continue
                accepted.append(certificate)
                positive += int(certificate.strict)
                weak += int(not certificate.strict)
                assert any(fused(labels, block) for labels in optima)
                if certificate.strict:
                    assert all(fused(labels, block) for labels in optima)
                # At an optimum every positive-probability anchor preserves the
                # objective, including weak certificates with overlapping blocks.
                for labels in optima:
                    for anchor in block:
                        after = list(labels)
                        for u in block:
                            after[u] = labels[anchor]
                        assert modularity_exact(graph, after, gamma) == maximum
            if accepted:
                quotient = contract_certified_blocks(graph, accepted)
                quotient_maximum = max(modularity_exact(quotient.adjacency, labels, gamma)
                                       for labels in partitions(len(quotient.groups)))
                assert quotient_maximum == maximum
    assert positive > 0 and weak > 0


def test_seeded_weighted_graphs_with_diagonals_against_exact_partition_optima():
    rng = np.random.default_rng(20260929)
    candidates = [block for k in range(2, 6) for block in itertools.combinations(range(5), k)]
    all_partitions = list(partitions(5))
    accepted = 0
    for _ in range(16):
        upper = np.triu(rng.integers(0, 7, size=(5, 5)) / 4, 1)
        dense = upper + upper.T
        np.fill_diagonal(dense, rng.integers(0, 5, size=5) / 2)
        graph = prepare_graph(sparse.csr_matrix(dense))
        for gamma in (Fraction(1, 4), Fraction(1), Fraction(3, 2)):
            values = [modularity_exact(graph, labels, gamma) for labels in all_partitions]
            maximum = max(values)
            optima = [labels for labels, value in zip(all_partitions, values) if value == maximum]
            certificates = [certify_block(graph, block, gamma, verification="exact") for block in candidates]
            certificates = [c for c in certificates if c.certified]
            accepted += len(certificates)
            for certificate in certificates:
                assert any(fused(labels, certificate.block) for labels in optima)
                if certificate.strict:
                    assert all(fused(labels, certificate.block) for labels in optima)
            if certificates:
                quotient = contract_certified_blocks(graph, certificates)
                assert max(modularity_exact(quotient.adjacency, labels, gamma)
                           for labels in partitions(len(quotient.groups))) == maximum
    assert accepted > 0


def test_path_quotient_preserves_diagonal_mass_and_all_lifted_partitions():
    a = adjacency(4, [(0, 1, 1), (1, 2, 1), (2, 3, 1)])
    quotient = quotient_adjacency(a, [(0, 1), (2, 3)])
    np.testing.assert_array_equal(quotient.adjacency.toarray(), [[2, 1], [1, 2]])
    np.testing.assert_array_equal(np.asarray(quotient.adjacency.sum(axis=1)).ravel(), [3, 3])
    assert quotient.adjacency.sum() == 6
    assert quotient.metadata["weights_exactly_preserved"]
    assert quotient.metadata["degree_and_total_mass_identity_verified"]
    for labels in partitions(2):
        for gamma in (Fraction(1, 2), Fraction(1), Fraction(3, 2)):
            lifted = quotient.lift_labels(labels)
            assert modularity_exact(a, lifted, gamma) == modularity_exact(quotient.adjacency, labels, gamma)
            assert modularity(a, lifted, gamma) == pytest.approx(modularity(quotient.adjacency, labels, gamma))
    # The diagonal convention matters to the null term, not merely the constant
    # diagonal contribution: dropping loops changes the inter-group B sign.
    assert Fraction(1) - Fraction(3 * 3, 6) == Fraction(-1, 2)
    assert Fraction(1) - Fraction(1 * 1, 2) == Fraction(1, 2)


def test_weighted_quotient_with_existing_diagonal_and_omitted_singletons():
    a = adjacency(5, [(0, 1, 0.5), (0, 2, 1.25), (1, 3, 2), (2, 4, 0.75), (3, 4, 1)],
                  diagonal=[0.5, 0, 2, 0, 1])
    quotient = quotient_adjacency(a, [(0, 2), (1, 3)])
    assert quotient.groups == ((0, 2), (1, 3), (4,))
    np.testing.assert_array_equal(quotient.adjacency.toarray(),
                                  (quotient.aggregation.T @ a @ quotient.aggregation).toarray())
    for labels in partitions(3):
        assert modularity_exact(a, quotient.lift_labels(labels), Fraction(7, 5)) == modularity_exact(
            quotient.adjacency, labels, Fraction(7, 5))
    assert quotient.lift_labels(["a", "b", "a"]).tolist() == ["a", "b", "a", "b", "a"]


def test_overlapping_positive_degree_weak_certificates_can_be_united():
    a = adjacency(3, [(0, 1, 1), (0, 2, 1), (1, 2, 1)])
    certificates = [certify_block(a, block, Fraction(3, 2), verification="exact")
                    for block in ((0, 1), (1, 2))]
    assert all(c.certified and not c.strict for c in certificates)
    quotient = contract_certified_blocks(a, certificates)
    assert quotient.groups == ((0, 1, 2),)
    assert quotient.metadata["optimal_value_preserved"]
    assert quotient.metadata["guarantee"] == "a compatible fused optimum exists"


def test_zero_degree_exclusion_and_certificate_graph_resolution_identity():
    a = adjacency(5, [(1, 4, 1), (2, 3, 1)])
    for block in ((0, 1, 4), (0, 2, 3)):
        result = certify_block(a, block, 1, verification="exact")
        assert not result.certified and result.verification_status == "zero_degree_excluded"
        assert result.metadata["excluded_vertices"] == [0]
        with pytest.raises(ValueError, match="exact verified"):
            contract_certified_blocks(a, [result])
    certificate = certify_block(a, (1, 4), 1, verification="exact")
    assert certificate.certified
    different = adjacency(5, [(1, 4, 2), (2, 3, 1)])
    with pytest.raises(ValueError, match="this graph"):
        contract_certified_blocks(different, [certificate])
    second = certify_block(a, (2, 3), 2, verification="exact")
    with pytest.raises(ValueError, match="same exact resolution"):
        contract_certified_blocks(a, [certificate, second])


def test_unrepresentable_quotient_sum_is_never_called_exact():
    a = adjacency(3, [(0, 1, float(2**53)), (1, 2, 1)])
    with pytest.raises(ArithmeticError, match="rounded exact weights"):
        quotient_adjacency(a, [(0, 2), (1,)])
    diagnostic = quotient_adjacency(a, [(0, 2), (1,)], require_exact=False)
    assert not diagnostic.metadata["weights_exactly_preserved"]
    assert diagnostic.metadata["rounded_aggregate_count"] == 2
    assert diagnostic.metadata["max_absolute_aggregate_rounding"] == 1


def test_block_order_size_limits_and_input_validation():
    a = adjacency(4, [(u, v, 1) for u, v in itertools.combinations(range(4), 2)])
    first = certify_block(a, (0, 1, 2, 3), 1, verification="exact")
    second = certify_block(a, (2, 0, 3, 1), 1, verification="exact")
    assert first.certified and second.certified
    assert first.margin == pytest.approx(second.margin)
    restricted = certify_block(a, (0, 1, 2, 3), 1, exact_max_size=3)
    assert restricted.margin > 0 and not restricted.certified
    assert restricted.verification_status == "exact_size_limit"
    small_dense = certify_block(a, (0, 1, 2, 3), 1, verification="exact", dense_max_size=3)
    assert small_dense.restricted_eigenvalue is None and small_dense.certified
    with pytest.raises(TypeError, match="CSR"):
        prepare_graph(a.tocsc())
    with pytest.raises(ValueError, match="symmetric"):
        prepare_graph(sparse.csr_matrix([[0, 1], [0, 0]]))
    with pytest.raises(ValueError, match="nonnegative"):
        prepare_graph(sparse.csr_matrix([[0, -1], [-1, 0]]))
    with pytest.raises(ValueError, match="finite"):
        prepare_graph(sparse.csr_matrix([[0, np.nan], [np.nan, 0]]))
    with pytest.raises(ValueError, match="duplicate"):
        certify_block(a, (0, 0))
    duplicate = sparse.csr_matrix(([0.5, 0.5, 1], [1, 1, 0], [0, 2, 3]), shape=(2, 2))
    with pytest.raises(ValueError, match="duplicate CSR"):
        prepare_graph(duplicate)
