"""Recursive pure-merge composition of explicitly named exact criteria.

Each round uses the current unrestricted modularity quotient at the same gamma:
strict singleton dominance, strict positive-closure edges, compatible weak
degree-proportional twin classes, and STRICT Böcker Rule4 on the original fixed
bank mapped to current vertex IDs. Generic weak block certificates are never
unioned. This is not the full Lange, Böcker candidate search or KaPoCE algorithm.

Strict decisions hold in every current optimum. The audited exact-profile twin
classes have a jointly fused optimum; that optimum also respects all strict
decisions. Hence their union preserves at least one optimum. Exact merge
quotients preserve the objective of every lifted partition, so recomputation
maintains this property inductively. All rounds containing changes strictly
decrease n; there is no artificial round limit and no cannot-link constraint.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import json
from numbers import Integral
from time import perf_counter
from types import MappingProxyType

from .almost_clique import almost_clique
from .sparse_criteria import (
    PreparedIntegerGraph, _parameter, degree_proportional_twins,
    positive_closure_edge, prepare_integer_graph, singleton_dominance,
)


def _checked_snapshot(adjacency):
    """Copy cached rows too, validating their degree/volume assumptions once."""
    graph = prepare_integer_graph(adjacency)
    n = graph.n
    rows = []
    for row in graph.rows:
        copied = {}
        for v, weight in row.items():
            if not isinstance(v, Integral) or not 0 <= v < n:
                raise ValueError("cached graph contains an invalid neighbor index")
            if not isinstance(weight, Integral) or weight < 0:
                raise ValueError("cached graph must contain exact nonnegative integer weights")
            if weight:
                copied[int(v)] = int(weight)
        rows.append(copied)
    if any(rows[v].get(u, 0) != weight for u, row in enumerate(rows) for v, weight in row.items()):
        raise ValueError("cached graph must be exactly symmetric")
    degrees = tuple(sum(row.values()) for row in rows)
    volume = sum(degrees)
    if degrees != tuple(graph.degrees) or volume != graph.volume or volume <= 0:
        raise ValueError("cached graph degree/volume values do not match its exact rows")
    return PreparedIntegerGraph(tuple(MappingProxyType(row) for row in rows), degrees, volume)


def _exact_quotient(graph, groups):
    """A'=R.T A R entirely in Python integers, including diagonal mass."""
    membership = [None] * graph.n
    for new, group in enumerate(groups):
        for old in group:
            if membership[old] is not None:
                raise ArithmeticError("quotient groups overlap")
            membership[old] = new
    if any(label is None for label in membership):
        raise ArithmeticError("quotient groups omit a current vertex")
    rows = [{} for _ in groups]
    for u, row in enumerate(graph.rows):
        target = rows[membership[u]]
        for v, weight in row.items():
            column = membership[v]
            target[column] = target.get(column, 0) + weight
    degrees = tuple(sum(row.values()) for row in rows)
    expected = tuple(sum(graph.degrees[u] for u in group) for group in groups)
    if degrees != expected or sum(degrees) != graph.volume:
        raise ArithmeticError("exact quotient changed degree sums or total mass")
    if any(rows[v].get(u, 0) != weight for u, row in enumerate(rows) for v, weight in row.items()):
        raise ArithmeticError("exact quotient lost symmetry")
    quotient = PreparedIntegerGraph(tuple(MappingProxyType(row) for row in rows), degrees, graph.volume)
    return quotient, membership


