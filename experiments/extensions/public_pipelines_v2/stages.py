"""Fresh U/D/R/RD stages using unchanged discovery, criteria and core quotients."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import time

import networkx as nx

from degree_contraction import certify_block, contract_certified_blocks, prepare_graph, quotient_adjacency
from experiments.candidates import candidate_bank
from experiments.pipeline import graph_adjacency, networkx_quotient
from research.baselines.recursive_cheap import recursive_cheap

from .contracts import (ARM_PHASES, ARMS, ArmState, FixedBank, MappedBank, OriginalContext,
                        canonical_partition, compose_membership, content_hash, groups_from_membership,
                        integer_labels)
from .integer_objective import prepare_integer_objective, validate_quotient


def bank_identity(blocks):
    # Exactly the archived v1 identity convention, without an added newline.
    return hashlib.sha256(json.dumps(blocks, separators=(",", ":")).encode("utf-8")).hexdigest()


def prepare_original(graph, metadata, *, expected_metadata=None):
    if set(graph) != set(range(len(graph))):
        raise ValueError("original graph vertices must follow the fixed consecutive order")
    if expected_metadata is not None and metadata != expected_metadata:
        raise ValueError("processed full dataset metadata differs from v1")
    adjacency = graph_adjacency(graph)
    objective = prepare_integer_objective(adjacency)
    component = tuple(sorted(max(nx.connected_components(graph), key=lambda g: (len(g), -min(g)))))
    if metadata.get("n", len(graph)) != len(graph) or metadata.get("m", graph.number_of_edges()) != graph.number_of_edges():
        raise ValueError("original full-graph counts disagree with processing metadata")
    return OriginalContext(nx.freeze(graph), objective.adjacency, objective, dict(metadata), component,
                           tuple(range(len(graph))))


def build_fixed_bank(context, discovery_seed, ledger, *, archived_record=None, clock=time.perf_counter, progress=None):
    start = clock()
    result = candidate_bank(context.graph, seed=discovery_seed, resolution=1.0, minimum_size=2)
    B = clock() - start
    diagnostics = ledger.attribute_candidate_call(B, result.refinement_seconds, result.proposal_seconds)
    attempt = {} if progress is None else progress.setdefault("fixed_bank_attempt", {})
    with ledger.measure("common_discovery"):
        labels = integer_labels(result.discovery_labels, context.objective.n)
        attempt["discovery_labels"] = list(labels)
        if archived_record is not None and list(labels) != archived_record["discovery_labels"]:
            raise ValueError("regenerated discovery labels differ from archived independent v1 labels")
        partition_hash = content_hash(canonical_partition(labels))
    with ledger.measure("fixed_bank_refinement"):
        blocks = tuple(integer_labels(block) for block in result.blocks)
        attempt.update(blocks=[list(block) for block in blocks], candidate_call_diagnostics=diagnostics)
        if any(len(block) < 2 or tuple(sorted(set(block))) != block
               or min(block) < 0 or max(block) >= context.objective.n for block in blocks):
            raise ValueError("complete original bank has invalid vertex entries")
        identity = bank_identity(blocks)
        if archived_record is not None:
            if identity != archived_record["bank_sha256"] or [list(block) for block in blocks] != archived_record["blocks"]:
                raise ValueError("regenerated complete forest differs from the archived independent v1 bank")
            if archived_record["seed"] != discovery_seed or archived_record["dataset"] != context.metadata:
                raise ValueError("archived original bank belongs to another seed/dataset")
        source_record = {"seed": int(discovery_seed), "bank_sha256": identity,
                         "blocks": [list(block) for block in blocks], "discovery_labels": list(labels),
                         "discovery_partition_sha256": partition_hash,
                         "spectral_splits": int(result.spectral_splits), "component_splits": int(result.component_splits),
                         "fallback_splits": int(result.fallback_splits), "candidate_count": len(blocks),
                         "sizes": dict(Counter(map(len, blocks))), "dataset": context.metadata,
                         "archived_v1_identity_equality_verified": archived_record is not None,
                         "candidate_call_diagnostics": diagnostics}
        bank = FixedBank(blocks, labels, identity, source_record)
    return bank


def map_original_bank(blocks, membership, discovery_labels, *, max_block_size=64):
    membership = integer_labels(membership)
    discovery_labels = integer_labels(discovery_labels, len(membership))
    groups = groups_from_membership(membership)
    linked = {}
    for index, supplied in enumerate(blocks):
        block = integer_labels(supplied)
        if any(u < 0 or u >= len(membership) for u in block) or len(set(block)) != len(block):
            raise ValueError("original bank mapping received invalid vertices")
        image = tuple(sorted({membership[u] for u in block}))
        linked.setdefault(image, []).append((index, block))
    entries = []
    for image, origins in sorted(linked.items(), key=lambda item: (len(item[0]), item[0])):
        expanded = tuple(sorted(u for v in image for u in groups[v]))
        communities = sorted({discovery_labels[u] for u in expanded})
        entries.append({"current_block": list(image), "current_size": len(image),
                        "original_bank_indices": [index for index, _ in origins],
                        "original_sizes": [len(block) for _, block in origins], "multiplicity": len(origins),
                        "original_source_union_size": len({u for _, block in origins for u in block}),
                        "expanded_original_vertices": list(expanded), "expanded_original_size": len(expanded),
                        "discovery_communities": communities, "crosses_discovery_communities": len(communities) > 1,
                        "classification": "trivial_image" if len(image) < 2 else
                                          "exact_size_limit_preassembly" if len(image) > max_block_size else "admissible"})
    nontrivial = tuple(tuple(record["current_block"]) for record in entries if record["current_size"] >= 2)
    trivial_count = sum(record["multiplicity"] for record in entries if record["current_size"] < 2)
    nontrivial_count = len(blocks) - trivial_count
    summary = {"complete_original_bank_count": len(blocks), "trivial_original_image_count": trivial_count,
               "unique_nontrivial_images": len(nontrivial),
               "duplicate_nontrivial_images_removed": nontrivial_count - len(nontrivial),
               "current_cap_exclusions": sum(record["current_size"] > max_block_size for record in entries),
               "admissible_current_images": sum(record["classification"] == "admissible" for record in entries),
               "max_block_size": max_block_size, "cap_applied_after_complete_original_bank_mapping": True}
    return MappedBank(nontrivial, tuple(entries), summary)


def run_recursive_prefix(adjacency, blocks, gamma):
    return recursive_cheap(adjacency, blocks, gamma, max_block_size=64, include_round_decisions=False)


def run_degree_stage(adjacency, blocks, gamma):
    """Every decision is on this one fixed fresh PreparedGraph; no float accepts."""
    prepared = prepare_graph(adjacency)
    certificates, decisions = [], []
    for block in blocks:
        if len(block) > 64:
            decisions.append({"block": list(block), "size": len(block), "certified": False, "strict": False,
                              "verification_status": "exact_size_limit_preassembly",
                              "graph_fingerprint": prepared.fingerprint, "gamma_exact": str(gamma)})
            continue
        certificate = certify_block(prepared, block, gamma, verification="auto", exact_max_size=64,
                                    dense_max_size=64, screen_tolerance=1e-10)
        decisions.append(certificate.to_dict())
        if certificate.certified:
            if (certificate.verification_status not in {"verified_positive_definite", "verified_positive_semidefinite"}
                    or certificate.metadata.get("graph_fingerprint") != prepared.fingerprint
                    or certificate.metadata.get("gamma_exact") != str(gamma)):
                raise ArithmeticError("degree acceptance lacks the exact current fingerprint/resolution guarantee")
            certificates.append(certificate)
    return prepared, tuple(certificates), {"decisions": decisions, "status_counts": dict(Counter(
        decision["verification_status"] for decision in decisions)), "candidate_count": len(blocks),
        "accepted_count": len(certificates), "graph_fingerprint": prepared.fingerprint, "gamma_exact": str(gamma),
        "checker_parameters": {"verification": "auto", "exact_max_size": 64, "dense_max_size": 64,
                               "screen_tolerance": 1e-10}, "all_decisions_on_one_fixed_current_graph": True}


def discovery_representability(membership, labels, n_current=None):
    groups = groups_from_membership(membership, n_current)
    crossings = [index for index, group in enumerate(groups) if len({labels[u] for u in group}) > 1]
    return {"representable": not crossings, "crossing_group_count": len(crossings),
            "crossing_current_vertex_ids": crossings, "external_original_incumbent_allowed": True,
            "control_kind": "discovery-incumbent control", "louvain_initial_partition_supplied": False}


def graph_counts(cache):
    loop_count = sum(any(v == u and weight for v, weight in row) for u, row in enumerate(cache.rows))
    off_diagonal = sum(v != u for u, row in enumerate(cache.rows) for v, _ in row) // 2
    return {"vertices": cache.n, "off_diagonal_edges": off_diagonal, "loop_count": loop_count,
            "isolates": sum(degree == 0 for degree in cache.degrees), "S_exact": cache.total}


def coverage_record(context, membership):
    groups = groups_from_membership(membership)
    lcc = set(context.largest_component)
    positive = {u for u, degree in enumerate(context.objective.degrees) if degree > 0}
    positive_removed = sum(max(0, sum(u in positive for u in group) - 1) for group in groups)
    lcc_removed = sum(max(0, sum(u in lcc for u in group) - 1) for group in groups)
    return {"original_vertices": context.objective.n, "remaining_vertices": len(groups),
            "removed_vertices": context.objective.n - len(groups),
            "removed_fraction": (context.objective.n - len(groups)) / context.objective.n,
            "positive_degree_original_vertices": len(positive), "positive_degree_removed_vertices": positive_removed,
            "largest_component_under_original_objective": {"vertices": len(lcc), "removed_vertices": lcc_removed,
                                                          "removed_fraction": lcc_removed / len(lcc)},
            "original_total_volume_is_unchanged": True}


def prepare_arm(context, bank, gamma, arm, ledger, *, partial_provenance=None):
    if arm not in ARMS:
        raise ValueError("unknown pipeline arm")
    applicable = {"arm_solver_prepare"}
    provenance = {} if partial_provenance is None else partial_provenance
    recursive_partition = None
    if arm in {"R", "RD"}:
        applicable.update(("recursive_prefix", "recursive_csr_reconstruct_validate"))
        with ledger.measure("recursive_prefix", arm=arm):
            result = run_recursive_prefix(context.adjacency, bank.blocks, gamma)
            if (result["gamma_exact"] != str(gamma) or result["metadata"]["original_bank_sha256"] != bank.identity_sha256
                    or result["metadata"]["max_block_size"] != 64 or result["metadata"]["round_limit"] is not None):
                raise ArithmeticError("recursive prefix changed its fixed bank/policy/resolution")
            recursive_partition = canonical_partition(result["original_membership"])
            provenance.update(recursive_result=result, recursive_internal_membership=list(result["original_membership"]))
        with ledger.measure("recursive_csr_reconstruct_validate", arm=arm):
            r_quotient = quotient_adjacency(context.adjacency, result["merge_groups"], require_exact=True)
            r_membership = integer_labels(r_quotient.membership, context.objective.n)
            if canonical_partition(r_membership) != recursive_partition:
                raise ArithmeticError("reconstructed CSR membership differs from recursive original partition")
            r_cache, r_validation = validate_quotient(context.objective, r_quotient.adjacency, r_membership)
            if r_cache.n != result["remaining_vertices"]:
                raise ArithmeticError("reconstructed recursive quotient has an unexpected order")
            provenance.update({"recursive_result": result, "recursive_internal_membership": list(result["original_membership"]),
                          "r_prefix_operational_membership": list(r_membership),
                          "r_prefix_partition_sha256": content_hash(recursive_partition),
                          "r_prefix_validation": r_validation, "r_prefix_core_metadata": r_quotient.metadata,
                          "r_prefix_graph_counts": graph_counts(r_cache)})
            adjacency, membership, cache = r_quotient.adjacency, r_membership, r_cache
    else:
        adjacency, membership, cache = context.adjacency, None, context.objective
    if arm == "RD":
        applicable.update(("mapped_bank_prepare", "r_prefix_cross_arm_validate"))
        with ledger.measure("mapped_bank_prepare", arm=arm):
            mapped = map_original_bank(bank.blocks, membership, bank.discovery_labels, max_block_size=64)
            degree_blocks = mapped.blocks
            provenance["mapped_bank"] = {"entries": list(mapped.entries), "summary": mapped.summary}
    else:
        degree_blocks = bank.blocks
    if arm in {"D", "RD"}:
        applicable.update(("degree_prepare_check", "degree_contract_validate"))
        with ledger.measure("degree_prepare_check", arm=arm):
            prepared, certificates, degree_record = run_degree_stage(adjacency, degree_blocks, gamma)
            provenance["degree_stage"] = degree_record
        with ledger.measure("degree_contract_validate", arm=arm):
            d_quotient = contract_certified_blocks(prepared, certificates)
            before_count = adjacency.shape[0]
            second = integer_labels(d_quotient.membership, before_count)
            # D already maps original vertices directly; constructing an O(n)
            # identity vector outside a charged phase would omit required work.
            membership = second if arm == "D" else compose_membership(membership, second)
            cache, validation = validate_quotient(context.objective, d_quotient.adjacency, membership)
            adjacency = d_quotient.adjacency
            provenance.update(degree_stage_current_membership=list(second), degree_contract_core_metadata=d_quotient.metadata,
                              final_direct_original_validation=validation)
            if arm == "RD":
                provenance["additional_removed_vertices_after_r"] = before_count - cache.n
    with ledger.measure("arm_solver_prepare", arm=arm):
        if arm == "U":
            membership = tuple(range(context.objective.n))
        solver_graph = context.graph if arm == "U" else networkx_quotient(adjacency)
        groups = groups_from_membership(membership, cache.n)
        representation = discovery_representability(membership, bank.discovery_labels, cache.n)
        provenance.update(operational_membership=list(membership), original_groups=[list(group) for group in groups],
                          original_partition_sha256=content_hash(canonical_partition(membership)),
                          final_objective_content_sha256=cache.content_sha256, graph_counts=graph_counts(cache),
                          coverage=coverage_record(context, membership), discovery_representability=representation,
                          stage_status="completed", gamma_exact=str(gamma))
        state = ArmState(arm, adjacency, membership, solver_graph, cache, provenance, recursive_partition)
    for phase in ARM_PHASES:
        if phase not in applicable:
            ledger.not_applicable(phase, arm)
    return state


def validate_r_prefixes(states, ledger):
    with ledger.measure("r_prefix_cross_arm_validate", arm="RD"):
        if states["R"].recursive_partition != states["RD"].recursive_partition:
            raise ArithmeticError("fresh independently prepared R and RD prefixes disagree")
        states["RD"].provenance["independent_r_prefix_partition_equality_verified"] = True
