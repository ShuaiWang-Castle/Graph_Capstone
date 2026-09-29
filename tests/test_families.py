"""Structural and exact algebra checks; no comparative performance runs."""
from fractions import Fraction
import itertools
import json
import random

import networkx as nx
import pytest

from experiments.families import (
    MATCHING_CLIQUE_SIZES,
    common_hub_matching,
    graph_sha256,
    hard_exterior_attachment,
    load_family,
    matching_cliques,
    noisy_planted_clusters,
    profile_scaling,
    uniform_advantage_counterexample,
    weighted_planted_blocks,
)


def edge_map(graph):
    return {(min(u, v), max(u, v)): attributes["weight"]
            for u, v, attributes in graph.edges(data=True)}


def validate_graph(graph, metadata):
    assert set(graph) == set(range(len(graph)))
    assert nx.number_of_selfloops(graph) == 0
    assert all(type(attributes["weight"]) is int and attributes["weight"] > 0
               for _, _, attributes in graph.edges(data=True))
    assert all(not attributes for _, attributes in graph.nodes(data=True))
    assert metadata["n"] == len(graph)
    assert metadata["m"] == graph.number_of_edges()
    assert metadata["total_volume"] == 2 * sum(edge_map(graph).values())
    assert metadata["graph_sha256"] == graph_sha256(graph)
    assert metadata["certificate_independent"]
    assert not metadata["oracle_blocks_included"]
    assert "oracle_blocks" not in metadata
    # Data metadata is portable/serializable; no runtime or hardware objects.
    json.dumps(metadata, allow_nan=False)


@pytest.mark.parametrize("k", MATCHING_CLIQUE_SIZES)
def test_matching_family_has_exact_degree_volume_and_threshold(k):
    graph, metadata = matching_cliques(k)
    validate_graph(graph, metadata)
    assert len(graph) == 2 * k
    assert graph.number_of_edges() == k * k
    assert set(dict(graph.degree(weight="weight")).values()) == {k}
    crossing = {(u, v) for u, v in graph.edges if (u < k) != (v < k)}
    assert crossing == {(u, k + u) for u in range(k)}
    assert Fraction(metadata["known_formula"]["uniform_gap_gamma1"]) == Fraction(k, 2) - 2
    assert Fraction(metadata["known_formula"]["weighted_zero_center_gamma_max"]) == 2 - Fraction(4, k)


def test_common_hub_retains_negative_upstream_outcome_and_integer_structure():
    graph, metadata = common_hub_matching()
    validate_graph(graph, metadata)
    assert len(graph) == 13
    assert graph.number_of_edges() == 42
    assert set(graph.neighbors(12)) == set(range(6))
    assert metadata["prior_art_separation"] == "none claimed"
    assert "star/P3" in metadata["known_negative_prior_art_result"]
    assert "retain" in metadata["known_negative_prior_art_result"]


def test_seeded_weighted_graph_is_reproducible_and_keeps_oracles_opt_in():
    parameters = dict(block_sizes=(4, 5, 6), p=1, q=1, seed=201, relabel_seed=1000201)
    graph, metadata = weighted_planted_blocks(**parameters)
    duplicate, duplicated_metadata = weighted_planted_blocks(**parameters)
    validate_graph(graph, metadata)
    assert edge_map(graph) == edge_map(duplicate)
    assert metadata == duplicated_metadata
    assert len(set(dict(graph.degree(weight="weight")).values())) > 1
    oracle_graph, oracle_metadata = weighted_planted_blocks(**parameters, include_oracle_blocks=True)
    assert edge_map(oracle_graph) == edge_map(graph)
    blocks = [set(block) for block in oracle_metadata["oracle_blocks"]]
    assert sorted(map(len, blocks)) == [4, 5, 6]
    assert set.union(*blocks) == set(graph)
    assert sum(map(len, blocks)) == len(graph)
    for u, v, attributes in graph.edges(data=True):
        if any(u in block and v in block for block in blocks):
            assert attributes["weight"] in {3, 6, 12, 24, 48}
        else:
            assert attributes["weight"] in {1, 2, 4, 8, 16}
    assert not graph.graph and not oracle_graph.graph


