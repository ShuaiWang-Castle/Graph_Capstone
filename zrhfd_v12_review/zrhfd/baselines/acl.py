"""The ACL lazy-walk local-push primitive, with explicit conductance selection."""
from collections import deque
import time
import numpy as np
from ._common import conductance, mass_grid, neighbors, source_record, sweep, validate_query


def local_push(graph, seed, alpha, rho, max_updates, deadline):
    if not 0 < alpha < 1 or rho <= 0:
        raise ValueError("ACL requires 0<alpha<1 and rho>0")
    residual = np.zeros(graph.n, dtype=np.float64)
    rank = np.zeros(graph.n, dtype=np.float64)
    residual[seed] = 1.0
    queue = deque([seed]) if residual[seed] > rho * graph.degree[seed] else deque()
    queued = set(queue)
    touched = {seed}
    updates = 0
    reason = "residual_tolerance"
    while queue:
        if updates >= max_updates:
            reason = "max_updates"
            break
        if time.perf_counter() >= deadline:
            reason = "time_budget"
            break
        v = queue.popleft()
        queued.remove(v)
        direction = residual[v]
        if direction <= rho * graph.degree[v]:
            continue
        rank[v] += alpha * direction
        residual[v] = (1 - alpha) * direction / 2
        if residual[v] > rho * graph.degree[v]:
            queued.add(v)
            queue.append(v)
        for node, weight in neighbors(graph, v):
            u = int(node)
            touched.add(u)
            residual[u] += (1 - alpha) * direction * float(weight) / (2 * graph.degree[v])
            if residual[u] > rho * graph.degree[u] and u not in queued:
                queued.add(u)
                queue.append(u)
        updates += 1
    return rank, residual, sorted(touched), updates, reason


def run(graph, seed, config, oracle_volume=None):
    started = time.perf_counter()
    degree = validate_query(graph, seed)
    if degree == 0:
        return {"vertices": [seed], "runtime_seconds": time.perf_counter() - started, "touched_vertices": [seed], "metadata": {"method": "ACL-paper-port", "stop": "isolated_seed", "oracle": oracle_volume is not None}}
    deadline = started + float(config.get("budget_seconds", 1e30))
    alphas = [float(x) for x in config.get("alpha_grid", [config.get("alpha", .15)])]
    if oracle_volume is not None:
        rhos = [float(config.get("rho_volume_factor", 1.0)) / float(oracle_volume)]
        scale_policy = "explicit_oracle_volume"
    elif "rho_grid" in config:
        rhos = [float(x) for x in config["rho_grid"]]
        scale_policy = "explicit_truth_free_rho_grid"
    elif config.get("use_scale_grid", False):
        masses, scale_policy = mass_grid(graph, seed, config)
        rhos = [float(config.get("rho_volume_factor", 1.0)) / mass for mass in masses]
    else:
        rhos, scale_policy = [float(config.get("rho", 1e-6))], "fixed_truth_free_rho"
    touched, trials = set(), []
    best, best_phi = [seed], conductance(graph, [seed])
    for alpha in alphas:
        for rho in rhos:
            rank, residual, seen, updates, reason = local_push(graph, seed, alpha, rho, int(config.get("max_updates", 1000000)), deadline)
            touched.update(seen)
            scores = np.divide(rank, graph.degree, out=np.zeros_like(rank), where=graph.degree > 0)
            vertices, phi = sweep(graph, scores, seed, config.get("require_seed", False), config.get("keep_ties", False))
            if vertices and phi < best_phi:
                best, best_phi = vertices, phi
            residual_density = np.divide(residual, graph.degree, out=np.zeros_like(residual), where=graph.degree > 0)
            trials.append({"alpha": alpha, "rho": rho, "updates": updates, "stop": reason, "conductance": phi if np.isfinite(phi) else None, "max_residual_degree_ratio": float(residual_density.max()), "mass_conservation_residual": float(abs(rank.sum() + residual.sum() - 1))})
            if reason == "time_budget":
                break
        if time.perf_counter() >= deadline:
            break
    return {"vertices": sorted(best), "runtime_seconds": time.perf_counter() - started, "touched_vertices": sorted(touched), "metadata": {"method": "ACL-paper-port", "sources": source_record("localgraphclustering", ["localgraphclustering/algorithms/acl_list.py"]), "objective": "lazy personalized PageRank; conductance sweep", "oracle": oracle_volume is not None, "scale_policy": scale_policy, "selection": "minimum output conductance; first tied configuration", "require_seed_in_sweep": bool(config.get("require_seed", False)), "keep_ties": bool(config.get("keep_ties", False)), "stop": "query_budget" if time.perf_counter() >= deadline else "configuration_grid_finished", "update_count": sum(t["updates"] for t in trials), "trials": trials, "touched_definition": "union of pushed vertices and their scanned graph neighbors; dense rank/residual allocations are included in runtime"}}
