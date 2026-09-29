"""Small independent engineering controls, not performance measurements."""
from fractions import Fraction as F
import json

import numpy as np
import pytest
from scipy import sparse

from degree_contraction import certify_block, modularity_exact, prepare_graph
from degree_contraction.certificate import _exact_psd
from research.baselines.block_criteria import uniform_copy_contrast
from research.baselines.weighted_reference import weighted_collective_reference
from experiments.extensions.metric_sdp.safe_composition import (
    ExactGraph, _degree_collective, _schur_psd, _to_csr, optimized_pair,
    prepare_exact_graph, run_composition, uniform_collective, weighted_collective,
)


def graph(n, edges=(), loops=()):
    values = np.zeros((n, n), dtype=np.int64)
    for u, v, x in edges:
        values[u, v] = values[v, u] = x
    for u, x in loops:
        values[u, u] = x
    return sparse.csr_matrix(values)


def full_signed(a, gamma):
    """Independent full integer adjacency -> dense Fraction B."""
    dense = a.toarray()
    degrees = [sum(map(int, row)) for row in dense]
    total = sum(degrees)
    return [[F(int(dense[u, v])) - gamma * degrees[u] * degrees[v] / total
             for v in range(len(degrees))] for u in range(len(degrees))]


def full_pair(b, u, v):
    outside = [w for w in range(len(b)) if w not in (u, v)]
    roots = {F(), F(1)}
    for w in outside:
        slope = b[u][w] + b[v][w]
        if slope and 0 <= b[u][w] / slope <= 1:
            roots.add(b[u][w] / slope)
    def loss(p):
        return sum((abs(p * b[v][w] - (1 - p) * b[u][w]) for w in outside), F())
    p = min(roots, key=lambda p: (loss(p), p))
    return p, loss(p)


def full_uniform(a, block, gamma):
    b = full_signed(a, gamma)
    outside = [w for w in range(a.shape[0]) if w not in block]
    k = len(block)
    distances = [[sum((abs(b[u][w] - b[v][w]) for w in outside), F())
                  for v in block] for u in block]
    h = [[F() for _ in block] for _ in block]
    for i in range(k):
        for j in range(i + 1, k):
            weight = b[block[i]][block[j]] - distances[i][j] / k
            h[i][i] += weight
            h[j][j] += weight
            h[i][j] = h[j][i] = -weight
    p = k - 1
    projected = [[h[i][j] - h[i][p] - h[p][j] + h[p][p]
                  for j in range(k - 1)] for i in range(k - 1)]
    return distances, projected, _exact_psd(projected)[:2]


@pytest.mark.parametrize("gamma", [F(), F(1, 8), F(3, 4), F(2)])
def test_compressed_optimized_pair_matches_full_rows_and_all_breakpoints(gamma):
    a = graph(7, [(0, 1, 4), (0, 2, 2), (1, 2, 1), (1, 3, 5),
                  (2, 4, 3), (3, 4, 1)], [(0, 2), (2, 7), (5, 11), (6, 13)])
    b = full_signed(a, gamma)
    prepared = prepare_exact_graph(a)
    for u in range(7):
        for v in range(u + 1, 7):
            p, loss = full_pair(b, u, v)
            result = optimized_pair(prepared, u, v, gamma)
            assert (result["p"], result["loss"]) == (p, loss)
            assert result["margin"] == b[u][v] - loss
            assert result["certified"] == (b[u][v] >= loss)
            assert result["strict"] == (b[u][v] > loss)
    assert optimized_pair(prepared, 0, 1, gamma)["inactive_volume"] > 0


def test_zero_affinity_nonzero_exterior_twins_are_scanned():
    a = graph(3, [(0, 1, 1), (0, 2, 4), (1, 2, 4)], [(0, 1), (1, 1)])
    result = run_composition(a, [], F(5, 9), mode="S")
    first = result.operations[0]
    assert first["block_current"] == [0, 1]
    assert first["certificate"]["affinity"] == "0"
    assert first["certificate"]["loss"] == "0"
    assert first["certificate"]["p"] == "1/2"
    assert first["certificate"]["strict"] is False


