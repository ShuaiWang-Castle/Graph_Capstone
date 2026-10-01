"""Same hypergraph Algorithm1 primitives compiled for one CPU thread.

The supplied concave Lovasz profile is retained. No graph projection, approximate
gradient, frontier pruning or alternative activation rule is used. Global input
packing/dense scratch/JIT loading are included in run_tlhfd's wrapper wall time.
"""
import math
import time
import numpy as np
import numba
from numba import njit
from ._common import mass_grid, validate_query
from .hypergraph import conductance, sweep, _emit
from .tlhfd import SOURCE


def _pack(h):
    edge_ptr = np.zeros(len(h.edges) + 1, np.int64)
    for eid, (vertices, theta, w) in enumerate(h.edges):
        slopes = [w[i + 1] - w[i] for i in range(len(vertices))]
        if any(slopes[i] < slopes[i + 1] for i in range(len(slopes) - 1)):
            raise ValueError('Nonconcave splitting is outside submodular Algorithm1 domain')
        edge_ptr[eid + 1] = edge_ptr[eid] + len(vertices)
    size = int(edge_ptr[-1])
    vertices_array = np.empty(size, np.int64)
    slopes_array = np.empty(size, np.float64)
    profile = np.empty(size + len(h.edges), np.float64)
    profile_ptr = np.empty(len(h.edges) + 1, np.int64)
    theta_array = np.empty(len(h.edges), np.float64)
    unit = np.empty(len(h.edges), np.bool_)
    for eid, (vertices, theta, w) in enumerate(h.edges):
        start, end = int(edge_ptr[eid]), int(edge_ptr[eid + 1])
        if tuple(vertices) != tuple(sorted(set(vertices))):
            raise ValueError('Require distinct ascending node IDs in every input hyperedge')
        vertices_array[start:end] = vertices
        slopes_array[start:end] = [float(w[i + 1] - w[i]) for i in range(len(vertices))]
        profile_ptr[eid] = start + eid
        profile[start + eid:end + eid + 1] = list(map(float, w))
        theta_array[eid] = float(theta)
        unit[eid] = all(value == 1 for value in w[1:-1])
    profile_ptr[-1] = len(profile)
    incidence_ptr = np.zeros(h.n + 1, np.int64)
    for v in range(h.n):
        incidence_ptr[v + 1] = incidence_ptr[v] + len(h.incidence[v])
    incidence_ids = np.empty(int(incidence_ptr[-1]), np.int64)
    for v in range(h.n):
        incidence_ids[incidence_ptr[v]:incidence_ptr[v + 1]] = h.incidence[v]
    return (edge_ptr, vertices_array, slopes_array, profile_ptr, profile,
            theta_array, unit, incidence_ptr, incidence_ids)


