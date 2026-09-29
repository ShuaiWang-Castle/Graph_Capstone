"""Bounded independent weighted-reference safety and dense-formula checks."""
from fractions import Fraction
import itertools
import json

import numpy as np
import pytest
from scipy import sparse

from degree_contraction import certify_block, prepare_graph
from research.baselines.weighted_reference import (
    _exact_psd_reference,
    dense_exterior_diagnostic,
    prepare_weighted_reference_graph,
    weighted_collective_reference,
    weighted_contrast,
)


def f(value):
    return Fraction(int(value)) if isinstance(value, (int, np.integer)) else Fraction.from_float(float(value))


def dense_reference(adjacency, block, gamma, center="median", penalty="center", anchor=None):
    """Direct dense abs sums and true edge Laplacian, independent of sparse code."""
    values = adjacency.toarray()
    n, k = len(values), len(block)
    exact = [[f(entry) for entry in row] for row in values]
    all_degree = [sum(row) for row in exact]
    degrees = [all_degree[u] for u in block]
    volume, total = sum(degrees), sum(all_degree)
    outside = [u for u in range(n) if u not in block]
    rows = [[exact[u][w] / degree for w in outside] for u, degree in zip(block, degrees)]
    if center == "zero":
        c = [Fraction()] * len(outside)
    elif center == "anchor":
        c = rows[0 if anchor is None else block.index(anchor)]
    else:
        c = []
        for column in zip(*rows):
            order = sorted(column)
            c.append(order[k // 2] if k % 2 else (order[k // 2 - 1] + order[k // 2]) / 2)
    delta = [sum(abs(x - y) for x, y in zip(row, c)) for row in rows]
    mean = sum(d * deviation for d, deviation in zip(degrees, delta)) / volume
    penalties = [[Fraction() for _ in block] for _ in block]
    matrix = [[Fraction() for _ in block] for _ in block]
    for i in range(k):
        for j in range(i + 1, k):
            if penalty == "full_pair_distance":
                p = sum(abs(degrees[j] * exact[block[i]][w] - degrees[i] * exact[block[j]][w])
                        for w in outside) / volume
            else:
                p = degrees[i] * degrees[j] / volume * (delta[i] + delta[j])
            penalties[i][j] = penalties[j][i] = p
            h = exact[block[i]][block[j]] - gamma * degrees[i] * degrees[j] / total - p
            matrix[i][i] += h
            matrix[j][j] += h
            matrix[i][j] = matrix[j][i] = -h
    basis = [[Fraction(int(row == col)) - (degrees[col] / degrees[0] if row == 0 else 0)
              for col in range(1, k)] for row in range(k)]
    projected = [[sum(basis[u][i] * matrix[u][v] * basis[v][j]
                       for u in range(k) for v in range(k))
                  for j in range(k - 1)] for i in range(k - 1)]
    return projected, delta, mean, penalties


def determinant(matrix):
    n = len(matrix)
    total = Fraction()
    for permutation in itertools.permutations(range(n)):
        inversions = sum(permutation[i] > permutation[j] for i in range(n) for j in range(i + 1, n))
        product = Fraction(-1 if inversions % 2 else 1)
        for i, j in enumerate(permutation):
            product *= matrix[i][j]
        total += product
    return total


def principal_minor_psd(matrix):
    minors = []
    for size in range(1, len(matrix) + 1):
        for subset in itertools.combinations(range(len(matrix)), size):
            minors.append(determinant([[matrix[i][j] for j in subset] for i in subset]))
    return all(value >= 0 for value in minors), all(value > 0 for value in minors)


@pytest.mark.parametrize("center", ["zero", "anchor", "median"])
def test_sparse_center_matches_dense_true_laplacian_and_exact_minors(center):
    dense = np.array([[2, 2, 1, 0, 5], [2, 0, 3, 2, 0], [1, 3, 2, 4, 1],
                      [0, 2, 4, 0, 3], [5, 0, 1, 3, 0]], dtype=np.int64)
    adjacency = sparse.csr_matrix(dense)
    block, gamma = (3, 1, 2, 0), Fraction(3, 4)
    anchor = 1 if center == "anchor" else None
    result = weighted_contrast(adjacency, block, gamma, center=center, anchor=anchor, include_details=True)
    projected, delta, mean, _ = dense_reference(adjacency, block, gamma, center, anchor=anchor)
    assert [[Fraction(x) for x in row] for row in result["metadata"]["exact_projected_matrix"]] == projected
    assert list(map(Fraction, result["metadata"]["exact_delta"])) == delta
    assert Fraction(result["metadata"]["exact_weighted_mean_delta"]) == mean
    assert (result["certified"], result["strict"]) == principal_minor_psd(projected)
    assert result["diagnostics"]["certifies"] is False
    json.dumps(result, allow_nan=False)


def test_sparse_full_pair_distance_matches_all_dense_exterior_coordinates():
    dense = np.array([[0, 3, 2, 0, 4], [3, 2, 1, 5, 0], [2, 1, 0, 1, 2],
                      [0, 5, 1, 0, 7], [4, 0, 2, 7, 0]], dtype=np.int64)
    a, block, gamma = sparse.csr_matrix(dense), (0, 2, 1), Fraction(2, 3)
    result = weighted_collective_reference(a, block, gamma, penalty="full_pair_distance", include_details=True)
    projected, _, _, penalties = dense_reference(a, block, gamma, penalty="full_pair_distance")
    assert [[Fraction(x) for x in row] for row in result["metadata"]["exact_pair_penalties"]] == penalties
    assert [[Fraction(x) for x in row] for row in result["metadata"]["exact_projected_matrix"]] == projected
    assert (result["certified"], result["strict"]) == principal_minor_psd(projected)


def partitions(n):
    def visit(prefix, maximum):
        if len(prefix) == n:
            yield tuple(prefix)
        else:
            for label in range(maximum + 2):
                yield from visit(prefix + [label], max(maximum, label))
    yield from visit([0], 0)


def test_bounded_five_vertex_weighted_safety_and_forced_exact_median_core_equality():
    rng = np.random.default_rng(20261001)
    examples = [np.ones((5, 5), dtype=np.int64) - np.eye(5, dtype=np.int64)]
    for _ in range(3):
        upper = np.triu(rng.choice([0, 1, 2, 5], size=(5, 5)), 1)
        example = upper + upper.T
        np.fill_diagonal(example, rng.choice([0, 2], size=5))
        examples.append(example)
    partition_list = list(partitions(5))
    blocks = [block for size in range(2, 6) for block in itertools.combinations(range(5), size)]
    accepted = 0
    for dense in examples:
        a = sparse.csr_matrix(dense)
        prepared = prepare_weighted_reference_graph(a)
        core_prepared = prepare_graph(a)
        degrees, total = dense.sum(axis=1).tolist(), int(dense.sum())
        for gamma in (Fraction(1, 4), Fraction(1), Fraction(2)):
            coefficients = {(u, v): Fraction(int(dense[u, v])) - gamma * degrees[u] * degrees[v] / total
                            for u, v in itertools.combinations(range(5), 2)}
            scores = [sum(value for (u, v), value in coefficients.items() if labels[u] == labels[v])
                      for labels in partition_list]
            optimum = max(scores)
            optima = [labels for labels, value in zip(partition_list, scores) if value == optimum]
            for block in blocks:
                if any(degrees[u] == 0 for u in block):
                    continue
                references = [weighted_contrast(prepared, block, gamma, center=center, diagnostics=False)
                              for center in ("zero", "anchor", "median")]
                full = weighted_contrast(prepared, block, gamma, penalty="full_pair_distance", diagnostics=False)
                core = certify_block(core_prepared, block, gamma, verification="exact")
                assert (references[-1]["certified"], references[-1]["strict"]) == (core.certified, core.strict)
                for result in references + [full]:
                    assert result["metadata"]["acceptance_arithmetic"].startswith("exact Fraction")
                    if result["certified"]:
                        accepted += 1
                        assert any(len({labels[u] for u in block}) == 1 for labels in optima)
                        if result["strict"]:
                            assert all(len({labels[u] for u in block}) == 1 for labels in optima)
                if any(result["certified"] for result in references):
                    assert full["certified"]  # center is a sufficient upper bound
                if any(result["strict"] for result in references):
                    assert full["strict"]
    assert accepted > 0


def test_exact_singular_boundary_and_float_diagnostics_cannot_accept(monkeypatch):
    edge = sparse.csr_matrix([[0, 1], [1, 0]])
    for center in ("zero", "anchor", "median"):
        weak = weighted_contrast(edge, (0, 1), Fraction(2), center=center)
        assert weak["certified"] and not weak["strict"]
        assert weak["status"] == "verified_positive_semidefinite"
    monkeypatch.setattr(np.linalg, "eigvalsh", lambda _: np.array([1e100]))
    rejected = weighted_contrast(edge, (0, 1), Fraction(3), penalty="full_pair_distance")
    assert rejected["diagnostics"]["positive_screen"]
    assert not rejected["certified"] and not rejected["strict"]
    assert rejected["status"] == "failed_exact_psd"
    diagnostic = dense_exterior_diagnostic(edge, (0, 1), Fraction(1))
    assert diagnostic["diagnostics"]["positive_screen"]
    assert not diagnostic["certified"] and not diagnostic["strict"]
    assert diagnostic["status"] == "diagnostic_only"


@pytest.mark.parametrize("center", ["zero", "anchor", "median"])
def test_isolated_dense_reference_reports_payload_and_matches_sparse_diagnostics(center):
    a = sparse.csr_matrix([[0, 2, 1, 1, 0], [2, 0, 1, 0, 2], [1, 1, 0, 3, 0],
                           [1, 0, 3, 0, 1], [0, 2, 0, 1, 0]])
    block = (2, 0, 1)
    exact = weighted_contrast(a, block, Fraction(1, 2), center=center)
    diagnostic = dense_exterior_diagnostic(a, block, Fraction(1, 2), center=center)
    np.testing.assert_allclose(diagnostic["delta"], list(map(float, map(Fraction, exact["metadata"]["exact_delta"]))), atol=1e-15)
    assert diagnostic["margin"] == pytest.approx(exact["margin"], abs=1e-14)
    assert diagnostic["allocation_shape"] == [3, 2]
    assert diagnostic["allocation_payload_bytes"] == 3 * 2 * 8
    assert diagnostic["assembly_seconds"] >= 0
    assert not diagnostic["certified"]
    assert "not measured peak" in diagnostic["metadata"]["memory_measurement"]


def test_even_median_implicit_zeros_and_degree_retention_of_diagonal():
    a = sparse.csr_matrix([[2, 1, 0, 0, 1], [1, 0, 1, 0, 1], [0, 1, 0, 1, 0],
                           [0, 0, 1, 0, 0], [1, 1, 0, 0, 0]])
    result = weighted_contrast(a, (0, 1, 2, 3), 1, include_details=True)
    expected, delta, mean, _ = dense_reference(a, (0, 1, 2, 3), Fraction(1))
    assert result["metadata"]["exact_center"] == {"4": "1/8"}
    assert list(map(Fraction, result["metadata"]["exact_delta"])) == delta
    assert result["metadata"]["block_volume_exact"] == "10"
    assert Fraction(result["metadata"]["exact_weighted_mean_delta"]) == mean
    assert [[Fraction(x) for x in row] for row in result["metadata"]["exact_projected_matrix"]] == expected


def test_preparation_is_independent_reusable_and_keeps_represented_binary_weights():
    a = sparse.csr_matrix([[0, 0.5, 1.25], [0.5, 2, 1], [1.25, 1, 0]])
    prepared = prepare_weighted_reference_graph(prepare_graph(a))
    assert prepared.degrees == (Fraction(7, 4), Fraction(7, 2), Fraction(9, 4))
    assert prepared.volume == Fraction(15, 2)
    assert prepare_weighted_reference_graph(prepared) is prepared
    with pytest.raises(TypeError):
        prepared.rows[0][1] = Fraction(2)
    before = weighted_contrast(prepared, (0, 1), "1/8", diagnostics=False)
    a.data[:] = 0
    after = weighted_contrast(prepared, (0, 1), "1/8", diagnostics=False)
    assert before["certified"] == after["certified"]
    assert before["metadata"]["graph_fingerprint"] == after["metadata"]["graph_fingerprint"]
    assert before["metadata"]["preparation_seconds_charged"] == 0


def test_exact_guard_zero_degree_and_dense_guards_are_explicit():
    a = sparse.csr_matrix(np.ones((5, 5)) - np.eye(5))
    result = weighted_contrast(a, range(5), exact_max_size=4)
    assert not result["available"] and not result["certified"]
    assert result["status"] == "exact_size_limit"
    assert result["metadata"]["exact_block_limit"] == 4
    diagnostic = dense_exterior_diagnostic(a, (0, 1), max_vertices=4)
    assert not diagnostic["available"] and diagnostic["status"] == "dense_diagnostic_size_limit"
    isolated = sparse.csr_matrix([[0, 0, 0], [0, 0, 1], [0, 1, 0]])
    zero = weighted_contrast(isolated, (0, 1))
    assert not zero["available"] and zero["status"] == "zero_degree_excluded"
    assert zero["metadata"]["excluded_vertices"] == [0]


@pytest.mark.parametrize("matrix, expected", [
    ([[0, 0], [0, 1]], (True, False)),
    ([[1, 1], [1, 1]], (True, False)),
    ([[0, 1], [1, 0]], (False, False)),
    ([[1, 2], [2, 1]], (False, False)),
    ([[2, 1], [1, 2]], (True, True)),
])
def test_independent_fraction_psd_handles_singular_and_indefinite_cases(matrix, expected):
    assert _exact_psd_reference([[Fraction(x) for x in row] for row in matrix])[:2] == expected


def test_invalid_reference_inputs_raise_without_silent_repairs():
    a = sparse.csr_matrix([[0, 1], [1, 0]])
    for kwargs in ({"center": "adaptive"}, {"penalty": "unknown"}, {"exact_max_size": 1},
                   {"center": "anchor", "anchor": 3}, {"anchor": 0}):
        with pytest.raises(ValueError):
            weighted_contrast(a, (0, 1), **kwargs)
    for block in ((0, 0), (0, 2), (0,), (False, 1)):
        with pytest.raises(ValueError):
            weighted_contrast(a, block)
    with pytest.raises(ValueError):
        weighted_contrast(a, (0, 1), gamma=-1)
    with pytest.raises(TypeError, match="CSR"):
        prepare_weighted_reference_graph(a.tocsc())
    with pytest.raises(ValueError, match="symmetric"):
        prepare_weighted_reference_graph(sparse.csr_matrix([[0, 1], [0, 0]]))
    duplicated = sparse.csr_matrix(([0.5, 0.5, 1], [1, 1, 0], [0, 2, 3]), shape=(2, 2))
    with pytest.raises(ValueError, match="duplicate"):
        prepare_weighted_reference_graph(duplicated)
