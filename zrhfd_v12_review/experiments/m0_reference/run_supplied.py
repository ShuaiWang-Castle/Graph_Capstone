"""Execute unchanged supplied checks through an explicitly identified import shim.

Run separately for each script, from the project root. Source outputs are written
under results/m0_reference and input files are never modified. Instrumentation
observes the same computations without changing reference decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import time

sys.dont_write_bytecode = True

import networkx as nx
import numba
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
THEORY = ROOT / "inputs/local_hfd/theory"
OUTROOT = ROOT / "results/m0_reference"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script", choices=["checks_g2", "checks_g3b"])
    args = parser.parse_args()
    outdir = OUTROOT / args.script
    outdir.mkdir(parents=True, exist_ok=True)
    if (outdir / "run_metadata.json").exists():
        raise RuntimeError("Raw run exists; refuse to overwrite it")
    sys.path.insert(0, str(THEORY))
    shimpath = Path(__file__).with_name("core.py")
    spec = importlib.util.spec_from_file_location("core", shimpath)
    shim = importlib.util.module_from_spec(spec)
    sys.modules["core"] = shim
    spec.loader.exec_module(shim)
    import zr_pipeline as ref
    catalog = json.loads((ROOT / "data/dev/same12/catalog.json").read_text())
    events = []
    instance = {"index": -1, "mm": None}
    cache = {}
    original_sbm, original_flow, original_sweep, original_mm = ref.sbm, ref.flow_cd, ref.zsweep, ref.mm
    original_cut = nx.minimum_cut

    def sbm(*a):
        A, lab = original_sbm(*a)
        instance["index"] += 1
        instance["A"] = A
        expected = catalog["cases"][instance["index"]]
        observed_sha = hashlib.sha256(A.astype("<f8", copy=False).tobytes(order="C")).hexdigest()
        if observed_sha != expected["adjacency_float64_le_c_sha256"]:
            raise RuntimeError("Source run graph diverged from frozen same12 catalog")
        events.append({"event": "instance", "case_index": instance["index"], "case_id": expected["case_id"], "A_sha256": observed_sha})
        return A, lab

    def flow(*a):
        ptr, idx, degree, seed, mass, sigma, tol, cap = a
        expected = catalog["cases"][instance["index"]]
        if int(seed) != expected["seed"]:
            raise RuntimeError("Source seed diverged from frozen same12 query")
        key = (instance["index"], int(seed), float(mass), float(sigma), float(tol), int(cap))
        start = time.perf_counter()
        cached = key in cache
        if cached:
            result = cache[key]
        else:
            result = original_flow(*a)
            cache[key] = result
        elapsed = time.perf_counter() - start
        x = result[0]
        A = instance["A"]
        grad = (1 + sigma) * degree * x - A @ x + degree
        grad[seed] -= mass
        residual = np.where(x > 0, np.abs(grad), np.maximum(-grad, 0))
        U = x > 0
        boundary = float(np.sum(x[U] * A[U][:, ~U].sum(axis=1)))
        conservation = float(mass - degree[U].sum() - boundary - sigma * np.dot(degree[U], x[U]))
        objective = float(.5 * np.dot(x, (degree * x - A @ x)) + .5 * sigma * np.dot(degree, x*x) + np.dot(degree, x) - mass*x[seed])
        events.append({"event": "diffusion", "case_index": instance["index"], "seed": int(seed), "mass": float(mass),
                       "sigma": sigma, "tol": tol, "max_updates": cap, "updates": int(result[1]), "coordinate_changes": int(result[2]),
                       "queue_drained": bool(result[3]), "max_queue": int(result[4]), "cached": cached, "seconds": elapsed,
                       "support": np.flatnonzero(U).tolist(), "support_volume": float(degree[U].sum()), "objective": objective,
                       "scaled_kkt_inf": float(np.max(residual / np.maximum(1, degree))), "kkt_inf": float(np.max(residual)),
                       "mass_conservation_residual": conservation, "seed_is_max": bool(x[seed] == np.max(x)),
                       "score_sha256": hashlib.sha256(x.astype("<f8", copy=False).tobytes()).hexdigest()})
        return result

    def sweep(A, d, M, x):
        z, S = original_sweep(A, d, M, x)
        events.append({"event": "sweep", "case_index": instance["index"], "Z": float(z), "S": S.tolist()})
        return z, S

    def cut(G, s, t, *a, **kw):
        value, partition = original_cut(G, s, t, *a, **kw)
        active = instance["mm"]
        if active is not None:
            A, d, M, seed, R, previous, score = active
            Sm = np.zeros(len(d), bool)
            Sm[previous] = True
            lam = ref.Zof(A, d, M, Sm)
            order = sorted(R, key=lambda i: (not Sm[i], -score[i]))
            D = np.cumsum(d[order])
            g = dict(zip(order, D**2 - (D-d[order])**2))
            T = sorted(u for u in partition[0] if u != "S")
            Tm = np.zeros(len(d), bool)
            Tm[T] = True
            candidate_z = float(ref.Zof(A, d, M, Tm))
            unary = {i: float(g[i]/M-lam*d[i]) for i in R}
            objective_T = float(A[Tm][:, ~Tm].sum() + sum(unary[i] for i in T))
            objective_previous = float(A[Sm][:, ~Sm].sum() + sum(unary[i] for i in previous))
            events.append({"event": "mincut", "case_index": instance["index"], "raw_nx_value": float(value),
                           "lambda": float(lam), "candidate_Z": candidate_z, "unary_objective_candidate": objective_T,
                           "unary_objective_current": objective_previous, "candidate": T,
                           "accepted": bool(candidate_z < lam-1e-12), "seed_first": bool(order[0] == seed)})
            if candidate_z < lam-1e-12:
                instance["mm"] = (A, d, M, seed, R, T, score)
        return value, partition

    def mm(A, d, M, seed, R, S, score, maxit=60):
        instance["mm"] = (A, d, M, seed, R, S, score)
        begin = time.perf_counter()
        out, steps = original_mm(A, d, M, seed, R, S, score, maxit)
        events.append({"event": "mm", "case_index": instance["index"], "R": list(map(int,R)), "S0": list(map(int,S)),
                       "out": list(map(int,out)), "accepted_steps": int(steps), "seconds": time.perf_counter()-begin})
        instance["mm"] = None
        return out, steps

    ref.sbm, ref.flow_cd, ref.zsweep, ref.mm = sbm, flow, sweep, mm
    nx.minimum_cut = cut
    start = time.perf_counter()
    metadata = {"script": args.script, "status": "running", "reference_type": "unchanged supplied script with reconstructed missing flow_cd",
                "python": sys.version, "platform": platform.platform(), "numpy": np.__version__, "networkx": nx.__version__, "numba": numba.__version__,
                "environment": {k: os.environ.get(k) for k in ["OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMBA_NUM_THREADS"]},
                "source_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in [THEORY/f"{args.script}.py", THEORY/"zr_pipeline.py", ROOT/"inputs/local_hfd/kernels.py", shimpath]},
                "diffusion_cache": "same graph,seed,mass,sigma,tol,cap; exact result tuple reused",
                "input_catalog_sha256": sha(ROOT/"data/dev/same12/catalog.json")}
    try:
        os.chdir(outdir)
        runpy.run_path(str(THEORY/f"{args.script}.py"), run_name="__main__")
        metadata["status"] = "completed"
    except BaseException as exc:
        metadata["status"] = "failed"
        metadata["error"] = repr(exc)
        raise
    finally:
        metadata["total_seconds"] = time.perf_counter()-start
        (outdir/"events.json").write_text(json.dumps(events, indent=1))
        (outdir/"run_metadata.json").write_text(json.dumps(metadata, indent=1))


if __name__ == "__main__":
    main()
