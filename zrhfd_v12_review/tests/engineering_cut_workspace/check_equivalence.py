"""Opt-in exhaustive engineering tests; never part of the frozen experiment."""
from pathlib import Path
from fractions import Fraction as F
from unittest.mock import patch
import hashlib
import itertools
import json
import sys
import subprocess
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from zrhfd.graph import Graph
from zrhfd import mincut, certificate
from zrhfd.experimental_cut_workspace import PreparedRegionWorkspace, installed_workspace


def brute_force(graph, region, seed, unary):
    best, winners = None, []
    others = [u for u in region if u != seed]
    for flags in itertools.product((False, True), repeat=len(others)):
        S = {seed} | {u for u, keep in zip(others, flags) if keep}
        cut = sum((F(str(float(w))) for u, v, w in graph.edges if (u in S) != (v in S)), F(0))
        value = cut + sum((F(unary[u]) for u in S), F(0))
        if best is None or value < best:
            best, winners = value, [sorted(S)]
        elif value == best:
            winners.append(sorted(S))
    return best, winners


def main():
    rng = np.random.default_rng(20261020)
    rows = []
    original_run = subprocess.run
    for case in range(24):
        n = 5 + case % 4
        weights = [1., 2., 3.] if case % 2 else [.25, .5, 1.25]
        edges = [(u, (u + 1) % n, weights[u % len(weights)]) for u in range(n)]
        edges += [(u, v, weights[(u + v) % len(weights)]) for u in range(n) for v in range(u + 2, n) if rng.random() < .35]
        graph = Graph.from_edges(n, edges)
        seed = case % n
        region = sorted({seed} | set(map(int, rng.choice(n, size=min(n, 3 + case % 4), replace=False))))
        # Duplicated/reversed input region must normalize exactly as the original.
        region_input = list(reversed(region)) + [seed]
        unary = {u: F(int(rng.integers(-17, 18)), [1, 3, 7, 13][(u + case) % 4]) for u in region}
        workspace = PreparedRegionWorkspace(graph, region_input, seed)
        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs['input'])
            return original_run(*args, **kwargs)
        with patch.object(subprocess, 'run', side_effect=capture):
            old_S, old_value, old_meta = mincut.cut_with_unary(graph, region_input, seed, unary)
            new_S, new_value, new_meta = workspace.solve(unary)
        encoded = workspace.encode(unary, include_arcs=True)
        optimum, winners = brute_force(graph, region, seed, unary)
        assert captured[0] == captured[1] == encoded.text
        assert old_S == new_S and old_value == new_value == optimum and new_S in winners
        assert seed in new_S and set(new_S) <= set(region)
        assert encoded.force == sum(c for u, v, c in encoded.arcs[:-1]) + 1
        for k in ('flow_integer', 'constant_integer', 'capacity_denominator', 'arcs', 'vertices', 'backend'):
            assert old_meta[k] == new_meta[k]
        rows.append({'case': case, 'n': n, 'region_size': len(region), 'status': 'PASS',
                     'same_capacity_text': True, 'same_ordered_arcs': True, 'same_cover': True,
                     'all_subset_optimum_exact': str(optimum), 'argmin_count': len(winners)})
    graph = Graph.from_edges(8, [(u, (u + 1) % 8) for u in range(8)] + [(0, 2), (0, 3), (4, 6)])
    region, seed = [0, 1, 2, 3, 4, 5], 0
    score = np.array([2., 1.8, 1.6, 1.5, .7, .6, .3, .1])
    old_mm = mincut.mm_refine(graph, seed, region, [seed], score)
    old_certificate = certificate.regional_certificate(graph, seed, region)
    with installed_workspace() as dispatcher:
        new_mm = mincut.mm_refine(graph, seed, region, [seed], score)
        new_certificate = certificate.regional_certificate(graph, seed, region)
        assert old_mm[0] == new_mm[0]
        assert [(s['Z_before_exact'], s['Z_proposed_exact'], s['mincut_objective_exact'], s['vertices'], s['accepted']) for s in old_mm[1]] == [(s['Z_before_exact'], s['Z_proposed_exact'], s['mincut_objective_exact'], s['vertices'], s['accepted']) for s in new_mm[1]]
        for k in ('LB_R', 'LB_R_upper', 'LB_R_lower_decimal', 'LB_R_upper_decimal', 'hull_vertices', 'hull_best', 'hull_best_Z_exact', 'mincut_calls', 'gap_bound_exact'):
            assert old_certificate[k] == new_certificate[k]
        assert len(dispatcher.workspaces) == 1
        rows.append({'kind': 'MM_and_certificate', 'status': 'PASS', 'shared_workspace_count': 1,
                     'same_hull_cover_and_objectives': True, 'workspace': dispatcher.summary()})
    huge = {u: F(1 << 124) for u in region}
    for function in (lambda: mincut.cut_with_unary(graph, region, seed, huge),
                     lambda: PreparedRegionWorkspace(graph, region, seed).encode(huge)):
        try:
            function()
        except OverflowError:
            pass
        else:
            raise AssertionError('Overflow must never fall back to float')
    rows.append({'kind': 'integer_overflow_rejection', 'status': 'PASS'})
    output = ROOT / 'reviews/performance_cut_workspace/equivalence_records.jsonl'
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {'status': 'PASS', 'role': 'artificial_engineering_equivalence_not_quality',
              'prototype_sha256': hashlib.sha256((ROOT / 'zrhfd/experimental_cut_workspace.py').read_bytes()).hexdigest(),
              'unchanged_binary_sha256': hashlib.sha256(mincut.BINARY.read_bytes()).hexdigest(), 'checks': rows}
    with output.open('a') as stream:
        stream.write(json.dumps(record, allow_nan=False) + '\n')
    print('PASS', len(rows), 'engineering equivalence checks')


if __name__ == '__main__':
    main()