def test_unweighted_planted_endpoints_match_exact_cliques_without_hints():
    parameters = dict(communities=3, block_size=4, p=1, q=0,
                      deletion_probability=0, addition_probability=0,
                      seed=101, noise_seed=100101, relabel_seed=1000101)
    graph, metadata = noisy_planted_clusters(**parameters)
    validate_graph(graph, metadata)
    assert sorted(map(len, nx.connected_components(graph))) == [4, 4, 4]
    assert graph.number_of_edges() == 18
    assert metadata["latent_m"] == 18
    assert metadata["deleted_edges"] == metadata["added_edges"] == 0
    assert metadata["latent_graph_sha256"] == metadata["graph_sha256"]
    oracle_graph, oracle_metadata = noisy_planted_clusters(**parameters, include_oracle_blocks=True)
    assert edge_map(graph) == edge_map(oracle_graph)
    oracle_blocks = {frozenset(block) for block in oracle_metadata["oracle_blocks"]}
    assert oracle_blocks == {frozenset(block) for block in nx.connected_components(graph)}
    assert all(not attributes for _, attributes in oracle_graph.nodes(data=True))


def test_noise_channel_deletes_or_adds_and_preserves_all_vertices():
    parameters = dict(communities=3, block_size=4, p=1, q=0, seed=101)
    removed_graph, removed_metadata = noisy_planted_clusters(
        **parameters, deletion_probability=1, addition_probability=0)
    validate_graph(removed_graph, removed_metadata)
    assert len(removed_graph) == 12 and removed_graph.number_of_edges() == 0
    assert removed_metadata["isolates"] == 12
    assert removed_metadata["deleted_edges"] == 18
    full_graph, full_metadata = noisy_planted_clusters(
        **parameters, deletion_probability=0, addition_probability=1)
    validate_graph(full_graph, full_metadata)
    assert full_graph.number_of_edges() == 66
    assert full_metadata["added_edges"] == 48
    assert full_metadata["latent_graph_sha256"] == removed_metadata["latent_graph_sha256"]
    complement, complement_metadata = noisy_planted_clusters(
        **parameters, deletion_probability=1, addition_probability=1)
    assert complement.number_of_edges() == 48
    assert complement_metadata["deleted_edges"] == 18


def test_noisy_generation_has_pinned_parameters_and_independent_streams():
    arguments = dict(communities=3, block_size=5, p="13/20", q="1/100",
                     deletion_probability="1/10", addition_probability="1/1000", seed=102)
    before = random.getstate()
    graph, metadata = noisy_planted_clusters(**arguments)
    second, second_metadata = noisy_planted_clusters(**arguments)
    assert random.getstate() == before
    validate_graph(graph, metadata)
    assert metadata == second_metadata and edge_map(graph) == edge_map(second)
    parameters = metadata["generation_parameters"]
    assert parameters["p"] == "13/20" and parameters["q"] == "1/100"
    assert parameters["deletion_probability"] == "1/10"
    assert parameters["addition_probability"] == "1/1000"
    assert parameters["seed"] == 102
    assert parameters["noise_seed"] == 100102
    assert parameters["relabel_seed"] == 1000102
    clean, clean_metadata = noisy_planted_clusters(
        **{**arguments, "deletion_probability": 0, "addition_probability": 0})
    assert clean_metadata["latent_graph_sha256"] == metadata["latent_graph_sha256"]
    assert clean.number_of_edges() == metadata["latent_m"]
    assert graph.number_of_edges() == metadata["latent_m"] - metadata["deleted_edges"] + metadata["added_edges"]


def pair_margins(graph, block, gamma):
    """Independent exact uniform/degree-weighted pair formulas, no checker."""
    u, v = block
    degrees = dict(graph.degree(weight="weight"))
    total = sum(degrees.values())

    def affinity(a, b):
        return Fraction(graph.get_edge_data(a, b, {}).get("weight", 0)) - gamma * degrees[a] * degrees[b] / total

    exterior = set(graph) - {u, v}
    uniform_distance = sum(abs(affinity(u, w) - affinity(v, w)) for w in exterior)
    weighted_distance = sum(abs(degrees[v] * graph.get_edge_data(u, w, {}).get("weight", 0)
                                - degrees[u] * graph.get_edge_data(v, w, {}).get("weight", 0))
                            for w in exterior)
    return (affinity(u, v) - uniform_distance / 2,
            affinity(u, v) - Fraction(weighted_distance, degrees[u] + degrees[v]))


