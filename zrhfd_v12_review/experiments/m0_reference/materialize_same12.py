"""Materialize the exact sequential rng59 SBM cases in supplied theory scripts."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "inputs/local_hfd/theory/zr_pipeline.py"
DEST = ROOT / "data/dev/same12"
REGIMES = [(4, 100, .5, .05), (4, 100, .3, .02),
           (5, 80, .6, .05), (4, 250, .1, .01)]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> str:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if path.exists() and path.read_bytes() != data:
        raise RuntimeError(f"Refusing to overwrite different immutable input: {path}")
    path.write_bytes(data)
    return digest(data)


def main() -> None:
    source = SOURCE.read_bytes()
    tree = ast.parse(source)
    # Execute only the supplied sbm and csr definitions, avoiding unavailable core
    # and every experiment/output side effect.
    definitions = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name in {"sbm", "csr"}]
    scope = {"np": np, "rng": np.random.default_rng(59)}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(SOURCE), "exec"), scope)
    DEST.mkdir(parents=True, exist_ok=True)
    rows = []
    for regime_index, (K, block_size, p, q) in enumerate(REGIMES):
        for rep in range(3):
            case_index = len(rows)
            case_id = f"same12_{case_index:02d}"
            state_before_graph = scope["rng"].bit_generator.state
            A, labels = scope["sbm"](K, block_size, p, q)
            state_before_seed = scope["rng"].bit_generator.state
            indptr, indices, degrees = scope["csr"](A)
            C = np.flatnonzero(labels == 0)
            seed = int(C[scope["rng"].integers(len(C))])
            state_after_seed = scope["rng"].bit_generator.state
            upper = np.transpose(np.nonzero(np.triu(A, 1))).tolist()
            graph_path = DEST / f"{case_id}.graph.json"
            truth_path = DEST / f"{case_id}.truth.json"
            graph_sha = write_json(graph_path, {"n": len(A), "edges": upper})
            truth_sha = write_json(truth_path, {"communities": [np.flatnonzero(labels == k).tolist() for k in range(K)]})
            nb = indices[indptr[seed]:indptr[seed + 1]]
            m_act = float(degrees[seed] + (1 + 1e-4) * degrees[seed] * degrees[nb].min())
            row = {
                "case_id": case_id, "case_index": case_index, "regime_index": regime_index,
                "rep": rep, "K": K, "block_size": block_size, "p": p, "q": q,
                "n": len(A), "edge_count": len(upper), "seed": seed, "community_index": 0,
                "seed_degree": int(degrees[seed]), "total_volume": int(degrees.sum()),
                "truth_volume": int(degrees[C].sum()), "m_act": m_act,
                "graph_path": graph_path.relative_to(ROOT).as_posix(),
                "truth_path": truth_path.relative_to(ROOT).as_posix(),
                "graph_sha256": graph_sha, "truth_sha256": truth_sha,
                "adjacency_float64_le_c_sha256": digest(A.astype("<f8", copy=False).tobytes(order="C")),
                "rng_state_before_graph": state_before_graph, "rng_state_before_seed": state_before_seed,
                "rng_state_after_seed": state_after_seed,
            }
            rows.append(row)
            print(json.dumps({key: row[key] for key in ["case_id", "n", "edge_count", "seed", "seed_degree", "m_act"]}), flush=True)
    catalog = {
        "schema_version": 1, "purpose": "M0 exact same12 reference/dev graphs; not test graphs",
        "generator_source": SOURCE.relative_to(ROOT).as_posix(), "generator_source_sha256": digest(source),
        "generator": "Executed supplied sbm and csr definitions without changing their code",
        "rng": "numpy.random.default_rng(59), sequential graph then seed draws",
        "numpy_version": np.__version__, "query_rule": "one random node from label 0 after each graph draw",
        "graph_schema": {"n": "int", "edges": "list of sorted upper-triangle unweighted undirected [u,v]"},
        "truth_schema": {"communities": "K lists of node IDs, first block is target"},
        "cases": rows,
    }
    write_json(DEST / "catalog.json", catalog)


if __name__ == "__main__":
    main()
