from fractions import Fraction
from itertools import combinations
import random

import numpy as np
from scipy import sparse

from degree_contraction import modularity_exact
from research.baselines.almost_clique import almost_clique
from research.baselines.sparse_criteria import prepare_integer_graph


def _partitions(n):
    labels = [0] * n
    def extend(position, maximum):
        if position == n:
            yield tuple(labels)
            return
        for label in range(maximum + 2):
            labels[position] = label
            yield from extend(position + 1, max(maximum, label))
    yield from extend(1, 0)


def test_rule4_matches_exact_positive_mincuts_and_preserves_optima():
    rng = random.Random(52141)
    verified = 0
    for instance in range(8):
        a = np.zeros((5, 5), dtype=int)
        for u, v in combinations(range(5), 2):
            a[u, v] = a[v, u] = rng.randrange(4)
        if instance % 2:
            a[0, 0] = 2  # quotient convention includes full diagonal degrees
        csr = sparse.csr_matrix(a)
        prepared = prepare_integer_graph(csr)
        degrees, volume = prepared.degrees, prepared.volume
        for gamma in (Fraction(1, 2), Fraction(1), Fraction(2)):
            scored = [(modularity_exact(csr, labels, gamma), labels) for labels in _partitions(5)]
            optimum = max(q for q, _ in scored)
            optimum_labels = [labels for q, labels in scored if q == optimum]
            for size in range(2, 6):
                for block in combinations(range(5), size):
                    result = almost_clique(prepared, block, gamma, strict=False)
                    positive = {(u, v): max(0, gamma.denominator * volume * int(a[u, v])
                                            - gamma.numerator * degrees[u] * degrees[v])
                                for u, v in combinations(block, 2)}
                    cuts = []
                    for mask in range(1, 1 << (len(block) - 1)):
                        side = {block[i + 1] for i in range(len(block) - 1) if mask & (1 << i)}
                        cuts.append(sum(w for (u, v), w in positive.items() if (u in side) != (v in side)))
                    assert result["metadata"]["internal_positive_mincut_numerator"] == min(cuts)
                    if result["certified"]:
                        verified += 1
                        fused = [len({labels[u] for u in block}) == 1 for labels in optimum_labels]
                        assert all(fused) if result["strict"] else any(fused)
    assert verified > 0