def test_loopless_reverse_example_has_independently_verified_exact_margins():
    graph, metadata = uniform_advantage_counterexample()
    validate_graph(graph, metadata)
    assert list(dict(graph.degree(weight="weight")).values()) == [17, 4, 8, 7, 8]
    assert metadata["total_volume"] == 44
    uniform, weighted = pair_margins(graph, (2, 3), Fraction(1, 8))
    assert uniform == Fraction(219, 704) > 0
    assert weighted == Fraction(-17, 660) < 0
    assert uniform == Fraction(metadata["known_formula"]["uniform_pair_margin_gamma1over8"])
    assert weighted == Fraction(metadata["known_formula"]["weighted_pair_margin_gamma1over8"])


def partitions(n):
    def visit(prefix, maximum):
        if len(prefix) == n:
            yield tuple(prefix)
        else:
            for label in range(maximum + 2):
                yield from visit(prefix + [label], max(maximum, label))
    yield from visit([0], 0)


def test_hard_exterior_family_is_genuinely_split_optimal_in_exact_small_case():
    graph, metadata = hard_exterior_attachment(3)
    validate_graph(graph, metadata)
    degrees = dict(graph.degree(weight="weight"))
    total = sum(degrees.values())
    affinities = {(u, v): Fraction(graph.get_edge_data(u, v, {}).get("weight", 0))
                  - Fraction(degrees[u] * degrees[v], total)
                  for u, v in itertools.combinations(range(6), 2)}
    assert {pair for pair, affinity in affinities.items() if affinity > 0} == {(0, 3), (1, 4), (2, 5)}
    assert all(affinity < 0 for pair, affinity in affinities.items() if pair not in {(0, 3), (1, 4), (2, 5)})
    scores = [(sum(affinity for (u, v), affinity in affinities.items() if labels[u] == labels[v]), labels)
              for labels in partitions(6)]
    best = max(score for score, _ in scores)
    optima = [labels for score, labels in scores if score == best]
    assert optima == [(0, 1, 2, 0, 1, 2)]
    assert metadata["known_formula"]["core_degree_squared_minus_total_volume"] > 0
    assert "expected-failure" in metadata["role"]


@pytest.mark.parametrize("k", [16, 32])
@pytest.mark.parametrize("outside_vertices", [100, 1000, 10000])
def test_profile_scaling_changes_only_outside_size_and_global_volume(k, outside_vertices):
    graph, metadata = profile_scaling(k, outside_vertices=outside_vertices)
    validate_graph(graph, metadata)
    assert len(graph) == k + outside_vertices
    assert nx.is_connected(graph)
    degree = k - 1 + 4
    assert {graph.degree(u, weight="weight") for u in range(k)} == {degree}
    profiles = {tuple(sorted((v, Fraction(edge["weight"], degree))
                            for v, edge in graph[u].items() if v >= k))
                for u in range(k)}
    assert len(profiles) == 1
    assert metadata["exterior_incidences"] == 4 * k
    assert metadata["dense_exterior_entries"] == k * outside_vertices
    assert metadata["total_volume"] == k * (k - 1) + 8 * k + 2 * outside_vertices
    assert metadata["total_volume_changes_with_outside_size"]
    assert "none claimed" in metadata["prior_art_separation"]


@pytest.mark.parametrize("constructor, kwargs", [
    (matching_cliques, {"k": 1}),
    (matching_cliques, {"k": True}),
    (weighted_planted_blocks, {"p": "3/2"}),
    (weighted_planted_blocks, {"q": float("nan")}),
    (weighted_planted_blocks, {"block_sizes": [4]}),
    (weighted_planted_blocks, {"node_factors": []}),
    (weighted_planted_blocks, {"seed": -1}),
    (noisy_planted_clusters, {"deletion_probability": "-1/10"}),
    (noisy_planted_clusters, {"addition_probability": 2}),
    (hard_exterior_attachment, {"k": 6, "attachment_weight": 1}),
    (profile_scaling, {"outside_vertices": 2}),
    (profile_scaling, {"outside_vertices": 3, "hub_size": 4}),
])
def test_invalid_family_parameters_are_not_silently_changed(constructor, kwargs):
    with pytest.raises(ValueError):
        constructor(**kwargs)


def test_dispatch_does_not_supply_blocks_and_rejects_unknown_families():
    graph, metadata = load_family("matching_cliques", k=3)
    validate_graph(graph, metadata)
    with pytest.raises(ValueError, match="Unknown controlled family"):
        load_family("not_a_family")