def test_weak_endpoint_rechecks_and_bank_cap_is_after_mapping():
    # Signed off-diagonal costs are (1,1,-2); the two weak endpoint facts
    # cannot be unioned. All degrees are 8, total24, gamma3/4.
    a = graph(3, [(0, 1, 3), (0, 2, 3)], [(0, 2), (1, 5), (2, 5)])
    for v in (1, 2):
        check = optimized_pair(a, 0, v, F(3, 4))
        assert check["certified"] and not check["strict"] and check["p"] == 0
    result = run_composition(a, [(0, 1, 2)], F(3, 4), max_block_size=2)
    assert result.groups == ((0, 1), (2,))
    assert len(result.operations) == 1
    assert result.metadata["counts"]["uniform_checks"] == 1  # raw size3 mapped to2
    assert modularity_exact(a, (0, 0, 1), F(3, 4)) > modularity_exact(a, (0, 0, 0), F(3, 4))
    assert modularity_exact(result.adjacency, (0, 1), F(3, 4)) == modularity_exact(
        a, (0, 0, 1), F(3, 4))


@pytest.mark.parametrize("gamma", [F(1, 3), F(1), F(5, 2)])
def test_sparse_uniform_distances_and_ldl_match_independent_full_matrix(gamma):
    a = graph(7, [(0, 1, 4), (0, 2, 2), (1, 2, 1), (1, 3, 5),
                  (2, 4, 3), (3, 4, 1)], [(0, 2), (2, 7), (5, 11), (6, 13)])
    for block in ((0, 1), (0, 1, 2), (1, 2, 3, 4), tuple(range(7))):
        distances, projected, decision = full_uniform(a, block, gamma)
        result = uniform_collective(a, block, gamma)
        assert result["distances"] == distances
        assert result["projected_matrix"] == projected
        assert (result["certified"], result["strict"]) == decision


def test_uniform_cap150_is_removed_and_exact_weak_boundary_is_retained():
    a = graph(151, [(0, 1, 10)], [(u, 1) for u in range(2, 151)])
    assert uniform_copy_contrast(a, (0, 1))["available"] is False
    result = uniform_collective(a, (0, 1))
    assert result["available"] and result["certified"] and result["strict"]
    cycle = graph(4, [(0, 1, 1), (1, 2, 1), (2, 3, 1), (0, 3, 1)])
    weak = uniform_collective(cycle, tuple(range(4)), F(1))
    assert weak["certified"] and not weak["strict"]
    assert not uniform_collective(cycle, tuple(range(4)), F(3, 2))["certified"]


def test_zero_pivot_indefiniteness_is_not_accepted():
    assert _schur_psd([[F(0), F(1)], [F(1), F(0)]])[:2] == (False, False)
    assert _schur_psd([[F(0), F(0)], [F(0), F(1)]])[:2] == (True, False)


def test_pair_then_bank_collective_uses_actual_current_csr_ids():
    a = graph(6, [(0, 1, 10), (2, 3, 1), (3, 4, 1), (4, 5, 1), (2, 5, 1)])
    original = a.copy()
    result = run_composition(a, [(2, 3, 4, 5), tuple(range(6))], F(1, 2),
                             max_block_size=4)
    assert result.membership.tolist() == [0, 0, 1, 1, 1, 1]
    assert result.groups == ((0, 1), (2, 3, 4, 5))
    assert [op["block_current"] for op in result.operations] == [[0, 1], [1, 2, 3, 4]]
    assert result.operations[1]["original_groups_before"] == [[2], [3], [4], [5]]
    assert result.operations[1]["original_bank_blocks"] == [[2, 3, 4, 5]]
    assert result.degrees == (F(20), F(8)) and result.total_degree == 28
    assert result.adjacency.toarray().tolist() == [[20.0, 0.0], [0.0, 8.0]]
    assert (a != original).nnz == 0
    assert not result.membership.flags.writeable
    json.dumps(result.operations, allow_nan=False)


def test_core_degree_uses_actual_even_median_and_exact_decisions():
    a = graph(5, [(0, 4, 1), (1, 4, 1), (0, 2, 1), (1, 3, 1), (2, 3, 1)])
    exact = prepare_exact_graph(a)
    prepared = prepare_graph(a)
    block = (0, 1, 2, 3)
    # Exactly half of an exterior column is nonzero: its median is 1/4.
    for gamma in (F(1, 4), F(1), F(3)):
        check = _degree_collective(exact, block, gamma, 64, prepared)
        core = certify_block(prepared, block, gamma, verification="exact")
        assert (check["certified"], check["strict"]) == (core.certified, core.strict)
        assert check["delta"] == [F(1, 4)] * 4
        assert check["weighted_mean_delta"] == F(1, 4)


