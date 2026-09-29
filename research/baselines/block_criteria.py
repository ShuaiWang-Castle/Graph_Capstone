"""Capped exact tests on supplied blocks, with explicit theorem-to-code scope.

Lange's positive-closure test is the published *pair* criterion. Whole-block
acceptance below requires strict certificates for a predeclared spanning star;
independent weak pairs are reported, never unioned. The uniform-copy reference
is a project-derived certificate, not an attributed published algorithm.
"""
from collections import deque
from fractions import Fraction
from numbers import Integral
from time import perf_counter

import numpy as np

try:
    from .sparse_criteria import PreparedIntegerGraph, _graph, _parameter
except ImportError:
    from sparse_criteria import PreparedIntegerGraph, _graph, _parameter


def _vertices(block, n):
    values = tuple(block)
    if len(values) < 2 or any(not isinstance(u, Integral) for u in values):
        raise ValueError("a block needs at least two integer vertices")
    values = tuple(int(u) for u in values)
    if len(set(values)) != len(values) or any(u < 0 or u >= n for u in values):
        raise ValueError("block vertices must be distinct and inside the graph")
    return values


def _cut_capacity(n, edges, source, sink):
    """Dinic on undirected Python-integer capacities; no float flow solver."""
    graph = [[] for _ in range(n)]
    for u, v, capacity in edges:
        if capacity <= 0:
            continue
        # A pair of initially positive reverse arcs models one undirected edge.
        iu, iv = len(graph[u]), len(graph[v])
        graph[u].append([v, iv, capacity])
        graph[v].append([u, iu, capacity])
    flow = 0
    infinity = sum(c for _, _, c in edges) + 1
    while True:
        level = [-1] * n
        level[source] = 0
        queue = deque([source])
        while queue:
            u = queue.popleft()
            for v, _, capacity in graph[u]:
                if capacity > 0 and level[v] < 0:
                    level[v] = level[u] + 1
                    queue.append(v)
        if level[sink] < 0:
            return flow, [u for u, distance in enumerate(level) if distance >= 0]
        cursor = [0] * n
        def augment(u, limit):
            if u == sink:
                return limit
            while cursor[u] < len(graph[u]):
                edge = graph[u][cursor[u]]
                v, reverse, capacity = edge
                if capacity > 0 and level[v] == level[u] + 1:
                    amount = augment(v, min(limit, capacity))
                    if amount:
                        edge[2] -= amount
                        graph[v][reverse][2] += amount
                        return amount
                cursor[u] += 1
            return 0
        while True:
            amount = augment(source, infinity)
            if not amount:
                break
            flow += amount


def _signed_cut_enumeration(internal, columns):
    """All nontrivial K cuts, anchor fixed left; boundary sides minimized.

    The internal multicut-zero premise is equivalent to every internal binary
    cut being nonnegative: a multicut cost is half the sum of its component cuts.
    Gray-code updates retain exact integer capacities.
    """
    k = len(internal)
    side = [True] + [False] * (k - 1)
    internal_cut = sum(internal[0][1:])
    totals = [sum(column) for column in columns]
    left = [column[0] for column in columns]
    min_internal = None
    min_pairs = [None] * (k - 1)
    witnesses = [None] * (k - 1)
    count = 0
    previous = 0
    for step in range(1 << (k - 1)):
        mask = step ^ (step >> 1)
        if step:
            changed = (mask ^ previous).bit_length()
            was_left = side[changed]
            internal_cut += sum(internal[changed][j] * (1 if side[j] == was_left else -1)
                                for j in range(k) if j != changed)
            direction = -1 if was_left else 1
            for index, column in enumerate(columns):
                left[index] += direction * column[changed]
            side[changed] = not was_left
        previous = mask
        if all(side):
            continue
        count += 1
        if min_internal is None or internal_cut < min_internal:
            min_internal = internal_cut
        closure_cut = internal_cut + sum(min(value, total - value) for value, total in zip(left, totals))
        for target in range(1, k):
            if not side[target] and (min_pairs[target - 1] is None or closure_cut < min_pairs[target - 1]):
                min_pairs[target - 1] = closure_cut
                witnesses[target - 1] = [i for i, included in enumerate(side) if included]
    return min_internal, min_pairs, witnesses, count


