"""Faithful sparse checks of named published criteria, not their full algorithms.

Supports symmetric nonnegative INTEGER adjacency, including quotient self-loops,
and rational nonnegative gamma. All decision arithmetic uses Python integers.
Each weak pair certificate is an alternative decision; recompute on the quotient
before composing weak contractions. Strict certificates hold in every optimum.
"""
from fractions import Fraction
from dataclasses import dataclass
from types import MappingProxyType
import numpy as np
from scipy import sparse


@dataclass(frozen=True, slots=True)
class PreparedIntegerGraph:
    """Copied immutable integer rows, shared by supplied-candidate baselines."""
    rows: tuple
    degrees: tuple
    volume: int

    @property
    def n(self):
        return len(self.rows)


def prepare_integer_graph(adjacency):
    if isinstance(adjacency, PreparedIntegerGraph):
        return adjacency
    rows, degrees, volume = _graph(adjacency)
    return PreparedIntegerGraph(tuple(MappingProxyType(row) for row in rows), tuple(degrees), volume)


def _graph(adjacency):
    if isinstance(adjacency, PreparedIntegerGraph):
        return adjacency.rows, adjacency.degrees, adjacency.volume
    a = sparse.csr_matrix(adjacency, copy=True)
    if a.shape[0] != a.shape[1] or a.shape[0] < 2:
        raise ValueError("need square adjacency with at least two vertices")
    if not a.has_canonical_format:
        raise ValueError("canonical CSR required; combine duplicate graph edges before this checker")
    if not np.all(np.isfinite(a.data)) or np.any(a.data < 0) or np.any(a.data != np.floor(a.data)):
        raise ValueError("criterion implementation requires nonnegative exact integer adjacency")
    if (a != a.T).nnz:
        raise ValueError("adjacency must be symmetric")
    a.eliminate_zeros()
    neighbors = [{int(v): int(weight) for v, weight in zip(a.indices[a.indptr[u]:a.indptr[u + 1]],
                                                          a.data[a.indptr[u]:a.indptr[u + 1]])}
                 for u in range(a.shape[0])]
    degree = [sum(row.values()) for row in neighbors]
    volume = sum(degree)
    if volume <= 0:
        raise ValueError("positive total volume required")
    return neighbors, degree, volume


def _parameter(gamma):
    gamma = Fraction(str(gamma))
    if gamma < 0:
        raise ValueError("nonnegative gamma required")
    return gamma


def singleton_dominance(adjacency, gamma="1", strict=True):
    """Lange2018 dominant-attractive edge criterion with singleton cuts.

    Tests either endpoint using c_uv >= sum_{w!=u,v}|c_uw|, with no
    dense modularity matrix. Only observed positive attractive edges are returned.
    O(n+m) arithmetic operations per pass; exact rational parameter arithmetic.
    """
    rows, degree, volume = _graph(adjacency)
    g = _parameter(gamma)
    p, q = g.numerator, g.denominator
    total_abs = []
    for u, row in enumerate(rows):
        du = degree[u]
        value = p * du * (volume - du)
        for v, weight in row.items():
            if v == u:
                continue
            null = p * du * degree[v]
            value += abs(q * volume * weight - null) - null
        total_abs.append(value)
    certified = []
    for u, row in enumerate(rows):
        for v, weight in row.items():
            if v <= u:
                continue
            cost = q * volume * weight - p * degree[u] * degree[v]
            if cost <= 0:
                continue
            margins = (2 * cost - total_abs[u], 2 * cost - total_abs[v])
            margin = max(margins)
            if margin > 0 or (not strict and margin == 0):
                certified.append({"u": u, "v": v, "margin_numerator": margin,
                                  "witness_endpoint": u if margins[0] >= margins[1] else v})
    return {"criterion": "Lange2018 dominant-attractive edge, singleton cuts",
            "gamma": str(g), "strict": strict, "coefficient_denominator": q * volume,
            "row_absolute_sum_numerators": total_abs, "safe_edges": certified,
            "algorithm_scope": "one criterion pass; not full Lange algorithm"}


