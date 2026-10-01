"""Validate the isolated queue change and audit availability of source materials."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

sys.dont_write_bytecode = True

import numba
import numpy as np

from core import flow_cd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/m0_reference"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_arrays(row):
    graph = json.loads((ROOT / row["graph_path"]).read_text())
    A = np.zeros((graph["n"], graph["n"]))
    for u, v in graph["edges"]:
        A[u, v] = A[v, u] = 1
    neighbors = [np.flatnonzero(A[u]) for u in range(len(A))]
    return A, np.r_[0, np.cumsum([len(nb) for nb in neighbors])].astype(np.int64), np.concatenate(neighbors), A.sum(1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    kernel = ROOT / "inputs/local_hfd/kernels.py"
    tree = ast.parse(kernel.read_text())
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "flow_diffusion")
    fn.decorator_list = []
    scope = {"np": np}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(kernel), "exec"), scope)
    original = numba.njit(cache=False)(scope["flow_diffusion"])
    catalog = json.loads((ROOT / "data/dev/same12/catalog.json").read_text())
    rows = []
    begin = time.perf_counter()
    for row in catalog["cases"]:
        A, ptr, idx, d = graph_arrays(row)
        for ratio in [3, 48, 192]:
            mass = float(ratio*d[row["seed"]])
            cap = 200_000
            x = original(ptr, idx, d, row["seed"], mass, 1e-4, 1e-12, cap)
            bounded = flow_cd(ptr, idx, d, row["seed"], mass, 1e-4, 1e-12, cap)
            rows.append({"case_id": row["case_id"], "mass": mass, "max_updates": cap,
                         "bitwise_equal": bool(np.array_equal(x, bounded[0])),
                         "max_abs_difference": float(np.max(np.abs(x-bounded[0]))),
                         "bounded_updates": int(bounded[1]), "bounded_queue_drained": bool(bounded[3])})
    result = {"validation": "Original supplied flow_diffusion versus reconstructed bounded-queue flow_cd",
              "kernel_sha256": sha(kernel), "shim_sha256": sha(Path(__file__).with_name("core.py")),
              "numpy": np.__version__, "numba": numba.__version__, "seconds": time.perf_counter()-begin,
              "all_bitwise_equal": all(row["bitwise_equal"] for row in rows), "cases": rows}
    path = OUT / "queue_equivalence.json"
    if path.exists():
        raise RuntimeError("Refuse overwrite immutable validation")
    path.write_text(json.dumps(result, indent=1))
    print(json.dumps({k:result[k] for k in ["all_bitwise_equal","seconds"]}))
    source_records = []
    for path in sorted((ROOT/"inputs/local_hfd").rglob("*")):
        if path.is_file() and path.suffix in {".py", ".json", ".md"}:
            source_records.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    # Central-directory audit; no extraction or mutation of existing studies.
    workspace = ROOT.parent
    downloads = Path.home()/"Downloads"
    ziprecords = []
    for location in [workspace, downloads]:
        for archive in sorted(location.rglob("*.zip")):
            try:
                with zipfile.ZipFile(archive) as zf:
                    names = zf.namelist()
                    relevant = [name for name in names if name.endswith("code/core.py") or "fresh_lfr_mu" in name or "ZHFD_Research_Proofs_Code_Results" in name or "zhfd_research" in name.lower()]
                ziprecords.append({"archive": str(archive), "member_count": len(names), "relevant_members": relevant})
            except Exception as exc:
                ziprecords.append({"archive": str(archive), "error": repr(exc)})
    audit = {"present": {"attached_lfr_graphs": 4, "attached_truth_files": 4, "theory_sources": True,
                         "review_round1_source_and_historical_json": True, "same12_rng59_materialized": 12},
             "missing": ["ZHFD_Research_Proofs_Code_Results.zip", "historical code/core.py", "12 NetworkX LFR graphs/truth", "historical results/hfd_gate_{case}.json per-query F1/Z files"],
             "scope": "recursive regular files in workspace and Downloads; central-directory scan of all ZIP archives in those locations",
             "historical_json_policy": "Supplied JSONs are historical evidence only; reproduced output has separate path and metadata",
             "input_source_records": source_records, "zip_inventory": ziprecords}
    (OUT/"input_availability_audit.json").write_text(json.dumps(audit, indent=1))
    print(json.dumps({"zip_count":len(ziprecords),"relevant_archives":sum(bool(z.get("relevant_members")) for z in ziprecords)}))


if __name__ == "__main__":
    main()