def positive_closure_block(adjacency, block, gamma="1", *, max_block_size=64,
                           max_closure_vertices=128, signed_enumeration_max_size=16):
    """Lange2019 Appendix Theorem4 Eq19 on predeclared star pairs in K.

    H is the full induced signed modularity graph on K, including zero edges.
    Its positive closure retains all positive K--outside edges and no
    outside--outside edges. Eq21 is only the single-edge special case.

    With nonnegative internal weights, min_MC(H)=0 is immediate and exact
    terminal mincuts check Eq19. Signed H uses capped exact cut enumeration,
    also checking the min_MC(H)=0 premise. Whole K is accepted only if every
    predeclared pair has a *strict* inequality; weak results stay individual.
    """
    if max_block_size < 2 or max_closure_vertices < 2 or signed_enumeration_max_size < 2:
        raise ValueError("all size caps must be at least two")
    started = perf_counter()
    rows, degree, volume = _graph(adjacency)
    vertices = _vertices(block, len(rows))
    g = _parameter(gamma)
    denominator = g.denominator * volume
    base = {"criterion": "Lange2019 positive-closure pair criterion on a supplied spanning star, Appendix Theorem4 Eq19",
            "block": list(vertices), "gamma": str(g), "certified": False, "strict": False,
            "available": True, "margin": None, "margin_exact": None, "verification_status": None,
            "safe_pairs": [], "pair_results": [], "coefficient_denominator": denominator,
            "metadata": {"algorithm_scope": "supplied-candidate criterion; not full Lange algorithm",
                         "published_guarantee": "one target pair in some optimum",
                         "block_acceptance": "all predeclared star pairs strictly certified, hence true in every optimum",
                         "weak_composition": "individual only; never unioned",
                         "max_block_size": max_block_size, "max_closure_vertices": max_closure_vertices,
                         "signed_enumeration_max_size": signed_enumeration_max_size}}
    def finish(status, available=True):
        base["verification_status"] = status
        base["available"] = available
        base["metadata"]["elapsed_seconds"] = perf_counter() - started
        return base
    if len(vertices) > max_block_size:
        return finish("block_size_limit", False)
    p, q = g.numerator, g.denominator
    k = len(vertices)
    inside = set(vertices)
    internal = [[0] * k for _ in vertices]
    for i, u in enumerate(vertices):
        for j in range(i + 1, k):
            v = vertices[j]
            internal[i][j] = internal[j][i] = q * volume * rows[u].get(v, 0) - p * degree[u] * degree[v]
    boundary = {}
    for i, u in enumerate(vertices):
        for w, weight in rows[u].items():
            if w in inside:
                continue
            cost = q * volume * weight - p * degree[u] * degree[w]
            if cost > 0:
                boundary.setdefault(w, [0] * k)[i] = cost
    boundary_nodes = sorted(boundary)
    columns = [boundary[w] for w in boundary_nodes]
    closure_size = k + len(columns)
    threshold = sum(map(sum, columns))
    base["metadata"].update({"closure_vertices": closure_size,
                             "positive_boundary_sum_numerator": threshold,
                             "predeclared_pairs": [[vertices[0], u] for u in vertices[1:]]})
    if closure_size > max_closure_vertices:
        return finish("positive_closure_size_limit", False)
    negative_internal = any(internal[i][j] < 0 for i in range(k) for j in range(i + 1, k))
    if negative_internal:
        if k > signed_enumeration_max_size:
            return finish("signed_internal_enumeration_size_limit", False)
        minimum, cuts, witnesses, count = _signed_cut_enumeration(internal, columns)
        base["metadata"].update({"cut_backend": "all exact signed binary cuts with independent boundary-side minimization",
                                 "enumerated_internal_cuts": count,
                                 "minimum_internal_cut_numerator": minimum,
                                 "internal_multicut_zero_premise": minimum >= 0})
        if minimum < 0:
            return finish("failed_internal_multicut_zero_premise")
    else:
        edges = [(i, j, internal[i][j]) for i in range(k) for j in range(i + 1, k) if internal[i][j] > 0]
        for index, column in enumerate(columns):
            edges.extend((i, k + index, capacity) for i, capacity in enumerate(column) if capacity > 0)
        cuts, witnesses = [], []
        for target in range(1, k):
            capacity, side = _cut_capacity(closure_size, edges, 0, target)
            cuts.append(capacity)
            witnesses.append([i for i in side if i < k])
        base["metadata"].update({"cut_backend": "exact Python-integer Dinic terminal mincuts",
                                 "internal_multicut_zero_premise": "all internal coefficients nonnegative",
                                 "terminal_flow_calls": k - 1})
    margins = [capacity - threshold for capacity in cuts]
    for index, (capacity, margin, witness) in enumerate(zip(cuts, margins, witnesses), 1):
        record = {"u": vertices[0], "v": vertices[index], "certified": margin >= 0,
                  "strict": margin > 0, "minimum_separating_closure_cut_numerator": capacity,
                  "margin_numerator": margin, "margin_exact": str(Fraction(margin, denominator)),
                  "witness_K_side": [vertices[i] for i in witness]}
        base["pair_results"].append(record)
        if margin >= 0:
            base["safe_pairs"].append(record)
    minimum_margin = min(margins)
    base["margin_exact"] = str(Fraction(minimum_margin, denominator))
    base["margin"] = float(Fraction(minimum_margin, denominator))
    base["certified"] = base["strict"] = all(margin > 0 for margin in margins)
    if base["certified"]:
        return finish("verified_all_spanning_pairs_strict")
    return finish("weak_pairs_reported_individually" if minimum_margin >= 0 else "failed_spanning_pair_condition")


