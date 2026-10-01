"""Invoke actual author Julia CPU sources; include subprocess startup in cost."""
from pathlib import Path
import json
import math
import tempfile
import time
from ._common import ROOT, conductance, mass_grid, source_record, validate_query
from ._execution import execute_julia


def run_native(mode, graph, seed, config, oracle_volume=None):
    started = time.perf_counter()
    degree = validate_query(graph, seed)
    if degree == 0:
        return {"vertices": [seed], "runtime_seconds": time.perf_counter() - started, "touched_vertices": [seed], "metadata": {"method": mode + "-author-Julia", "stop": "isolated_seed", "oracle": oracle_volume is not None}}
    if any((len(e) > 2 and float(e[2]) != 1.0) for e in graph.edges):
        raise ValueError("Retained native author graph adapters support unweighted inputs only")
    masses, mass_policy = mass_grid(graph, seed, config, oracle_volume)
    if not masses:
        return {"vertices": [seed], "runtime_seconds": time.perf_counter() - started, "touched_vertices": [seed], "metadata": {"method": mode + "-author-Julia", "stop": "no_admissible_mass", "mass_policy": mass_policy, "oracle": oracle_volume is not None}}
    repository = "hfd" if mode == "hfd" else "pnormflowdiffusion"
    files = ["ucHFD.jl", "utils.jl", "struct.jl"] if mode == "hfd" else ["pNormDiffusion.jl", "utils.jl", "struct.jl"]
    sources = source_record(repository, files)
    julia = ROOT / config.get("julia_binary", "external/runtime/julia-1.10.10/bin/julia")
    if not julia.is_file():
        raise RuntimeError("Author baseline Julia runtime is unavailable")
    temp_root = ROOT / "reviews/baselines/native-tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    iterations = int(config.get("iterations", 50))
    sigma = float(config.get("sigma", 1e-4))
    p = float(config.get("p", 2.0 if mode == "hfd" else 4.0))
    if iterations < 1 or not math.isfinite(p) or p < 2 or not math.isfinite(sigma) or sigma <= 0:
        raise ValueError("Invalid author baseline iteration, exponent or regularization parameter")
    rng_seed = int(config.get("random_seed", 73))
    with tempfile.TemporaryDirectory(prefix=mode + "_", dir=temp_root) as temp:
        edgepath = Path(temp) / "edges.csv"
        edgepath.write_text("".join(str(int(e[0])) + "," + str(int(e[1])) + "\n" for e in graph.edges), encoding="utf-8")
        args = [str(julia), "--startup-file=no", "--threads=1", "--project=" + str(ROOT / "external/runtime/hfd-environment"), str(ROOT / "zrhfd/baselines/native_driver.jl"), mode, str(ROOT / "external" / repository), str(edgepath), str(graph.n), str(seed), str(sigma), str(iterations), str(p), ",".join(str(x) for x in masses), str(rng_seed), str(float(config.get("epsilon", 1e-3))), str(float(config.get("cm_tol", 1e-2)))]
        trials, execution = execute_julia(args, config, started + float(config.get("budget_seconds", 600)), sources)
    if execution["status"] == "COMPLETED" and len(trials) != len(masses):
        raise RuntimeError("Author baseline did not return the complete requested mass grid")
    available = [t for t in trials if t["vertices"] and t["conductance"] is not None]
    best = min(available, key=lambda t: t["conductance"]) if available else None
    objective = ("HFD p-norm primal / quadratic dual" if p == 2 else "HFD p-norm primal with degree-weighted excess regularization") if mode == "hfd" else "p-norm flow with hard degree capacities"
    complete = execution["status"] == "COMPLETED"
    stop = ("fixed AM iteration budget and mass grid completed" if mode == "hfd" else "author excess tolerance or pass cap; mass grid completed") if complete else "TIMEOUT"
    metadata = {"method": mode + "-author-Julia", "sources": sources, "objective": objective, "oracle": oracle_volume is not None, "mass_policy": mass_policy, "mass_grid": masses, "mass_grid_complete": complete, "sigma": sigma if mode == "hfd" else None, "p": p, "max_iterations": iterations, "update_count": iterations * len(trials) if mode == "hfd" and complete else "UNKNOWN: incomplete grid or author does not return actual update count", "random_seed": rng_seed, "stop": stop, "status": "COMPLETED" if complete else "PARTIAL_TIMEOUT", "selection": "minimum author conductance across completed masses; first tied mass; native per-iteration/per-prefix tie rules retained", "trials": trials, "kernel_seconds_total": sum(t["kernel_seconds"] for t in trials), "runtime_definition": "wrapper entry to return, including full input conversion and Julia cold process startup; source kernel times retained separately", "touched_definition": "full graph input conversion; HFD also scans all nodes each iteration; p-norm diagnostic maximum-excess scan is global and included in outer cost", "execution": execution}
    return {"vertices": sorted(best["vertices"]) if best else [seed], "runtime_seconds": time.perf_counter() - started, "touched_vertices": list(range(graph.n)), "metadata": metadata}