def _content_hash(graph):
    entries = [(u, v, weight) for u, row in enumerate(graph.rows) for v, weight in sorted(row.items()) if v >= u]
    payload = json.dumps({"n": graph.n, "adjacency_upper_including_diagonal": entries}, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def recursive_cheap(adjacency, candidate_blocks, gamma=Fraction(1), *,
                    max_block_size=64, include_round_decisions=False):
    """Recompute named merge criteria to a fixed point on exact quotients.

    The candidate bank remains the supplied original bank. Mapping can make an
    originally oversized candidate admissible after earlier safe contractions;
    mapped duplicates and trivial blocks are counted explicitly. Each Böcker
    check is strict. Exact-profile twin components are the sole weak union and
    use their audited compatibility property. No finite gamma interval or full
    published solver is claimed by this fixed-gamma composite baseline.
    """
    if not isinstance(max_block_size, Integral) or not 2 <= max_block_size <= 64:
        raise ValueError("max_block_size must be an integer in 2..64")
    started = perf_counter()
    preparation_started = perf_counter()
    graph = _checked_snapshot(adjacency)
    original_n = graph.n
    preparation_seconds = perf_counter() - preparation_started
    resolution = _parameter(gamma)
    bank = []
    for supplied in candidate_blocks:
        block = tuple(supplied)
        if any(not isinstance(u, Integral) or not 0 <= u < original_n for u in block):
            raise ValueError("candidate bank refers to invalid original vertices")
        bank.append(tuple(sorted(set(map(int, block)))))
    bank_payload = json.dumps(bank, separators=(",", ":")).encode()
    original_graph_hash = _content_hash(graph)
    original_to_current = list(range(original_n))
    original_members = [(u,) for u in range(original_n)]
    rounds = []
    weak_used = False
    status = "fixed_point"
    while graph.n >= 2:
        round_started = perf_counter()
        n = graph.n
        parent = list(range(n))
        def find(u):
            while parent[u] != u:
                parent[u] = parent[parent[u]]
                u = parent[u]
            return u
        def unite(group):
            if len(group) < 2:
                return
            root = find(group[0])
            for u in group[1:]:
                parent[find(u)] = root
        statistics = {"round": len(rounds), "input_vertices": n,
                      "input_volume_exact": graph.volume, "criteria": {}}
        decisions = {}
        for name, function in (("singleton_dominance", singleton_dominance),
                               ("positive_closure_edge", positive_closure_edge)):
            criterion_started = perf_counter()
            result = function(graph, resolution, strict=True)
            for edge in result["safe_edges"]:
                unite((edge["u"], edge["v"]))
            statistics["criteria"][name] = {"strict": True, "decision_count": len(result["safe_edges"]),
                "criterion": result["criterion"], "seconds": perf_counter() - criterion_started}
            if include_round_decisions:
                decisions[name] = result["safe_edges"]
        criterion_started = perf_counter()
        twins = degree_proportional_twins(graph, resolution, strict=False)
        for group in twins["merge_groups"]:
            unite(group)
        weak_used |= bool(twins["merge_groups"])
        statistics["criteria"]["degree_proportional_twins"] = {
            "strict": False, "decision_count": len(twins["safe_edges"]),
            "compatible_component_count": len(twins["merge_groups"]), "criterion": twins["criterion"],
            "composition": "audited compatible exact-profile components; not generic weak-edge union",
            "seconds": perf_counter() - criterion_started}
        if include_round_decisions:
            decisions["degree_proportional_twins"] = twins["merge_groups"]
        mapping_started = perf_counter()
        mapped = [tuple(sorted({original_to_current[u] for u in block})) for block in bank]
        trivial = sum(len(block) < 2 for block in mapped)
        nontrivial = [block for block in mapped if len(block) >= 2]
        unique = sorted(set(nontrivial), key=lambda block: (len(block), block))
        oversized = [block for block in unique if len(block) > max_block_size]
        admissible = [block for block in unique if len(block) <= max_block_size]
        statistics["mapped_bank"] = {"original_block_count": len(bank), "trivial_block_count": trivial,
            "duplicate_nontrivial_blocks_removed": len(nontrivial) - len(unique),
            "unique_nontrivial_blocks": len(unique), "admissible_block_count": len(admissible),
            "current_size_cap_exclusions": len(oversized),
            "excluded_current_sizes": dict(Counter(map(len, oversized))),
            "max_block_size": int(max_block_size), "mapping_seconds": perf_counter() - mapping_started}
        criterion_started = perf_counter()
        accepted_blocks = []
        outcomes = Counter()
        for block in admissible:
            result = almost_clique(graph, block, resolution, max_block_size=max_block_size, strict=True)
            outcomes[result["verification_status"]] += 1
            if result["certified"]:
                if not result["strict"]:
                    raise ArithmeticError("Weak almost-clique blocks must not be unioned")
                accepted_blocks.append(block)
                unite(block)
        statistics["criteria"]["bocker_almost_clique"] = {
            "strict": True, "decision_count": len(accepted_blocks), "candidate_count": len(admissible),
            "status_counts": dict(outcomes), "criterion": "Bocker2011 Rule4 on original fixed bank mapped to current quotient",
            "seconds": perf_counter() - criterion_started}
        if include_round_decisions:
            decisions["bocker_almost_clique"] = [list(block) for block in accepted_blocks]
            statistics["decisions_current_vertex_ids"] = decisions
        components = {}
        for u in range(n):
            components.setdefault(find(u), []).append(u)
        groups = sorted(components.values(), key=lambda group: group[0])
        removed = n - len(groups)
        statistics.update({"removed_vertices": removed, "remaining_vertices": len(groups),
                           "quotient_seconds": 0.0, "objective_domain": "unrestricted current quotient; no cannot-link fixes"})
        if not removed:
            statistics["round_seconds"] = perf_counter() - round_started
            rounds.append(statistics)
            break
        quotient_started = perf_counter()
        graph, membership = _exact_quotient(graph, groups)
        new_members = [tuple(sorted(u for old in group for u in original_members[old])) for group in groups]
        original_to_current = [membership[old] for old in original_to_current]
        original_members = new_members
        statistics["quotient_seconds"] = perf_counter() - quotient_started
        statistics["exact_degree_total_identity_verified"] = True
        statistics["round_seconds"] = perf_counter() - round_started
        rounds.append(statistics)
        if graph.n == 1:
            status = "fully_contracted"
    result = {"method": "recursive composition of named cheap merge criteria",
            "status": status, "available": True, "certified": True, "strict": not weak_used,
            "gamma_exact": str(resolution), "input_vertices": original_n, "remaining_vertices": graph.n,
            "removed_vertices": original_n - graph.n,
            "merge_groups": [list(group) for group in original_members if len(group) > 1],
            "original_membership": original_to_current,
            "round_count": len(rounds), "merge_round_count": sum(r["removed_vertices"] > 0 for r in rounds),
            "round_stats": rounds, "preparation_seconds": preparation_seconds,
            "metadata": {"algorithm_scope": "recursive named-criterion composition; not full Lange/Bocker/KaPoCE",
                "full_kapoce_solver": False, "arithmetic": "Python integers and Fraction parameters, exact merge quotient each round",
                "quotient_identity": "A_next=R.T A_current R including doubled internal edge mass on diagonal",
                "original_graph_sha256": original_graph_hash, "final_quotient_sha256": _content_hash(graph),
                "original_bank_sha256": hashlib.sha256(bank_payload).hexdigest(),
                "total_volume_exact": graph.volume, "max_block_size": int(max_block_size),
                "round_limit": None, "termination": "every nonterminal changed round strictly decreases vertex count",
                "bank_policy": "same original bank mapped/deduplicated on each current quotient; no candidate generation",
                "weak_composition": "only compatible degree-proportional profile components; no weak Bocker block union",
                "cannot_link_constraints": False, "weak_twin_components_used": weak_used,
                "guarantee": "a compatible fused optimum exists" if weak_used else "every optimum respects the merge groups"}}
    result["elapsed_seconds"] = perf_counter() - started
    return result