def _exact_psd(matrix):
    """Independent rational Schur elimination; a zero PSD pivot needs zero row."""
    a = [row.copy() for row in matrix]
    positive = zero = 0
    for i in range(len(a)):
        pivot = a[i][i]
        if pivot < 0:
            return False, False, {"positive_pivots": positive, "zero_pivots": zero,
                                  "obstruction": "negative Schur pivot", "position": i}
        if pivot == 0:
            if any(a[i][j] != 0 for j in range(i + 1, len(a))):
                return False, False, {"positive_pivots": positive, "zero_pivots": zero,
                                      "obstruction": "zero pivot with nonzero residual row", "position": i}
            zero += 1
            continue
        positive += 1
        for j in range(i + 1, len(a)):
            factor = a[j][i] / pivot
            for h in range(j, len(a)):
                a[j][h] -= factor * a[i][h]
                a[h][j] = a[j][h]
    return True, zero == 0, {"positive_pivots": positive, "zero_pivots": zero, "obstruction": None}


def uniform_copy_contrast(adjacency, block, gamma="1", *, exact_max_size=64,
                          diagnostic_max_size=128, max_graph_size=150, max_exterior_size=150):
    """Project-derived uniform anchor-copy pair-contrast spectral reference.

    D_uv=sum_outside |B_uw-B_vw|, C_uv=B_uv-D_uv/k. Acceptance is exact
    PSD of L(C) on ones-perp; a float eigenvalue is diagnostic only. This dense
    exterior reference is deliberately unavailable beyond the explicit caps.
    It is not a published Lange/KaPoCE method and has no sparse scaling claim.
    """
    if min(exact_max_size, diagnostic_max_size, max_graph_size) < 2 or max_exterior_size < 0:
        raise ValueError("invalid graph/block/exterior size caps")
    started = perf_counter()
    n = adjacency.n if isinstance(adjacency, PreparedIntegerGraph) else np.shape(adjacency)[0]
    vertices = _vertices(block, n)
    g = _parameter(gamma)
    result = {"criterion": "uniform anchor-copy pair-contrast Laplacian reference (project-derived)",
              "block": list(vertices), "gamma": str(g), "certified": False, "strict": False,
              "available": True, "margin": None, "verification_status": None,
              "metadata": {"algorithm_scope": "small supplied-candidate reference, no published full-method attribution",
                           "acceptance_arithmetic": "exact Fraction symmetric Schur elimination",
                           "diagnostic_arithmetic": "unvalidated float64 restricted eigenvalue",
                           "exact_max_size": exact_max_size, "diagnostic_max_size": diagnostic_max_size,
                           "max_graph_size": max_graph_size, "max_exterior_size": max_exterior_size}}
    def finish(status, available=True):
        result["verification_status"] = status
        result["available"] = available
        result["metadata"]["elapsed_seconds"] = perf_counter() - started
        return result
    if n > max_graph_size:
        return finish("graph_size_limit", False)
    if n - len(vertices) > max_exterior_size:
        return finish("exterior_dimension_limit", False)
    if len(vertices) > max(exact_max_size, diagnostic_max_size):
        return finish("block_dimension_limit", False)
    rows, degree, volume = _graph(adjacency)
    inside = set(vertices)
    outside = [w for w in range(n) if w not in inside]
    exterior = [[Fraction(rows[u].get(w, 0)) - g * degree[u] * degree[w] / volume
                 for w in outside] for u in vertices]
    k = len(vertices)
    matrix = [[Fraction() for _ in vertices] for _ in vertices]
    contrast_max = Fraction()
    for i, u in enumerate(vertices):
        for j in range(i + 1, k):
            v = vertices[j]
            difference = sum((abs(left - right) for left, right in zip(exterior[i], exterior[j])), Fraction())
            contrast_max = max(contrast_max, difference)
            weight = Fraction(rows[u].get(v, 0)) - g * degree[u] * degree[v] / volume - difference / k
            matrix[i][i] += weight
            matrix[j][j] += weight
            matrix[i][j] = matrix[j][i] = -weight
    result["metadata"].update({"dense_exterior_entries": k * len(outside),
                               "contrast_pair_entries": k * (k - 1) // 2,
                               "max_pair_contrast_exact": str(contrast_max)})
    # The last vertex is a deterministic pivot: columns e_i-e_p span ones-perp.
    pivot = k - 1
    reduced = [[matrix[i][j] - matrix[i][pivot] - matrix[pivot][j] + matrix[pivot][pivot]
                for j in range(k - 1)] for i in range(k - 1)]
    if k <= diagnostic_max_size:
        try:
            diagnostic = np.asarray([[float(x) for x in row] for row in matrix])
            vector = np.ones(k) / np.sqrt(k)
            vector[pivot] += 1
            householder = np.eye(k) - 2 * np.outer(vector, vector) / (vector @ vector)
            basis = np.delete(householder, pivot, axis=1)
            projected = basis.T @ diagnostic @ basis
            result["margin"] = float(np.linalg.eigvalsh((projected + projected.T) / 2)[0])
        except (OverflowError, np.linalg.LinAlgError):
            result["metadata"]["diagnostic_error"] = "floating conversion or eigensolve failed; exact path unaffected"
    if k > exact_max_size:
        return finish("exact_block_size_limit", False)
    accepted, strict, elimination = _exact_psd(reduced)
    result["certified"], result["strict"] = accepted, strict
    result["metadata"]["exact_elimination"] = elimination
    return finish(("verified_positive_definite" if strict else "verified_positive_semidefinite")
                  if accepted else "failed_exact_psd")
