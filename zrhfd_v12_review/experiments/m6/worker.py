"""One isolated M6 query; label access occurs strictly after the method."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import platform
import resource
import sys
import time
import traceback
from pathlib import Path
from dataclasses import asdict

from common import ROOT, atomic, check_sources, encoded, read, sha, utc
sys.path.insert(0, str(ROOT))

def make_toy(directory):
    """Fixed topology only, without communities or truth labels."""
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    n = 64
    neighbors = [sorted({(u + offset) % n for offset in (-4, -2, -1, 1, 2, 4)})
                 for u in range(n)]
    arrays = {"indptr": np.arange(0, 6 * (n + 1), 6, dtype=np.int64),
              "indices": np.asarray(neighbors, dtype=np.int32).ravel(),
              "weights": np.ones(6 * n, dtype=np.float64),
              "degree": np.full(n, 6.0, dtype=np.float64)}
    for name, values in arrays.items():
        np.save(directory / f"{name}.npy", values, allow_pickle=False)
    atomic(directory / "csr_metadata.json", {"n": n, "total_volume": 6 * n,
        "integer_weights": True, "files": {k: f"{k}.npy" for k in arrays},
        "sha256": {k: sha(directory / f"{k}.npy") for k in arrays},
        "purpose": "UNLABELED_SIGNATURE_WARMUP_ONLY"})

def warmup(directory, cfg, checkpoint):
    import numpy as np
    import numba
    from zrhfd.storage import load_csr
    from zrhfd.diffusion import _coordinate_queue, _local_telemetry
    from zrhfd.pipeline import run
    make_toy(directory)
    toy = load_csr(directory)
    args1 = (toy.indptr, toy.indices, toy.weights, toy.degree, 0, 18.0,
             cfg.sigma, cfg.diffusion_tolerance, cfg.max_updates)
    args2 = (toy.indptr, toy.indices, toy.weights, toy.degree,
             np.zeros(toy.n, dtype=np.float64), np.asarray([0], dtype=np.int64),
             0, 18.0, cfg.sigma)
    info = {"arrays": {k: {"dtype": str(getattr(toy, k).dtype),
        "readonly": not getattr(toy, k).flags.writeable,
        "numba_type": str(numba.typeof(getattr(toy, k)))}
        for k in ("indptr", "indices", "weights", "degree")}, "dispatchers": []}
    total = 0.0
    for dispatcher, args in ((_coordinate_queue, args1), (_local_telemetry, args2)):
        signature = tuple(numba.typeof(value) for value in args)
        started = time.perf_counter()
        dispatcher.compile(signature)
        elapsed = time.perf_counter() - started
        total += elapsed
        info["dispatchers"].append({"name": dispatcher.py_func.__name__,
            "argument_types": [str(s) for s in signature],
            "compile_or_cache_seconds": elapsed,
            "cache_hits": {str(k): int(v) for k, v in dispatcher._cache_hits.items()},
            "cache_misses": {str(k): int(v) for k, v in dispatcher._cache_misses.items()},
            "signatures": [str(s) for s in dispatcher.signatures]})
    checkpoint({"stage": "numba_ready", "numba_compile_or_cache_seconds": total})
    signatures_before = [list(d.signatures) for d in (_coordinate_queue, _local_telemetry)]
    started = time.perf_counter()
    output = run(toy, 0, cfg)
    info["toy_pipeline_warmup_seconds"] = time.perf_counter() - started
    info["numba_compile_or_cache_seconds"] = total
    info["toy_status"] = output["status"]
    info["toy_seed"] = 0
    info["signature_added_by_toy_execution"] = any(
        before != list(dispatcher.signatures) for before, dispatcher in
        zip(signatures_before, (_coordinate_queue, _local_telemetry)))
    if info["signature_added_by_toy_execution"]:
        raise RuntimeError("Unlabeled toy execution introduced an unwarmed signature")
    return toy, info

def evaluate(graph, output, offline):
    """Full static offline coverage; never launches an additional diffusion."""
    if sha(ROOT / offline["truth_path"]) != offline["truth_sha256"]:
        raise RuntimeError("Offline truth hash differs")
    truth = read(ROOT / offline["truth_path"])["communities"]
    community_index = offline["community_index"]
    C = set(map(int, truth[community_index]))
    R = set(output["region_vertices"])
    S = set(output["vertices"])
    H = set(output["certificate"]["hull_best"])
    def quality(T):
        overlap = len(T & C)
        return {"precision": overlap / len(T) if T else 0.0,
                "recall": overlap / len(C),
                "F1": 2 * overlap / (len(T) + len(C)),
                "symmetric_difference": len(T ^ C)}
    truth_stats = graph.stats(C)
    target_volume = truth_stats["volume"]
    intersections = [{"community_index": j, "size": len(nodes),
        "region_intersection_size": len(R.intersection(nodes)),
        "region_covered_fraction": len(R.intersection(nodes)) / len(nodes)}
        for j, nodes in enumerate(truth)]
    rho = max((r["region_covered_fraction"] for r in intersections
               if r["community_index"] != community_index), default=0.0)
    return {"quality": quality(S), "hull_best_quality": quality(H),
        "truth_stats": truth_stats, "community_index": community_index,
        "target_size": len(C), "target_volume": target_volume,
        "target_size_outlier_from_native_requested_bounds": not 100 <= len(C) <= 200,
        "covered": C.issubset(R), "rho_hat": rho,
        "region_missing_truth_vertices": sorted(C - R),
        "region_outside_truth_vertices": sorted(R - C),
        "region_outside_truth_volume": float(graph.degree[list(R - C)].sum()),
        "region_outside_truth_volume_ratio": float(graph.degree[list(R - C)].sum()) / target_volume,
        "truth_community_region_intersections": intersections,
        "failure_class": None if S == C else ("H1" if not C.issubset(R) else "H2"),
        "touched_over_output_volume": output["touched_volume"] / output["stats"]["volume"]}

def execute(request_path):
    started = time.perf_counter()
    request = read(request_path)
    outdir = request_path.parent
    timing = {}
    progress_io = {"seconds": 0.0, "events": 0, "bytes": 0}
    def checkpoint(event):
        began = time.perf_counter()
        packet = {"timestamp_utc": utc(), "worker_elapsed_seconds": began - started,
                  "event": event}
        atomic(outdir / "checkpoint.json", packet)
        line = encoded(packet)
        with (outdir / "progress.jsonl").open("a") as stream:
            stream.write(line)
        progress_io["seconds"] += time.perf_counter() - began
        progress_io["events"] += 1
        progress_io["bytes"] += len(line.encode())
    checkpoint({"stage": "worker_started"})
    try:
        before = time.perf_counter()
        if request.get("manifest_path"):
            manifest = read(ROOT / request["manifest_path"])
            if sha(ROOT / request["manifest_path"]) != request["manifest_sha256"]:
                raise RuntimeError("Manifest hash differs")
            check_sources(manifest)
        else:
            from common import sources
            if sources() != request["source_sha256"]:
                raise RuntimeError("Smoke source snapshot differs")
        timing["source_verification_seconds"] = time.perf_counter() - before
        before = time.perf_counter()
        import numpy as np
        import numba
        from zrhfd.pipeline import Config, run
        from zrhfd.storage import load_csr
        from zrhfd.diffusion import _coordinate_queue, _local_telemetry
        cfg = Config(**{**request["method_config"], "fixed_grid": tuple(request["method_config"]["fixed_grid"])})
        if json.loads(json.dumps(asdict(Config()))) != request["method_config"]:
            raise RuntimeError("Requested main Config differs from current default Config")
        timing["imports_seconds"] = time.perf_counter() - before
        checkpoint({"stage": "warmup_started"})
        toy, warm = warmup(outdir / "toy_csr", cfg, checkpoint)
        timing.update({k: warm[k] for k in ("numba_compile_or_cache_seconds", "toy_pipeline_warmup_seconds")})
        atomic(outdir / "warmup.json", warm)
        checkpoint({"stage": "input_load_started"})
        before = time.perf_counter()
        if request["mode"] == "smoke":
            graph = toy
        else:
            metadata = ROOT / request["query"]["csr_path"] / "csr_metadata.json"
            if sha(metadata) != request["query"]["csr_metadata_sha256"]:
                raise RuntimeError("CSR metadata hash differs")
            graph = load_csr(metadata, verify_hashes=False)
        timing["input_load_seconds"] = time.perf_counter() - before
        for key in ("indptr", "indices", "weights", "degree"):
            actual, template = getattr(graph, key), getattr(toy, key)
            if numba.typeof(actual) != numba.typeof(template) or actual.flags.writeable:
                raise RuntimeError(f"Formal CSR signature differs from warmup: {key}")
        signatures_before = [list(d.signatures) for d in (_coordinate_queue, _local_telemetry)]
        seed = request["seed"] if request["mode"] == "smoke" else request["query"]["seed"]
        checkpoint({"stage": "method_started", "n": graph.n, "seed": seed})
        before = time.perf_counter()
        output = run(graph, seed, cfg, progress=checkpoint)
        timing["method_hot_wall_seconds"] = time.perf_counter() - before
        timing["pipeline_internal_seconds"] = output["runtime_seconds"]
        timing["diffusion_sum_seconds"] = sum(x["runtime_seconds"] for x in output["diffusion_trace"])
        signature_added = any(before != list(dispatcher.signatures) for before, dispatcher in
                              zip(signatures_before, (_coordinate_queue, _local_telemetry)))
        if signature_added:
            raise RuntimeError("Formal method introduced an unwarmed Numba signature")
        # Preserve the entire algorithm result before any potentially interrupted
        # label loading, offline evaluation, or final record serialization.
        before = time.perf_counter()
        atomic(outdir / "method_result.json", {"schema_version": 1,
            "query_id": request["query_id"], "status": "method_completed",
            "timestamp_utc": utc(), "timing": timing, "raw_output": output})
        timing["raw_method_serialization_seconds"] = time.perf_counter() - before
        checkpoint({"stage": "method_completed", "runtime_seconds": timing["method_hot_wall_seconds"]})
        before = time.perf_counter()
        offline = None if request["mode"] == "smoke" else evaluate(graph, output, request["query"]["offline_only"])
        timing["offline_evaluation_seconds"] = time.perf_counter() - before
        if request.get("manifest_path"):
            check_sources(manifest)
        timing["worker_to_result_seconds"] = time.perf_counter() - started
        result = {"schema_version": 1, "status": "completed", "mode": request["mode"],
            "request_sha256": sha(request_path), "timestamp_utc": utc(),
            "query_id": request["query_id"], "n": graph.n, "seed": seed,
            "timing": timing, "progress_io": progress_io,
            "readonly_csr_signatures_match_warmup": True, "signature_added_during_method": False,
            "raw_output": output, "offline_only": offline,
            "runtime": {"python": sys.version, "executable": sys.executable,
                "platform": platform.platform(), "machine": platform.machine(),
                "max_rss_bytes_macos": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "packages": {k: importlib.metadata.version(k) for k in ("numpy", "scipy", "numba")}},
            "provenance": {k: request[k] for k in ("method_config", "source_sha256")},
            "input": request.get("query")}
        atomic(outdir / "result.json", result)
        checkpoint({"stage": "result_written"})
        print(json.dumps({"status": "completed", "query_id": request["query_id"], "timing": timing}))
        return 0
    except BaseException as error:
        trace = traceback.format_exc()
        atomic(outdir / "error.json", {"status": "error", "error_type": type(error).__name__,
            "message": str(error), "traceback": trace, "timing": timing,
            "worker_elapsed_seconds": time.perf_counter() - started, "progress_io": progress_io})
        checkpoint({"stage": "worker_error", "error_type": type(error).__name__, "message": str(error)})
        print(trace, file=sys.stderr)
        return 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    arguments = parser.parse_args()
    sys.exit(execute(arguments.request))