@njit(cache=True, fastmath=False)
def _advance(edge_ptr, vertices, slopes, profile_ptr, profile, theta, unit,
             incidence_ptr, incidence_ids, degree, seed, mass, sigma, gamma,
             eta, k, x, active_ids, active_mask, grad, inward, boundary_ids,
             boundary_mask, incident_ids, incident_mask, touched, best_x,
             best_ids, active_count, best_count, best_objective,
             selected_epoch, trace, start_epoch, end_epoch):
    for epoch in range(start_epoch, end_epoch):
        active_ids[:active_count].sort()
        boundary_count = incident_count = 0
        regularizer = linear = quadratic = 0.0
        for i in range(active_count):
            v = active_ids[i]
            touched[v] = True
            grad[v] = degree[v] * (1 + sigma * x[v]) - (mass if v == seed else 0.0)
            regularizer += degree[v] * x[v] * x[v]
            linear += degree[v] * x[v]
            for j in range(incidence_ptr[v], incidence_ptr[v + 1]):
                eid = incidence_ids[j]
                if not incident_mask[eid]:
                    incident_mask[eid] = True
                    incident_ids[incident_count] = eid
                    incident_count += 1
        incident_ids[:incident_count].sort()
        for ei in range(incident_count):
            eid = incident_ids[ei]
            start, end = edge_ptr[eid], edge_ptr[eid + 1]
            overlap = 0
            for j in range(start, end):
                v = vertices[j]
                if active_mask[v]:
                    overlap += 1
                elif not boundary_mask[v]:
                    boundary_ids[boundary_count] = v
                    boundary_count += 1
                    boundary_mask[v] = True
                    touched[v] = True
                    grad[v] = degree[v]
                    inward[v] = 0.0
            if unit[eid]:
                # Exactly the unit greedy Lovasz vector: +1 at first maximum
                # and -1 at last minimum in descending height/ascending ID order.
                vmax = vmin = vertices[start]
                for j in range(start + 1, end):
                    v = vertices[j]
                    if x[v] > x[vmax]:
                        vmax = v
                    if x[v] <= x[vmin]:
                        vmin = v
                fe = x[vmax] - x[vmin]
                gradient = theta[eid] * fe
                grad[vmax] += gradient
                grad[vmin] += -gradient
            else:
                old = np.empty(end - start, np.float64)
                for j in range(start, end):
                    old[j - start] = x[vertices[j]]
                order = np.argsort(-old, kind='mergesort')
                fe = 0.0
                for i in range(end - start):
                    fe += slopes[start + i] * old[order[i]]
                for i in range(end - start):
                    v = vertices[start + order[i]]
                    grad[v] += theta[eid] * fe * slopes[start + i]
            quadratic += theta[eid] * fe * fe
            commitment = theta[eid] * (1.0 if unit[eid] else profile[profile_ptr[eid] + overlap])
            for j in range(start, end):
                v = vertices[j]
                if not active_mask[v]:
                    inward[v] += commitment
        objective = .5 * quadratic + .5 * sigma * regularizer + (linear - mass * x[seed])
        if not math.isfinite(objective):
            return active_count, best_count, best_objective, selected_epoch, epoch, False
        if objective < best_objective:
            for i in range(best_count):
                best_x[best_ids[i]] = 0.0
            best_count = 0
            for i in range(active_count):
                v = active_ids[i]
                if x[v] > 0:
                    best_x[v] = x[v]
                    best_ids[best_count] = v
                    best_count += 1
            best_objective, selected_epoch = objective, epoch
        boundary_ids[:boundary_count].sort()
        pushes = np.empty(boundary_count, np.float64)
        scores = np.empty(boundary_count, np.float64)
        for i in range(boundary_count):
            v = boundary_ids[i]
            pushes[i] = max(0.0, -grad[v] / degree[v])
            scores[i] = pushes[i] * (inward[v] / degree[v]) ** gamma
        order = np.argsort(-scores, kind='mergesort')
        picked = min(k, boundary_count)
        chosen = np.zeros(boundary_count, np.bool_)
        for i in range(picked):
            chosen[order[i]] = True
        skipped = 0.0
        for i in range(boundary_count):
            if not chosen[i]:
                skipped += degree[boundary_ids[i]] * pushes[i]
        old_active_count = active_count
        for i in range(old_active_count):
            active_mask[active_ids[i]] = False
        active_count = 0
        for i in range(old_active_count):
            v = active_ids[i]
            value = max(0.0, x[v] - eta * grad[v] / degree[v]) if degree[v] > 0 else 0.0
            if not math.isfinite(value):
                return active_count, best_count, best_objective, selected_epoch, epoch, False
            x[v] = value
            if value > 0 or v == seed:
                active_ids[active_count] = v
                active_count += 1
                active_mask[v] = True
        activated = 0
        for i in range(picked):
            bi = order[i]
            v = boundary_ids[bi]
            value = eta * pushes[bi]
            if not math.isfinite(value):
                return active_count, best_count, best_objective, selected_epoch, epoch, False
            if value > 0:
                x[v] = value
                active_ids[active_count] = v
                active_count += 1
                active_mask[v] = True
                activated += 1
        for i in range(boundary_count):
            boundary_mask[boundary_ids[i]] = False
        for i in range(incident_count):
            incident_mask[incident_ids[i]] = False
        trace[epoch, 0] = objective
        trace[epoch, 1] = old_active_count
        trace[epoch, 2] = boundary_count
        trace[epoch, 3] = incident_count
        trace[epoch, 4] = activated
        trace[epoch, 5] = skipped
    return active_count, best_count, best_objective, selected_epoch, end_epoch, True


