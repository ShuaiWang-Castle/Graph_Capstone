from ._native import run_native


def run(graph, seed, config, oracle_volume=None):
    return run_native("hfd", graph, seed, config, oracle_volume)


def solve_hyper(h, seed, mass, sigma=1e-4, tolerance=1e-6,
                support_tolerance=1e-7, iterations=50, budget_seconds=600,
                artifact_directory="reviews/baselines/execution_logs"):
    """Actual author unit-cut HFD; fixed AM budget, final excess-derived x.

    Unsupported edge models fail explicitly. Tolerances are recorded as
    requests, since retained author ucHFD has no KKT or support-tolerance stop.
    """
    from pathlib import Path
    import math
    import tempfile
    import time
    import numpy as np
    from ._common import ROOT, source_record, validate_query
    from ._execution import execute_julia
    started = time.perf_counter()
    validate_query(h, seed)
    if not math.isfinite(float(mass)) or mass <= 0 or not math.isfinite(float(sigma)) or sigma <= 0 or iterations < 1:
        raise ValueError("Invalid native hypergraph HFD mass, sigma or iteration count")
    edges = []
    reconstructed_degree = np.zeros(h.n, dtype=np.float64)
    for vertices, theta, profile in h.edges:
        order = len(vertices)
        if theta != 1 or order < 2 or len(profile) != order + 1 or profile[0] != 0 or profile[-1] != 0 or any(value != 1 for value in profile[1:-1]):
            raise NotImplementedError("Author unit-HFD adapter requires unweighted all-or-nothing set hyperedges")
        if len(set(vertices)) != order or any(not 0 <= int(v) < h.n for v in vertices):
            raise ValueError("Invalid set hyperedge in native adapter")
        edges.append(tuple(int(v) for v in vertices))
        reconstructed_degree[list(vertices)] += 1
    if not np.array_equal(h.degree, reconstructed_degree):
        raise ValueError("Hypergraph degree and unit incidence disagree")
    sources = source_record("hfd", ["ucHFD.jl", "utils.jl", "struct.jl"])
    config = {"artifact_directory": artifact_directory}
    directory = ROOT / "reviews/baselines/native-tmp"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hyper_hfd_", dir=directory) as temp:
        edgepath = Path(temp) / "edges.csv"
        edgepath.write_text("".join(",".join(str(v) for v in edge) + "\n" for edge in edges))
        args = [str(ROOT / "external/runtime/julia-1.10.10/bin/julia"), "--startup-file=no", "--threads=1", "--project=" + str(ROOT / "external/runtime/hfd-environment"), str(ROOT / "zrhfd/baselines/native_driver.jl"), "hfd_hyper", str(ROOT / "external/hfd"), str(edgepath), str(h.n), str(seed), str(sigma), str(int(iterations)), "2", str(float(mass)), "73", "0.001", "0.01"]
        trials, execution = execute_julia(args, config, started + float(budget_seconds), sources)
    if execution["status"] == "COMPLETED" and len(trials) != 1:
        raise RuntimeError("Author hypergraph source did not return the requested single mass")
    trial = trials[0] if trials else None
    heights = np.array(trial["dual_heights"] if trial else np.zeros(h.n), dtype=np.float64)
    if heights.shape != (h.n,) or not np.isfinite(heights).all() or np.any(heights < 0):
        raise FloatingPointError("Invalid author hypergraph dual heights")
    telemetry = {"method": "unit-HFD-author-Julia", "sources": sources, "objective": "HFD p=2 unit-cut quadratic dual", "sigma": sigma, "mass": mass, "requested_kkt_tolerance": tolerance, "requested_support_tolerance": support_tolerance, "tolerances_applied": False, "iterations": iterations, "updates": iterations if trial else "UNKNOWN: timeout", "stop": "fixed_author_AM_iterations" if execution["status"] == "COMPLETED" else "TIMEOUT", "status": execution["status"], "execution": execution, "scores_definition": "final author excess / degree / sigma; zero for isolated vertices; source strict-positive support retained", "scores_iteration": "final iterate; author best-conductance cluster retained separately", "author_cluster": trial["vertices"] if trial else [], "author_conductance": trial["conductance"] if trial else None, "kernel_seconds": trial["kernel_seconds"] if trial else None, "runtime_seconds": time.perf_counter() - started, "touched_vertices": list(range(h.n)), "native_trial": trial}
    return heights, telemetry
