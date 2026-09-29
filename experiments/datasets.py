"""Canonical processing of archived graphs for undirected modularity."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import networkx as nx


def load_snap(name: str):
    registry = json.loads(Path("data/registry.json").read_text(encoding="utf-8"))
    entry = registry[name]
    path = Path(entry["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError(f"Dataset hash mismatch: {name}")
    graph = nx.Graph()
    rows = loops = duplicates = 0
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            if line.startswith("#") or not line.strip():
                continue
            u, v = map(int, line.split()[:2])
            graph.add_nodes_from((u, v))
            rows += 1
            if u == v:
                loops += 1
            elif graph.has_edge(u, v):
                duplicates += 1
            else:
                graph.add_edge(u, v, weight=1)
    nodes = sorted(graph)
    graph = nx.relabel_nodes(graph, {u: i for i, u in enumerate(nodes)})
    metadata = {
        "name": name,
        "raw_sha256": entry["sha256"],
        "processing": "undirected simple union; remove self-loops; retain every listed endpoint",
        "source_rows": rows,
        "self_loop_rows_removed": loops,
        "duplicate_or_reciprocal_rows_collapsed": duplicates,
        "n": len(graph),
        "m": graph.number_of_edges(),
        "isolates": nx.number_of_isolates(graph),
        "components": nx.number_connected_components(graph),
        "largest_component_n": max(map(len, nx.connected_components(graph)), default=0),
        "original_sorted_node_labels_sha256": hashlib.sha256(json.dumps(nodes, separators=(",", ":")).encode()).hexdigest(),
        "relabeling": "ascending original integer identifier to 0..n-1",
    }
    return graph, metadata


def load_development(name: str):
    constructors = {
        "karate": nx.karate_club_graph,
        "les_miserables": nx.les_miserables_graph,
        "florentine": nx.florentine_families_graph,
        "davis": nx.davis_southern_women_graph,
    }
    graph = nx.convert_node_labels_to_integers(constructors[name]())
    return graph, {"name": name, "source": "NetworkX built-in dataset", "networkx_version": nx.__version__, "n": len(graph), "m": graph.number_of_edges()}
