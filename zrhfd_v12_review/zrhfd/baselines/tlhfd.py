"""TL*: an explicit Algorithm-1 implementation, never an HFD proxy."""
import math
import time
from ._common import conductance, mass_grid, neighbors, sweep, validate_query


SOURCE = "https://arxiv.org/html/2606.09340v1#alg1"


def graph_objective(graph, heights, seed, mass, sigma):
    active = set(heights)
    quadratic = 0.0
    for v in active:
        for node, weight in neighbors(graph, v):
            u = int(node)
            if u not in active or v < u:
                quadratic += float(weight) * (heights[v] - heights.get(u, 0.0)) ** 2
    regularizer = sum(float(graph.degree[v]) * x * x for v, x in heights.items())
    linear = sum(float(graph.degree[v]) * x for v, x in heights.items()) - mass * heights.get(seed, 0.0)
    return .5 * quadratic + .5 * sigma * regularizer + linear


def algorithm_one(graph, heights, seed, mass, sigma, eta, k, gamma):
    """Simultaneous old-iterate update and committed top-k boundary activation."""
    active = set(heights) | {seed}
    boundary = set()
    gradients = {v: float(graph.degree[v]) * (1 + sigma * heights.get(v, 0.0)) - (mass if v == seed else 0) for v in active}
    inward = {}
    for v in sorted(active):
        xv = heights.get(v, 0.0)
        for node, weight in neighbors(graph, v):
            u, w = int(node), float(weight)
            gradients[v] += w * (xv - heights.get(u, 0.0))
            if u not in active:
                if u not in boundary:
                    boundary.add(u)
                    gradients[u] = float(graph.degree[u])
                    inward[u] = 0.0
                gradients[u] -= w * xv
                inward[u] += w
    result = {}
    for v in active:
        degree = float(graph.degree[v])
        if degree > 0:
            value = max(0.0, heights.get(v, 0.0) - eta * gradients[v] / degree)
            if value > 0:
                result[v] = value
    scores = []
    pushes = {}
    for v in boundary:
        degree = float(graph.degree[v])
        push = max(0.0, -gradients[v] / degree)
        pushes[v] = push
        scores.append((push * (inward[v] / degree) ** gamma, v))
    chosen = sorted(scores, key=lambda item: (-item[0], item[1]))[:k]
    for _, v in chosen:
        value = eta * pushes[v]
        if value > 0:
            result[v] = value
    if any(not math.isfinite(x) for x in result.values()):
        raise FloatingPointError("Nonfinite TL* Algorithm-1 iterate")
    chosen_vertices = {u for _, u in chosen}
    skipped = sum(float(graph.degree[v]) * pushes[v] for v in boundary if v not in chosen_vertices)
    return result, active | boundary, {"active_nodes": len(active), "boundary_nodes": len(boundary), "activated_positive_nodes": sum(pushes[v] > 0 for _, v in chosen), "skipped_push_degree_sum": skipped}


