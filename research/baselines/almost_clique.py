"""Böcker et al. Algorithmica2011 Rule4 on supplied blocks, exactly.

The graph G in the source contains positive-cost edges. Its internal mincut
is compared with all internal negative insertion costs plus positive exterior
deletion costs. A strict margin forces fusion in every optimum. Weak blocks
are individually persistent; this module does not union overlapping weak tests.
"""
from fractions import Fraction
from numbers import Integral
from time import perf_counter

import networkx as nx

from .sparse_criteria import _graph, _parameter


def almost_clique(adjacency, block, gamma="1", *, max_block_size=64, strict=True):
    started = perf_counter()
    rows, degree, volume = _graph(adjacency)
    vertices = tuple(block)
    if len(vertices) < 2 or any(not isinstance(u, Integral) for u in vertices):
        raise ValueError("block needs at least two integer vertices")
    vertices = tuple(map(int, vertices))
    if len(set(vertices)) != len(vertices) or any(u < 0 or u >= len(rows) for u in vertices):
        raise ValueError("invalid block vertices")
    if max_block_size < 2:
        raise ValueError("block cap must be at least two")
    g = _parameter(gamma)
    result = {"criterion": "Bocker2011 Rule4 almost-clique supplied-block criterion",
              "block": list(vertices), "gamma": str(g), "certified": False,
              "strict": False, "available": True, "verification_status": None,
              "metadata": {"source": "https://doi.org/10.1007/s00453-009-9339-7",
                           "algorithm_scope": "one supplied block; not full published candidate search",
                           "internal_mincut_graph": "positive signed-affinity edges only",
                           "arithmetic": "Python integer coefficients and exact Stoer-Wagner",
                           "weak_composition": "individual decisions; overlapping weak blocks not unioned",
                           "max_block_size": max_block_size}}
    if len(vertices) > max_block_size:
        result.update(available=False, verification_status="block_size_limit")
        result["metadata"]["elapsed_seconds"] = perf_counter() - started
        return result
    p, q = g.numerator, g.denominator
    denominator = q * volume
    internal = nx.Graph()
    internal.add_nodes_from(vertices)
    negative = 0
    for i, u in enumerate(vertices):
        for v in vertices[i + 1:]:
            cost = q * volume * rows[u].get(v, 0) - p * degree[u] * degree[v]
            if cost > 0:
                internal.add_edge(u, v, weight=cost)
            else:
                negative -= cost
    inside = set(vertices)
    boundary = sum(max(0, q * volume * weight - p * degree[u] * degree[v])
                   for u in vertices for v, weight in rows[u].items() if v not in inside)
    upper = min(dict(internal.degree(weight="weight")).values())
    if strict and upper <= negative + boundary:
        # A singleton cut is a valid upper bound on the global mincut. This
        # exact screen proves the strict criterion cannot pass, without flow.
        result.update(verification_status="failed_exact_mincut_upper_bound", margin=None,
                      margin_upper_bound_exact=str(Fraction(upper - negative - boundary, denominator)))
        result["metadata"].update({"internal_positive_mincut_numerator": None,
                                   "internal_positive_mincut_upper_bound_numerator": upper,
                                   "negative_internal_sum_numerator": negative,
                                   "positive_boundary_sum_numerator": boundary,
                                   "elapsed_seconds": perf_counter() - started})
        return result
    if nx.is_connected(internal):
        mincut, partition = nx.stoer_wagner(internal, weight="weight")
    else:
        mincut = 0
        component = min(nx.connected_components(internal), key=min)
        partition = (component, inside - component)
    margin = mincut - negative - boundary
    result.update(certified=margin > 0 if strict else margin >= 0,
                  strict=margin > 0, verification_status="verified_strict" if margin > 0
                  else "verified_weak" if margin == 0 and not strict else "failed_strict_boundary" if margin == 0 else "failed_condition",
                  coefficient_denominator=denominator, margin_exact=str(Fraction(margin, denominator)),
                  margin=float(Fraction(margin, denominator)))
    result["metadata"].update({"internal_positive_mincut_numerator": int(mincut),
                               "negative_internal_sum_numerator": negative,
                               "positive_boundary_sum_numerator": boundary,
                               "mincut_partition": [sorted(side) for side in partition],
                               "elapsed_seconds": perf_counter() - started})
    return result