def solve_trial(h, seed, mass, sigma, gamma, eta, k, iterations,
                deadline=math.inf, initial_heights=None, chunk_steps=16, packed=None):
    """Expose last and best old iterate for numerical parity, without labels."""
    arrays = _pack(h) if packed is None else packed
    n, m = h.n, len(h.edges)
    x = np.zeros(n, np.float64)
    initial = dict(initial_heights or {})
    for v, value in initial.items():
        if not 0 <= int(v) < n or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError('Initial heights require finite positive valid entries')
        x[int(v)] = float(value)
    initial_ids = sorted(set(map(int, initial)) | {seed})
    active_ids = np.empty(n, np.int64)
    active_ids[:len(initial_ids)] = initial_ids
    active_mask = np.zeros(n, np.bool_)
    active_mask[initial_ids] = True
    grad, inward = np.empty(n, np.float64), np.empty(n, np.float64)
    boundary_ids = np.empty(n, np.int64)
    boundary_mask = np.zeros(n, np.bool_)
    incident_ids = np.empty(m, np.int64)
    incident_mask = np.zeros(m, np.bool_)
    touched = np.zeros(n, np.bool_)
    best_x = np.zeros(n, np.float64)
    best_ids = np.empty(n, np.int64)
    trace = np.empty((iterations, 6), np.float64)
    active_count = len(initial_ids)
    best_count = selected_epoch = completed = 0
    best_objective = 0.0
    reason = 'fixed_iterations'
    for start in range(0, iterations, chunk_steps):
        if time.perf_counter() >= deadline:
            reason = 'time_budget'
            break
        active_count, best_count, best_objective, selected_epoch, completed, finite = _advance(
            *arrays, h.degree, seed, mass, sigma, gamma, eta, k,
            x, active_ids, active_mask, grad, inward, boundary_ids, boundary_mask,
            incident_ids, incident_mask, touched, best_x, best_ids, active_count,
            best_count, best_objective, selected_epoch, trace, start, min(iterations, start + chunk_steps))
        if not finite:
            raise FloatingPointError('Nonfinite hyper Algorithm1 objective/iterate at iteration ' + str(completed))
    return {'last_heights': {int(v): float(x[v]) for v in active_ids[:active_count] if x[v] > 0},
            'best_heights': {int(v): float(best_x[v]) for v in best_ids[:best_count]},
            'touched': np.flatnonzero(touched).tolist(), 'best_objective': float(best_objective),
            'selected_epoch': int(selected_epoch), 'updates': int(completed),
            'stop': reason, 'trace': trace[:completed]}