def run(graph, seed, config, oracle_volume=None):
    backend = config.get("backend", "literal")
    if backend == "numba":
        from .tlhfd_numba import run as accelerated_run
        return accelerated_run(graph, seed, config, oracle_volume)
    if backend != "literal":
        raise ValueError("Unknown explicit Algorithm1 backend")
    started = time.perf_counter()
    degree = validate_query(graph, seed)
    if degree == 0:
        return {"vertices": [seed], "runtime_seconds": time.perf_counter() - started, "touched_vertices": [seed], "metadata": {"method": "TL*-Algorithm1", "stop": "isolated_seed", "oracle": oracle_volume is not None}}
    if "step_schedule" not in config:
        raise ValueError("TL* requires an explicit step_schedule: experimental step size was not disclosed in the paper")
    schedule = config["step_schedule"]
    if schedule not in {"theory", "constant", "sqrt_decay"}:
        raise ValueError("Unknown explicit TL* step schedule")
    if schedule != "theory" and "step_size" not in config:
        raise ValueError("This TL* schedule requires explicit step_size")
    sigma = float(config.get("sigma", 1e-4))
    gamma = float(config.get("gamma", 1.0))
    iterations = int(config.get("iterations", 500))
    if sigma <= 0 or gamma < 0 or iterations < 1:
        raise ValueError("Invalid TL* parameters")
    return_policy = config.get("return_policy", "best_dual")
    if return_policy not in {"best_dual", "last", "best_sweep"}:
        raise ValueError("Unknown explicit TL* iterate selection")
    deadline = started + float(config.get("budget_seconds", 1e30))
    masses, mass_policy = mass_grid(graph, seed, config, oracle_volume)
    fractions = [float(f) for f in config.get("fraction_grid", [.01, .02, .03, .05])]
    trials, touched = [], {seed}
    best_vertices, best_phi = [seed], conductance(graph, [seed])
    for mass in masses:
        ks = [int(k) for k in config["k_grid"]] if "k_grid" in config else [max(1, int(math.floor(f * mass / float(config.get("injection_factor", 3.0)) + .5))) for f in fractions]
        for ki, k in enumerate(ks):
            if k < 0:
                raise ValueError("TL* k must be nonnegative")
            heights = {}
            best_heights = {}
            best_objective = 0.0
            selected_epoch = 0
            trial_vertices = []
            trial_phi = math.inf
            diagnostics = []
            reason = "fixed_iterations"
            for epoch in range(iterations):
                if time.perf_counter() >= deadline:
                    reason = "time_budget"
                    break
                objective = graph_objective(graph, heights, seed, mass, sigma)
                if not math.isfinite(objective):
                    raise FloatingPointError("Nonfinite TL* objective at mass/configuration/iteration " + str((mass, k, epoch)))
                if objective < best_objective:
                    best_objective, best_heights, selected_epoch = objective, dict(heights), epoch
                if return_policy == "best_sweep":
                    vertices, phi = sweep(graph, heights, seed, config.get("require_seed", False), config.get("keep_ties", False))
                    if vertices and phi < trial_phi:
                        trial_vertices, trial_phi, selected_epoch = vertices, phi, epoch
                eta = 1.0 / (sigma * (epoch + 1)) if schedule == "theory" else float(config["step_size"])
                if schedule == "sqrt_decay":
                    eta /= math.sqrt(epoch + 1)
                if not math.isfinite(eta) or eta <= 0:
                    raise ValueError("Invalid explicit TL* step size")
                heights, seen, diag = algorithm_one(graph, heights, seed, mass, sigma, eta, k, gamma)
                touched.update(seen)
                diagnostics.append({"iteration": epoch + 1, "eta": eta, "objective_before_update": objective, **diag})
            if return_policy != "best_sweep":
                selected = best_heights if return_policy == "best_dual" else heights
                if return_policy == "last":
                    selected_epoch = len(diagnostics)
                trial_vertices, trial_phi = sweep(graph, selected, seed, config.get("require_seed", False), config.get("keep_ties", False))
            if trial_vertices and trial_phi < best_phi:
                best_vertices, best_phi = trial_vertices, trial_phi
            trials.append({"mass": mass, "k": k, "fraction": None if "k_grid" in config else fractions[ki], "conductance": trial_phi if math.isfinite(trial_phi) else None, "stop": reason, "updates": len(diagnostics), "selected_iteration": selected_epoch, "best_dual_objective": best_objective, "trace": diagnostics})
            if reason == "time_budget":
                break
        if time.perf_counter() >= deadline:
            break
    return {"vertices": sorted(best_vertices), "runtime_seconds": time.perf_counter() - started, "touched_vertices": sorted(touched), "metadata": {"method": "TL*-Algorithm1", "backend": "literal", "sources": {"paper": SOURCE, "version": "2606.09340v1", "implementation_identity": "independent Algorithm-1 port; author execution code unavailable"}, "objective": "HFD quadratic dual", "oracle": oracle_volume is not None, "mass_policy": mass_policy, "sigma": sigma, "gamma": gamma, "iterations_requested": iterations, "step_schedule": schedule, "step_size": config.get("step_size"), "step_schedule_provenance": "theoretical theorem schedule" if schedule == "theory" else "explicit implementation choice; paper experimental step not disclosed", "return_policy": return_policy, "return_policy_provenance": "theoretical best-dual iterate" if return_policy == "best_dual" else "explicit implementation choice; experimental return iterate not disclosed", "topk_ties": "ascending node ID", "rounding": "nearest integer; exact halves upward", "require_seed_in_sweep": bool(config.get("require_seed", False)), "keep_ties": bool(config.get("keep_ties", False)), "update_count": sum(t["updates"] for t in trials), "stop": "query_budget" if time.perf_counter() >= deadline else "configuration_grid_finished", "selection": "minimum output conductance over mass and activation grids; first tied configuration", "touched_definition": "union of active region and one-hop boundary read by exact local graph update", "trials": trials}}
