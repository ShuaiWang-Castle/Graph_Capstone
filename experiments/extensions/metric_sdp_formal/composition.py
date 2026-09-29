"""Deterministic formal orchestration over immutable reviewed exact helpers.

Only run_composition is copied from the sealed parent. Mathematical helpers,
certificates, merge implementation and result type are imported unchanged.
The optional callback publishes a durable accepted prefix through caller I/O;
it provides neither a resumable timed job nor formal execution approval.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from time import perf_counter

import numpy as np

from experiments.extensions.metric_sdp.safe_composition import (
    CompositionResult, _bank, _degree_collective, _gamma, _json_exact, _limits,
    _mapped_bank, _merge, _signed, _to_csr, _weighted_collective,
    optimized_pair, prepare_exact_graph, prepare_graph,
    prepare_weighted_reference_graph, uniform_collective,
)


def run_composition(adjacency, original_bank, gamma=Fraction(1), *,
                    mode="S", max_graph_size=300, max_block_size=64, progress=None):
    """Run deterministic S/D/SD/SW; return actual CSR IDs and exact operation proof.

    S: all NONNEGATIVE signed pairs lexicographically, then mapped-bank blocks
    lexicographically. One accepted operation is merged, then all checks restart.
    D and W: the same original bank mapped/deduplicated BEFORE cap checks, with
    a fresh check and exact merge after each acceptance. SD/SW never return to S.
    Common signed-component presolve is owned by the downstream runtime.
    progress receives a detached accepted-operation event synchronously after
    exact merge/composed membership validation and before the next check.
    It does not choose candidates; exceptions propagate without a partial result.
    """
    started = perf_counter()
    graph, g = prepare_exact_graph(adjacency), _gamma(gamma)
    _limits(graph, max_graph_size, max_block_size)
    if mode not in {"S", "D", "SD", "SW"}:
        raise ValueError("mode must be S, D, SD or SW")
    if progress is not None and not callable(progress):
        raise TypeError("progress must be callable or None")
    bank = _bank(original_bank, graph.n)
    original = graph
    membership = list(range(graph.n))
    operations, phases, counts = [], [], Counter()
    seconds = {"preparation": perf_counter() - started, "checking": 0.0,
               "quotient": 0.0, "final_materialization": 0.0, "progress_callback": 0.0}
    sequence = ("S", "D") if mode == "SD" else ("S", "W") if mode == "SW" else (mode,)
    for stage in sequence:
        stage_n, stage_ops = graph.n, len(operations)
        while graph.n > 1:
            check_started = perf_counter()
            chosen, certificate, source_blocks = None, None, []
            if stage == "S":
                beta = g / graph.volume
                for u in range(graph.n):
                    for v in range(u + 1, graph.n):
                        if _signed(graph, u, v, beta) < 0:
                            continue
                        counts["pair_checks"] += 1
                        candidate = optimized_pair(graph, u, v, g)
                        if candidate["certified"]:
                            chosen, certificate = (u, v), candidate
                            break
                    if chosen is not None:
                        break
            if chosen is None:
                prepared = None
                for block, sources in _mapped_bank(bank, membership):
                    if len(block) > max_block_size:
                        counts[f"{stage}_mapped_cap_exclusions"] += 1
                        continue
                    counts[{"S": "uniform_checks", "D": "degree_checks",
                            "W": "weighted_checks"}[stage]] += 1
                    if stage == "S":
                        candidate = uniform_collective(graph, block, g,
                            max_graph_size=max_graph_size, max_block_size=max_block_size)
                    elif stage == "D":
                        if any(graph.degrees[u] <= 0 for u in block):
                            counts["D_zero_degree_exclusions"] += 1
                            continue
                        if prepared is None:
                            prepared = prepare_graph(_to_csr(graph))
                        candidate = _degree_collective(graph, block, g, max_block_size, prepared)
                    else:
                        if prepared is None:
                            prepared = prepare_weighted_reference_graph(graph)
                        candidate = _weighted_collective(prepared, block, g, max_block_size)
                    if not candidate.get("available", True):
                        counts[f"{stage}_unavailable_{candidate['status']}"] += 1
                    if candidate["certified"]:
                        chosen, certificate, source_blocks = block, candidate, sources
                        break
            if chosen is None:
                seconds["checking"] += perf_counter() - check_started
                break
            before = list(membership)
            operation = {"index": len(operations), "stage": stage,
                         "current_n_before": graph.n, "block_current": list(chosen),
                         "original_groups_before": [[u for u, c in enumerate(before) if c == v]
                                                    for v in chosen],
                         "original_bank_blocks": [list(x) for x in source_blocks],
                         "original_membership_before": before,
                         "current_graph_sha256": graph.fingerprint,
                         "gamma_exact": str(g), "S_exact": str(graph.volume),
                         "block_volume_exact": str(sum((graph.degrees[v] for v in chosen), Fraction())),
                         "certificate": _json_exact(certificate)}
            seconds["checking"] += perf_counter() - check_started
            quotient_started = perf_counter()
            graph, old_to_new = _merge(graph, chosen)
            membership = [old_to_new[c] for c in before]
            expected = [sum((original.degrees[u] for u, c in enumerate(membership) if c == v),
                            Fraction()) for v in range(graph.n)]
            if tuple(expected) != graph.degrees or graph.volume != original.volume:
                raise ArithmeticError("composed original membership changed exact degrees or S")
            operation.update(current_n_after=graph.n, old_to_new_membership=old_to_new,
                             original_membership_after=list(membership),
                             quotient_graph_sha256=graph.fingerprint,
                             quotient_degrees_exact=list(map(str, graph.degrees)))
            operations.append(operation)
            counts[f"{stage}_accepted_operations"] += 1
            seconds["quotient"] += perf_counter() - quotient_started
            if progress is not None:
                callback_started = perf_counter()
                try:
                    event = {"kind": "accepted_operation", "mode": mode,
                             "operation": _json_exact(operation),
                             "counts_snapshot": dict(counts),
                             "completed_phases": _json_exact(phases)}
                    progress(event)
                finally:
                    # Included in the caller's outer safe_composition cost.
                    # This diagnostic subset must not be summed a second time.
                    seconds["progress_callback"] += perf_counter() - callback_started
        phases.append({"stage": stage, "start_n": stage_n, "end_n": graph.n,
                       "accepted_operations": len(operations) - stage_ops, "fixed_point": True})
    materialize_started = perf_counter()
    final = _to_csr(graph)
    groups = tuple(tuple(u for u, c in enumerate(membership) if c == v) for v in range(graph.n))
    mapping = np.asarray(membership, dtype=np.int64)
    mapping.flags.writeable = False
    seconds["final_materialization"] = perf_counter() - materialize_started
    metadata = {"schema": "plain-metric-sdp-safe-composition-progress-v1", "mode": mode,
                "gamma_exact": str(g), "original_S_exact": str(original.volume),
                "original_n": original.n, "final_n": graph.n,
                "original_graph_sha256": original.fingerprint,
                "quotient_graph_sha256": graph.fingerprint,
                "original_bank": [list(x) for x in bank],
                "counts": dict(counts), "phases": phases,
                "stage_seconds": seconds, "outer_call_seconds": perf_counter() - started,
                "progress_callback_seconds": seconds["progress_callback"],
                "progress_policy": "synchronous detached post-validation operation event; caller owns durable I/O",
                "exact_block_cap": max_block_size, "graph_cap": max_graph_size,
                "pair_policy": "ALL B_uv>=0, lower weighted median, lexicographic sequential restart",
                "bank_policy": "original bank mapped/deduplicated before cap; lexicographic; no resampling",
                "weak_policy": "one current-quotient merge and full restart; no original weak union",
                "quotient_identity": "A_next=R.T A_current R; loops retain doubled internal mass",
                "objective_identity_verified": True,
                "scope": "derived relaxed-safe S/D/SD/SW, not generic discrete R or full published methods"}
    return CompositionResult(graph, final, mapping, groups, graph.degrees, graph.volume,
                             tuple(operations), metadata)
