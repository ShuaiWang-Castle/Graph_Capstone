"""Native CPU Leiden modularity; return the query seed's global partition block."""
import importlib.metadata
import time
from ._common import source_record, validate_query


def run(graph, seed, config, oracle_volume=None):
    started = time.perf_counter()
    validate_query(graph, seed)
    import igraph
    import leidenalg
    edges = [(int(e[0]), int(e[1])) for e in graph.edges]
    weights = [float(e[2]) if len(e) > 2 else 1.0 for e in graph.edges]
    native = igraph.Graph(n=graph.n, edges=edges, directed=False)
    random_seed = int(config.get("random_seed", 73))
    iterations = int(config.get("iterations", -1))
    resolution = float(config.get("resolution", 1.0))
    partition = leidenalg.find_partition(native, leidenalg.RBConfigurationVertexPartition, weights=weights, resolution_parameter=resolution, n_iterations=iterations, seed=random_seed)
    vertices = sorted(partition[partition.membership[seed]])
    return {"vertices": vertices, "runtime_seconds": time.perf_counter() - started, "touched_vertices": list(range(graph.n)), "metadata": {"method": "Leiden-native-modularity", "sources": source_record("leidenalg", ["src/leidenalg/functions.py"]), "igraph_version": igraph.__version__, "leidenalg_version": importlib.metadata.version("leidenalg"), "objective": "RBConfiguration modularity", "resolution": resolution, "random_seed": random_seed, "iterations_requested": iterations, "update_count": "UNKNOWN: native optimiser does not expose iteration count", "stop": "native no-improvement convergence" if iterations < 0 else "fixed iteration request", "oracle_volume_used": False, "selection": "global partition block containing query seed", "partition_quality": float(partition.quality()), "partition_clusters": len(partition), "touched_definition": "global graph"}}
