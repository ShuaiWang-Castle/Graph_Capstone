"""Reproducible controlled graphs, independent of contraction acceptance.

Every constructor returns ``(graph, metadata)`` like ``experiments.datasets``.
Original graphs are loopless, have consecutive integer labels and positive
integer edge weights. No rejection sampling selects favorable certificates.
Oracle/reference blocks are opt-in metadata for controlled supplied-block
studies only. They are never graph attributes or a candidate-bank input.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import itertools
import json
import random
from typing import Iterable, Sequence

import networkx as nx


MATCHING_CLIQUE_SIZES = (3, 4, 5, 8, 16, 32, 64)
NOISY_PLANTED_SEEDS = (101, 102, 103)
WEIGHTED_PLANTED_SEEDS = (201, 202, 203)
GENERATOR_VERSION = "controlled-families-v1"


def _integer(value: int, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _probability(value, name: str) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a probability in [0, 1]")
    try:
        probability = value if isinstance(value, Fraction) else Fraction(str(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"{name} must be a probability in [0, 1]") from error
    if probability < 0 or probability > 1:
        raise ValueError(f"{name} must be a probability in [0, 1]")
    return probability


def _rng(seed: int, stream: str) -> random.Random:
    """Independent, explicitly named MT19937 streams, with integer seeds."""
    _integer(seed, "seed")
    key = f"{GENERATOR_VERSION}:{stream}:{seed}".encode("ascii")
    return random.Random(int.from_bytes(hashlib.sha256(key).digest(), "big"))


def _draw(rng: random.Random, probability: Fraction) -> bool:
    # Integer sampling preserves rational input probabilities without a float
    # threshold. Denominator1 also handles the endpoint probabilities exactly.
    return rng.randrange(probability.denominator) < probability.numerator


def graph_sha256(graph: nx.Graph) -> str:
    """Content hash of node count and canonically ordered integer edges."""
    edges = sorted((min(u, v), max(u, v), attributes["weight"])
                   for u, v, attributes in graph.edges(data=True))
    payload = json.dumps({"n": len(graph), "edges": edges},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finish(graph: nx.Graph, family: str, parameters: dict, *,
            reference_blocks: Iterable[Iterable[int]] = (),
            include_oracle_blocks: bool = False, **annotations):
    if set(graph) != set(range(len(graph))) or nx.number_of_selfloops(graph):
        raise AssertionError("Controlled original graph must be loopless with labels0..n-1")
    if any(type(edge["weight"]) is not int or edge["weight"] <= 0
           for _, _, edge in graph.edges(data=True)):
        raise AssertionError("Controlled weights must be positive Python integers")
    metadata = {
        "name": family,
        "family": family,
        "generator_version": GENERATOR_VERSION,
        "generation_parameters": parameters,
        "certificate_independent": True,
        "selection": "all configured cases; no certificate-based resampling",
        "candidate_policy": "fixed independent bank; oracle blocks only in separately labeled controlled studies",
        "oracle_blocks_included": bool(include_oracle_blocks),
        "original_loopless": True,
        "edge_weights": "positive integers",
        "n": len(graph),
        "m": graph.number_of_edges(),
        "total_volume": sum(int(degree) for _, degree in graph.degree(weight="weight")),
        "isolates": nx.number_of_isolates(graph),
        "components": nx.number_connected_components(graph),
        "graph_sha256": graph_sha256(graph),
        **annotations,
    }
    if include_oracle_blocks:
        metadata["oracle_blocks"] = [sorted(block) for block in reference_blocks]
        metadata["oracle_use"] = "controlled supplied-block comparison only; not discovery or recovery evidence"
    return graph, metadata


def matching_cliques(k: int = 5, *, include_oracle_blocks: bool = False):
    """Two unit K_k cliques joined by a unit perfect matching."""
    _integer(k, "k", 2)
    graph = nx.Graph()
    graph.add_nodes_from(range(2 * k))
    blocks = (tuple(range(k)), tuple(range(k, 2 * k)))
    for block in blocks:
        graph.add_edges_from(itertools.combinations(block, 2), weight=1)
    graph.add_edges_from(((u, k + u) for u in range(k)), weight=1)
    return _finish(
        graph, "matching_cliques", {"k": k, "seed": None},
        reference_blocks=blocks, include_oracle_blocks=include_oracle_blocks,
        role="exact controlled mechanism and scaling family",
        known_formula={"degree": k, "total_volume": 2 * k * k,
                       "uniform_gap_gamma1": str(Fraction(k, 2) - 2),
                       "weighted_zero_center_gamma_max": str(2 - Fraction(4, k))},
        prior_art_separation="none: exact C-subinstance oracle covers this family",
        upstream_evidence="research/safe_contraction/theory-audit.md#8-matching-clique-family-and-primary-source-scope",
    )


def common_hub_matching(k: int = 6, *, include_oracle_blocks: bool = False):
    """Matching cliques plus one hub adjacent to the first entire clique."""
    graph, _ = matching_cliques(k)
    hub = 2 * k
    graph.add_node(hub)
    graph.add_edges_from(((u, hub) for u in range(k)), weight=1)
    return _finish(
        graph, "common_hub_matching", {"k": k, "hub": hub, "seed": None},
        reference_blocks=(range(k), range(k, 2 * k)),
        include_oracle_blocks=include_oracle_blocks,
        role="negative prior-art separation and shared-exterior mechanism diagnostic",
        known_negative_prior_art_result="actual KaPoCE star/P3 implementation solves upstream common-hub matching case; retain this outcome",
        prior_art_separation="none claimed",
        upstream_evidence="experiments/protocol.md#baselines-and-configuration-contract",
    )


def _planted_layout(block_sizes: Sequence[int]):
    sizes = tuple(_integer(size, "block_size", 2) for size in block_sizes)
    if len(sizes) < 2:
        raise ValueError("At least two planted blocks are required")
    blocks, membership = [], []
    for label, size in enumerate(sizes):
        start = len(membership)
        blocks.append(tuple(range(start, start + size)))
        membership.extend([label] * size)
    return sizes, blocks, membership


def _relabel(graph: nx.Graph, blocks: Sequence[Sequence[int]], seed: int):
    labels = list(range(len(graph)))
    _rng(seed, "vertex-relabeling").shuffle(labels)
    mapping = dict(enumerate(labels))
    relabeled = nx.relabel_nodes(graph, mapping, copy=True)
    # Insertion order too is canonical, so external consumers do not inherit
    # latent-order effects through Graph iteration.
    canonical = nx.Graph()
    canonical.add_nodes_from(range(len(graph)))
    canonical.add_weighted_edges_from(sorted(
        (min(u, v), max(u, v), edge["weight"])
        for u, v, edge in relabeled.edges(data=True)))
    return canonical, [tuple(sorted(mapping[u] for u in block)) for block in blocks]


def weighted_planted_blocks(*, block_sizes: Sequence[int] = (4, 5, 6),
                            p=Fraction(4, 5), q=Fraction(1, 25),
                            node_factors: Sequence[int] = (1, 2, 4),
                            internal_base: int = 3, external_base: int = 1,
                            seed: int = 201, relabel_seed: int | None = None,
                            include_oracle_blocks: bool = False):
    """Small weighted planted blocks with declared degree heterogeneity.

    Edge presence is independent with probabilities p/q. Its integer weight is
    the internal/external base times the two endpoint factors. Factors cycle
    within each latent block; independent relabeling conceals block order.
    No connectivity or certificate acceptance is enforced.
    """
    sizes, blocks, membership = _planted_layout(block_sizes)
    p, q = _probability(p, "p"), _probability(q, "q")
    factors = tuple(_integer(factor, "node_factor", 1) for factor in node_factors)
    if not factors:
        raise ValueError("node_factors must be nonempty")
    _integer(internal_base, "internal_base", 1)
    _integer(external_base, "external_base", 1)
    _integer(seed, "seed")
    relabel_seed = seed + 1_000_000 if relabel_seed is None else _integer(relabel_seed, "relabel_seed")
    activity = [factors[position % len(factors)] for block in blocks
                for position in range(len(block))]
    rng = _rng(seed, "weighted-edge-presence")
    graph = nx.Graph()
    graph.add_nodes_from(range(len(membership)))
    for u, v in itertools.combinations(range(len(graph)), 2):
        internal = membership[u] == membership[v]
        if _draw(rng, p if internal else q):
            base = internal_base if internal else external_base
            graph.add_edge(u, v, weight=base * activity[u] * activity[v])
    graph, blocks = _relabel(graph, blocks, relabel_seed)
    return _finish(
        graph, "weighted_planted_blocks",
        {"block_sizes": list(sizes), "p": str(p), "q": str(q),
         "node_factors": list(factors), "factor_assignment": "cyclic within latent blocks",
         "internal_base": internal_base, "external_base": external_base,
         "seed": seed, "relabel_seed": relabel_seed,
         "rng": "independent named Python Random MT19937 streams; rational randrange draws"},
        reference_blocks=blocks, include_oracle_blocks=include_oracle_blocks,
        role="certificate-independent controlled weighted heterogeneity",
        oracle_block_interpretation="latent generating blocks, not claimed modularity-optimal communities",
        recovery_accuracy_claimed=False,
    )


def noisy_planted_clusters(*, communities: int = 8, block_size: int = 30,
                           p=Fraction(13, 20), q=Fraction(1, 100),
                           deletion_probability=Fraction(1, 10),
                           addition_probability=Fraction(1, 1000),
                           seed: int = 101, noise_seed: int | None = None,
                           relabel_seed: int | None = None,
                           include_oracle_blocks: bool = False):
    """Unweighted planted graph followed by independent deletion/addition noise.

    Keep all original vertices, including isolates. Added edges are sampled
    only from latent nonedges and deletions only from latent edges. True blocks
    are optional oracle metadata, never candidate-bank hints or node labels.
    """
    _integer(communities, "communities", 2)
    _integer(block_size, "block_size", 2)
    sizes, blocks, membership = _planted_layout([block_size] * communities)
    p, q = _probability(p, "p"), _probability(q, "q")
    deletion = _probability(deletion_probability, "deletion_probability")
    addition = _probability(addition_probability, "addition_probability")
    _integer(seed, "seed")
    noise_seed = seed + 100_000 if noise_seed is None else _integer(noise_seed, "noise_seed")
    relabel_seed = seed + 1_000_000 if relabel_seed is None else _integer(relabel_seed, "relabel_seed")
    latent_rng = _rng(seed, "unweighted-latent-edge-presence")
    noise_rng = _rng(noise_seed, "unweighted-observation-channel")
    latent, observed = nx.Graph(), nx.Graph()
    latent.add_nodes_from(range(len(membership)))
    observed.add_nodes_from(range(len(membership)))
    removed = added = latent_internal = latent_external = 0
    for u, v in itertools.combinations(range(len(membership)), 2):
        internal = membership[u] == membership[v]
        exists = _draw(latent_rng, p if internal else q)
        if exists:
            latent.add_edge(u, v, weight=1)
            latent_internal += int(internal)
            latent_external += int(not internal)
            if _draw(noise_rng, deletion):
                removed += 1
            else:
                observed.add_edge(u, v, weight=1)
        elif _draw(noise_rng, addition):
            observed.add_edge(u, v, weight=1)
            added += 1
    latent, _ = _relabel(latent, blocks, relabel_seed)
    observed, blocks = _relabel(observed, blocks, relabel_seed)
    return _finish(
        observed, "noisy_planted_clusters",
        {"communities": communities, "block_size": block_size,
         "p": str(p), "q": str(q), "deletion_probability": str(deletion),
         "addition_probability": str(addition), "seed": seed,
         "noise_seed": noise_seed, "relabel_seed": relabel_seed,
         "rng": "independent named Python Random MT19937 streams; rational randrange draws"},
        reference_blocks=blocks, include_oracle_blocks=include_oracle_blocks,
        role="certificate-independent controlled unweighted/noisy clusters",
        latent_graph_sha256=graph_sha256(latent),
        latent_m=latent.number_of_edges(), latent_internal_edges=latent_internal,
        latent_external_edges=latent_external, deleted_edges=removed, added_edges=added,
        observation_channel="independent latent-edge deletions and latent-nonedge additions; no postselection",
        oracle_block_interpretation="latent generating blocks, not claimed modularity-optimal communities",
        recovery_accuracy_claimed=False,
    )


def uniform_advantage_counterexample(*, include_oracle_blocks: bool = False):
    """Loopless reverse-dominance control derived from the audited looped case."""
    graph = nx.Graph()
    graph.add_nodes_from(range(5))
    graph.add_weighted_edges_from([
        (0, 1, 2), (0, 2, 5), (0, 3, 5), (0, 4, 5),
        (1, 2, 1), (1, 4, 1), (2, 3, 1), (2, 4, 1), (3, 4, 1),
    ])
    return _finish(
        graph, "uniform_advantage_counterexample", {"seed": None, "gamma": "1/8"},
        reference_blocks=((2, 3),), include_oracle_blocks=include_oracle_blocks,
        role="exploratory derived loopless non-dominance control",
        upstream_evidence="research/safe_contraction/theory-audit.md#7-negative-edges-quotient-loops-and-non-dominance",
        derivation="remove the audited A22=2 diagonal; recompute all degrees and S",
        known_formula={"degrees": [17, 4, 8, 7, 8], "total_volume": 44,
                       "uniform_pair_margin_gamma1over8": "219/704",
                       "weighted_pair_margin_gamma1over8": "-17/660"},
        prior_art_separation="none claimed; ablation showing lack of universal dominance",
        oracle_block_interpretation="specified reference block, not community truth",
    )


def hard_exterior_attachment(k: int = 6, *, attachment_weight: int | None = None,
                             include_oracle_blocks: bool = False):
    """Exploratory expected-failure control: unit core clique + private leaves.

    At gamma1, W²-2W-(k-1)>0 makes every core-core affinity negative.
    The only positive affinities are private core-leaf edges. Their disjoint
    pairs attain all positives with no negatives, hence are the unique optimum.
    This is a mathematical failure stress, not a prior-art separation family.
    """
    _integer(k, "k", 2)
    weight = k + 2 if attachment_weight is None else _integer(attachment_weight, "attachment_weight", 1)
    gap_numerator = weight * weight - 2 * weight - (k - 1)
    if gap_numerator <= 0:
        raise ValueError("Expected-failure attachment requires W²-2W-(k-1)>0")
    graph = nx.Graph()
    graph.add_nodes_from(range(2 * k))
    graph.add_edges_from(itertools.combinations(range(k), 2), weight=1)
    graph.add_edges_from(((u, k + u) for u in range(k)), weight=weight)
    return _finish(
        graph, "hard_exterior_attachment", {"k": k, "attachment_weight": weight, "seed": None},
        reference_blocks=(range(k),), include_oracle_blocks=include_oracle_blocks,
        role="exploratory mathematically justified expected-failure attachment stress",
        expected_outcome="core fusion loses modularity at gamma1; only private edge-pair partition is optimal",
        known_formula={"core_degree": k - 1 + weight,
                       "total_volume": k * (k - 1 + 2 * weight),
                       "core_degree_squared_minus_total_volume": gap_numerator},
        prior_art_separation="none claimed",
        oracle_block_interpretation="deliberately non-optimal core stress block",
    )


def profile_scaling(k: int = 16, *, outside_vertices: int = 100,
                    hub_size: int = 4, core_weight: int = 1,
                    attachment_weight: int = 1, outside_weight: int = 1,
                    include_oracle_blocks: bool = False):
    """Fixed common exterior support, with an independently larger unit ring.

    Core profiles/degree remain fixed while outside n and full S change. A
    dense exterior table grows with n; sparse local incidences stay k*hub_size.
    Known twin-type baselines may win: this tests computation, not separation.
    """
    _integer(k, "k", 2)
    _integer(outside_vertices, "outside_vertices", 3)
    _integer(hub_size, "hub_size", 1)
    if hub_size > outside_vertices:
        raise ValueError("hub_size cannot exceed outside_vertices")
    for value, name in ((core_weight, "core_weight"), (attachment_weight, "attachment_weight"),
                        (outside_weight, "outside_weight")):
        _integer(value, name, 1)
    graph = nx.Graph()
    graph.add_nodes_from(range(k + outside_vertices))
    graph.add_edges_from(itertools.combinations(range(k), 2), weight=core_weight)
    graph.add_edges_from(((u, v) for u in range(k) for v in range(k, k + hub_size)),
                        weight=attachment_weight)
    graph.add_edges_from(((k + i, k + (i + 1) % outside_vertices)
                         for i in range(outside_vertices)), weight=outside_weight)
    return _finish(
        graph, "profile_scaling",
        {"k": k, "outside_vertices": outside_vertices, "outside_model": "ring",
         "hub_size": hub_size, "core_weight": core_weight,
         "attachment_weight": attachment_weight, "outside_weight": outside_weight,
         "seed": None},
        reference_blocks=(range(k),), include_oracle_blocks=include_oracle_blocks,
        role="controlled scaling of shared exterior profiles; no separation claim",
        exterior_incidences=k * hub_size,
        dense_exterior_entries=k * outside_vertices,
        common_normalized_exterior_profiles=True,
        total_volume_changes_with_outside_size=True,
        global_null_normalization="retain each graph's full S; do not tune attachment after seeing acceptance",
        known_formula={"core_degree": (k - 1) * core_weight + hub_size * attachment_weight,
                       "total_volume": k * (k - 1) * core_weight + 2 * k * hub_size * attachment_weight
                       + 2 * outside_vertices * outside_weight},
        prior_art_separation="none claimed; common-neighborhood/twin rules are required controls",
    )


_FAMILIES = {
    "matching_cliques": matching_cliques,
    "common_hub_matching": common_hub_matching,
    "weighted_planted_blocks": weighted_planted_blocks,
    "noisy_planted_clusters": noisy_planted_clusters,
    "uniform_advantage_counterexample": uniform_advantage_counterexample,
    "hard_exterior_attachment": hard_exterior_attachment,
    "profile_scaling": profile_scaling,
}


def load_family(name: str, **parameters):
    """Config-facing dispatch; returns graph/metadata without discovering blocks."""
    try:
        constructor = _FAMILIES[name]
    except KeyError as error:
        raise ValueError(f"Unknown controlled family: {name}") from error
    return constructor(**parameters)