def test_sd_sw_are_fresh_second_stages_and_weighted_reference_is_unchanged():
    # Unequal full degrees make uniform exterior contrasts large; exact degree
    # cancellation retains this small supplied-block certificate.
    a = graph(5, [(0, 1, 10), (1, 2, 10), (2, 3, 10), (0, 3, 10)],
              [(0, 80), (4, 100000)])
    bank = [(0, 1, 2, 3)]
    s = run_composition(a, bank, mode="S")
    assert s.graph.n == 5 and not s.operations
    d = run_composition(a, bank, mode="D")
    sd = run_composition(a, bank, mode="SD")
    sw = run_composition(a, bank, mode="SW")
    assert d.groups == sd.groups == sw.groups == ((0, 1, 2, 3), (4,))
    assert [p["stage"] for p in sd.metadata["phases"]] == ["S", "D"]
    assert [p["stage"] for p in sw.metadata["phases"]] == ["S", "W"]
    assert [op["stage"] for op in sd.operations] == ["D"]
    assert [op["stage"] for op in sw.operations] == ["W"]
    check = weighted_collective(a, bank[0])
    source = weighted_collective_reference(a, bank[0], penalty="full_pair_distance",
                                          diagnostics=False, include_details=True)
    for key in ("certified", "strict", "verification_status", "margin"):
        assert check[key] == source[key]
    assert check["metadata"]["exact_projected_matrix"] == source["metadata"]["exact_projected_matrix"]
    assert check["diagnostics"]["margin"] is None
    assert sw.total_degree == sum((F(int(x)) for x in a.data), F())
    assert modularity_exact(sw.adjacency, (0, 1)) == modularity_exact(a, (0, 0, 0, 0, 1))


def test_domain_invalid_input_and_unrepresentable_materialization_fail_loudly():
    with pytest.raises(ValueError):
        run_composition(graph(3, [(0, 1, 1)]), [], F(-1))
    with pytest.raises(ValueError):
        run_composition(graph(3, [(0, 1, 1)]), [(0, 0, 1)])
    with pytest.raises(ValueError):
        uniform_collective(graph(3, [(0, 1, 1)]), (0, 1), max_block_size=65)
    with pytest.raises(ValueError):
        prepare_exact_graph(sparse.csr_matrix([[1, 2], [0, 1]]))
    with pytest.raises(ArithmeticError):
        _to_csr(ExactGraph(({0: 2**53 + 1},)))
    if np.dtype(np.longdouble).itemsize > 8:
        with pytest.raises(ValueError):
            ExactGraph(({0: np.longdouble(1)},))
    singleton = run_composition(graph(1, loops=[(0, 9)]), [], mode="SW")
    assert singleton.graph.n == 1 and singleton.total_degree == 9
    assert not singleton.operations and singleton.adjacency[0, 0] == 9


def test_sd_sw_second_stage_rebuilds_after_real_s_merge_and_maps_original_bank():
    a = graph(7, [(0, 1, 10), (2, 3, 10), (3, 4, 10), (4, 5, 10), (2, 5, 10)],
              [(2, 80), (6, 100000)])
    bank = [(2, 3, 4, 5)]
    for mode, second in (("SD", "D"), ("SW", "W")):
        result = run_composition(a, bank, mode=mode)
        assert result.groups == ((0, 1), (2, 3, 4, 5), (6,))
        assert result.membership.tolist() == [0, 0, 1, 1, 1, 1, 2]
        assert [op["stage"] for op in result.operations] == ["S", second]
        next_op = result.operations[1]
        assert next_op["current_n_before"] == 6
        assert next_op["block_current"] == [1, 2, 3, 4]
        assert next_op["original_groups_before"] == [[2], [3], [4], [5]]
        assert next_op["original_bank_blocks"] == [[2, 3, 4, 5]]
        assert next_op["current_graph_sha256"] == result.operations[0]["quotient_graph_sha256"]
        assert modularity_exact(result.adjacency, (0, 1, 2)) == modularity_exact(
            a, (0, 0, 1, 1, 1, 1, 2))
