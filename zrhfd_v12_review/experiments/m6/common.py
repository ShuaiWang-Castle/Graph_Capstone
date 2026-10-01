"""M6 provenance and immutable input helpers (no algorithm import)."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "experiments/m6/config.json"
MANIFEST = ROOT / "results/m6/manifest.json"
SOURCE_FILES = [
    "zrhfd/__init__.py", "zrhfd/graph.py", "zrhfd/storage.py",
    "zrhfd/diffusion.py", "zrhfd/sweep.py", "zrhfd/mincut.py",
    "zrhfd/certificate.py", "zrhfd/pipeline.py", "work/bin/mincut128",
    "experiments/m6/config.json", "experiments/m6/common.py",
    "experiments/m6/run.py", "experiments/m6/worker.py",
    "experiments/m6/summarize.py",
]

def utc():
    return datetime.now(timezone.utc).isoformat()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def json_default(value):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=json_default, allow_nan=False) + "\n"

def object_sha(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(encoded(value))
    os.replace(temp, path)

def immutable(path, value):
    path = Path(path)
    text = encoded(value)
    if path.exists():
        if path.read_text() != text:
            raise RuntimeError(f"Immutable record differs: {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(text)

def sources():
    return {name: sha(ROOT / name) for name in SOURCE_FILES}

def check_sources(manifest):
    actual = sources()
    differences = [p for p, expected in manifest["source_sha256"].items()
                   if actual.get(p) != expected]
    if differences:
        raise RuntimeError("Frozen M6 sources differ: " + ", ".join(differences))
    if manifest.get("dependency_fingerprint") != dependency_fingerprint():
        raise RuntimeError("Frozen M6 dependency distribution records differ")

def dependency_fingerprint():
    records = {}
    for name in ("numpy", "scipy", "numba", "llvmlite"):
        distribution = importlib.metadata.distribution(name)
        record = next((file for file in distribution.files or []
                       if str(file).endswith(".dist-info/RECORD")), None)
        records[name] = {"version": distribution.version,
            "distribution_record_sha256": sha(distribution.locate_file(record)) if record else None}
    return {"python_binary_sha256": sha(Path(os.sys.executable).resolve()),
            "python_version": os.sys.version, "packages": records}

def single_thread_env(cache):
    env = os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               NUMBA_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1",
               NUMBA_CACHE_DIR=str(cache), PYTHONHASHSEED="0")
    return env

def load_schedule():
    cfg = read(CONFIG)
    catalog_path = ROOT / cfg["catalog"]
    if sha(catalog_path) != cfg["catalog_sha256"]:
        raise RuntimeError("Scale catalog hash differs")
    catalog = read(catalog_path)
    cases = sorted(catalog["cases"], key=lambda row: (row["n"], row["generation_seed"]))
    rows = []
    for case in cases:
        if case["status"] != "CALIBRATED":
            raise RuntimeError("Formal scale input was not accepted as calibrated")
        for key in ("queries", "truth"):
            if sha(ROOT / case[f"{key}_path"]) != case[f"{key}_sha256"]:
                raise RuntimeError(f"Frozen {key} differs for {case['case_id']}")
        metadata_path = Path(case["csr_path"]) / "csr_metadata.json"
        if sha(ROOT / metadata_path) != case["csr_metadata_sha256"]:
            raise RuntimeError("Frozen CSR metadata differs")
        meta = read(ROOT / metadata_path)
        queries = read(ROOT / case["queries_path"])["queries"]
        for index, query in enumerate(queries):
            rows.append({
                "query_id": f"{case['case_id']}_q{index:02d}",
                "case_id": case["case_id"], "n": case["n"],
                "generation_seed": case["generation_seed"], "query_index": index,
                "seed": int(query["seed"]),
                "csr_path": case["csr_path"],
                "csr_metadata_sha256": case["csr_metadata_sha256"],
                "csr_array_sha256": meta["sha256"],
                "native_network_sha256": meta["source_network_sha256"],
                "native_community_sha256": meta["source_community_sha256"],
                "offline_only": {"community_index": int(query["community_index"]),
                    "truth_path": case["truth_path"], "truth_sha256": case["truth_sha256"],
                    "queries_path": case["queries_path"],
                    "queries_sha256": case["queries_sha256"]},
            })
    if len(cases) != cfg["expected_graphs"] or len(rows) != cfg["expected_queries"]:
        raise RuntimeError("Scale schedule does not have the frozen 9 graphs / 108 queries")
    return cfg, rows