def singleton_interval(adjacency, gamma_low, gamma_high, strict=True):
    """Same singleton cut must pass both endpoints of the requested interval.

    T_u(gamma)-2c_uv(gamma) is convex, so endpoint success certifies every
    intermediate gamma. Tests must share a witness; a union of different
    witnesses does not provide this argument.
    """
    low, high = _parameter(gamma_low), _parameter(gamma_high)
    if low > high:
        raise ValueError("resolution interval endpoints reversed")
    lo = singleton_dominance(adjacency, low, strict)
    hi = singleton_dominance(adjacency, high, strict)
    rows, degree, volume = _graph(adjacency)
    safe = []
    for u, row in enumerate(rows):
        for v, weight in row.items():
            if v <= u:
                continue
            margins = []
            for endpoint in (u, v):
                c_lo = low.denominator * volume * weight - low.numerator * degree[u] * degree[v]
                c_hi = high.denominator * volume * weight - high.numerator * degree[u] * degree[v]
                m_lo = 2 * c_lo - lo["row_absolute_sum_numerators"][endpoint]
                m_hi = 2 * c_hi - hi["row_absolute_sum_numerators"][endpoint]
                accepted = min(m_lo, m_hi) > 0 if strict else min(m_lo, m_hi) >= 0
                if c_hi > 0 and accepted:
                    margins.append((endpoint, m_lo, m_hi))
            if margins:
                endpoint, m_lo, m_hi = margins[0]
                safe.append({"u": u, "v": v, "witness_endpoint": endpoint,
                             "endpoint_margin_numerators": [m_lo, m_hi]})
    return {"criterion": "Lange2018 singleton dominance, exact convex endpoint interval check",
            "gamma_interval": [str(low), str(high)], "strict": strict, "safe_edges": safe,
            "algorithm_scope": "one criterion pass; not full Lange algorithm"}


def positive_closure_edge(adjacency, gamma="1", strict=True):
    """Lange2019 Appendix Theorem4, Eq21 single-edge positive closure.

    Uses positive observed-neighbor intersections. Does not implement triangle,
    general-subgraph search, reweighted ICP, or the full published algorithm.
    """
    rows, degree, volume = _graph(adjacency)
    g = _parameter(gamma)
    p, q = g.numerator, g.denominator
    positive = []
    for u, row in enumerate(rows):
        neighbors = {}
        for v, weight in row.items():
            if v == u:
                continue
            value = q * volume * weight - p * degree[u] * degree[v]
            if value > 0:
                neighbors[v] = value
        positive.append(neighbors)
    totals = [sum(row.values()) for row in positive]
    certified = []
    for u, row in enumerate(positive):
        for v, cost in row.items():
            if v <= u:
                continue
            small, other = (row, positive[v]) if len(row) <= len(positive[v]) else (positive[v], row)
            repayment = sum(min(value, other[w]) for w, value in small.items() if w in other)
            margin = 3 * cost - totals[u] - totals[v] + repayment
            if margin > 0 or (not strict and margin == 0):
                certified.append({"u": u, "v": v, "margin_numerator": margin,
                                  "common_positive_repayment_numerator": repayment})
    return {"criterion": "Lange2019 positive-closure edge, Appendix Theorem4 Eq21",
            "gamma": str(g), "strict": strict, "coefficient_denominator": q * volume,
            "safe_edges": certified, "algorithm_scope": "one criterion pass; not full Lange algorithm"}


def degree_proportional_twins(adjacency, gamma="1", strict=False):
    """SEA2022 weighted Twin Simple, modularity degree-proportional specialization.

    For observed uv with nonnegative B_uv and d_u,d_v>0, checks
    d_v*A_uw == d_u*A_vw for every outside w. The null model cancels
    exactly. This fixed proportional factor is a faithful sufficient subcase;
    arbitrary-factor generic Twin Simple may certify additional pairs.
    Returns merge-only components of these exact twin edges. No constraints
    on outside membership are added. At gamma=0 only observed pairs are
    screened, so zero-weight nonedge twins are not exhaustively searched.
    """
    rows, degree, volume = _graph(adjacency)
    g = _parameter(gamma)
    p, q = g.numerator, g.denominator
    parent = list(range(len(rows)))
    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    safe = []
    for u, row in enumerate(rows):
        if degree[u] == 0:
            continue
        for v, weight in row.items():
            if v <= u or degree[v] == 0:
                continue
            attraction = q * volume * weight - p * degree[u] * degree[v]
            if attraction < 0 or (strict and attraction == 0):
                continue
            union = set(row) | set(rows[v])
            union.discard(u)
            union.discard(v)
            if any(degree[v] * row.get(w, 0) != degree[u] * rows[v].get(w, 0) for w in union):
                continue
            safe.append({"u": u, "v": v, "attraction_numerator": attraction,
                         "exterior_ratio": str(Fraction(degree[u], degree[v]))})
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[rv] = ru
    components = {}
    for u in range(len(rows)):
        components.setdefault(find(u), []).append(u)
    return {"criterion": "SEA2022 weighted Twin Simple, degree-proportional modularity subcase",
            "gamma": str(g), "strict": strict, "coefficient_denominator": q * volume,
            "safe_edges": safe, "merge_groups": [c for c in components.values() if len(c) > 1],
            "algorithm_scope": "exact-profile merge-only criterion; not full KaPoCE Twin Simple algorithm"}