def run_tlhfd(h, seed, config, oracle_volume=None, progress=None):
    started = time.perf_counter()
    degree = validate_query(h, seed)
    if degree == 0:
        return {'vertices': [seed], 'runtime_seconds': time.perf_counter() - started,
                'touched_vertices': [seed], 'metadata': {'method': 'TL*-hyper-Algorithm1',
                'backend': 'numba', 'stop': 'isolated_seed'}}
    if config.get('step_schedule') != 'constant' or config.get('return_policy', 'best_dual') != 'best_dual':
        raise ValueError('Hyper NumBa requires explicit constant step and best_dual; no silent paper default')
    eta, sigma, gamma = float(config['step_size']), float(config.get('sigma', 1e-4)), float(config.get('gamma', 1.))
    iterations = int(config.get('iterations', 1000))
    chunk_steps = int(config.get('numba_chunk_steps', 16))
    if eta <= 0 or sigma <= 0 or gamma < 0 or iterations < 1 or chunk_steps < 1 or not all(math.isfinite(x) for x in (eta, sigma, gamma)):
        raise ValueError('Invalid explicit TL* hyper parameters')
    deadline = started + float(config.get('budget_seconds', 600))
    packing_start = time.perf_counter()
    arrays = _pack(h)
    packing_seconds = time.perf_counter() - packing_start
    unit = bool(arrays[6].all())
    scale = config.get('activation_scale', 'volume' if unit else 'vertex_count')
    if scale not in ('volume', 'vertex_count'):
        raise ValueError('Unknown explicit top-k scale')
    masses, policy = mass_grid(h, seed, config, oracle_volume)
    fractions = [float(f) for f in config.get('fraction_grid', [.01, .02, .03, .05] if unit else [.01, .02, .03, .05, .07, .10])]
    if any(not math.isfinite(f) or f < 0 for f in fractions):
        raise ValueError('Invalid activation fractions')
    trials, touched, support_union = [], {seed}, set()
    best_vertices, best_phi, timed_out = [seed], conductance(h, [seed]), False
    _emit(progress, {'stage': 'algorithm_started', 'method': 'TL*-hyper-Algorithm1',
        'backend': 'numba', 'mass_grid': masses, 'vertices': best_vertices,
        'completed_trial_count': 0, 'mass_grid_complete': False,
        'global_input_packing': {'vertices': h.n, 'hyperedges': len(h.edges),
            'incidences': len(arrays[1]), 'seconds': packing_seconds}})
    for mass in masses:
        estimate = mass / float(config.get('injection_factor', 3.))
        if scale == 'vertex_count':
            estimate /= h.total / h.n
        ks = [int(k) for k in config['k_grid']] if 'k_grid' in config else [max(1, int(math.floor(f * estimate + .5))) for f in fractions]
        for fi, k in enumerate(ks):
            if k < 0:
                raise ValueError('Negative top-k')
            trial = solve_trial(h, seed, mass, sigma, gamma, eta, k, iterations, deadline, chunk_steps=chunk_steps, packed=arrays)
            best_heights = trial['best_heights']
            support_union.update(best_heights)
            touched.update(trial['touched'])
            vertices, phi = sweep(h, best_heights, seed, config.get('require_seed', True), config.get('keep_ties', False))
            if vertices and phi < best_phi:
                best_vertices, best_phi = vertices, phi
            trace = [{'iteration': i + 1, 'eta': eta, 'objective_before_update': float(row[0]),
                      'active_nodes': int(row[1]), 'boundary_nodes': int(row[2]),
                      'incident_hyperedges': int(row[3]), 'activated_positive_nodes': int(row[4]),
                      'skipped_push_degree_sum': float(row[5])} for i, row in enumerate(trial['trace'])]
            trials.append({'mass': mass, 'k': k, 'fraction': None if 'k_grid' in config else fractions[fi],
                'conductance': phi if math.isfinite(phi) else None, 'selected_iteration': trial['selected_epoch'],
                'selected_support': sorted(best_heights), 'best_dual_objective': trial['best_objective'],
                'updates': trial['updates'], 'stop': trial['stop'], 'trace': trace})
            _emit(progress, {'stage': 'trial_finished', 'method': 'TL*-hyper-Algorithm1',
                'backend': 'numba', 'trial_index': len(trials)-1, 'trial': trials[-1],
                'vertices': best_vertices, 'diffusion_support_union': sorted(support_union),
                'touched_vertices': sorted(touched), 'mass_grid': masses,
                'completed_trial_count': len(trials), 'mass_grid_complete': False,
                'status': 'PARTIAL_GRID_CHECKPOINT'})
            if trial['stop'] == 'time_budget' or time.perf_counter() >= deadline:
                timed_out = True
                break
        if timed_out:
            break
    _emit(progress, {'stage': 'grid_finished', 'method': 'TL*-hyper-Algorithm1',
        'backend': 'numba', 'vertices': best_vertices,
        'diffusion_support_union': sorted(support_union), 'touched_vertices': sorted(touched),
        'mass_grid': masses, 'completed_trial_count': len(trials),
        'mass_grid_complete': not timed_out, 'status': 'PARTIAL_TIMEOUT' if timed_out else 'COMPLETED'})
    return {'vertices': sorted(best_vertices), 'runtime_seconds': time.perf_counter() - started,
        'touched_vertices': sorted(touched), 'metadata': {
            'method': 'TL*-hyper-Algorithm1', 'backend': 'numba', 'backend_version': numba.__version__,
            'fastmath': False, 'parallel': False,
            'sources': {'paper': SOURCE, 'version': '2606.09340v1', 'identity': 'independent actual Lovasz+Algorithm1 port'},
            'objective': 'HFD quadratic dual with the supplied splitting function',
            'sigma': sigma, 'gamma': gamma, 'step_schedule': 'constant', 'step_size': eta,
            'step_size_provenance': 'explicit engineering input, paper experiment actual step size undisclosed',
            'return_policy': 'best_dual among old iterates 0..T-1', 'splitting': h.splitting,
            'unit_profile': unit, 'activation_scale': scale,
            'subgradient_ties': 'greedy Lovasz extreme point: descending old height, ascending node ID',
            'topk_ties': 'ascending node ID', 'rounding': 'nearest integer; exact halves upward',
            'require_seed_in_sweep': bool(config.get('require_seed', True)),
            'keep_ties': bool(config.get('keep_ties', False)), 'oracle': oracle_volume is not None,
            'mass_policy': policy, 'mass_grid': masses, 'mass_grid_complete': not timed_out,
            'selection': 'per-query lowest output conductance across fixed mass/f grid, first tied configuration; differs from paper per-cluster median selection',
            'stop': 'TIMEOUT' if timed_out else 'configuration_grid_finished',
            'status': 'PARTIAL_TIMEOUT' if timed_out else 'COMPLETED',
            'update_count': sum(t['updates'] for t in trials), 'diffusion_support_union': sorted(support_union),
            'touched_definition': 'union of active vertices and all vertices in their scanned incident hyperedges',
            'global_input_packing': {'vertices': h.n, 'hyperedges': len(h.edges), 'incidences': len(arrays[1]), 'seconds': packing_seconds},
            'dense_storage': 'O(n+m+incidences) packed input, masks and scratch; allocation and JIT/cache loading included in wrapper runtime',
            'clock_check': 'between chunks of ' + str(chunk_steps) + ' simultaneous Algorithm1 updates; outer task wall cap also applies',
            'trials': trials}}
