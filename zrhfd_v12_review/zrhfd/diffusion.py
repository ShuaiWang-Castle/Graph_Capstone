"""Bounded local coordinate queue for the frozen graph quadratic objective."""
import time
import numpy as np
from numba import njit
from scipy import sparse
from scipy.sparse.linalg import spsolve, cg


def _active_linear_finish(graph, raw, support, seed, mass, sigma, tolerance):
    """Same quadratic objective; sparse active-set finish after queue truncation.

    This backend is a solver choice, not a different mass/region/clustering rule.
    Check both active stationarity and nonnegative inactive gradients.
    """
    active=set(map(int,support));active.add(seed);trace=[]
    adjacency=graph.adjacency()
    for iteration in range(64):
        U=np.asarray(sorted(active),dtype=np.int64)
        local=adjacency[U][:,U]
        system=sparse.diags((1+sigma)*graph.degree[U])-local
        rhs=-graph.degree[U].copy();rhs[np.flatnonzero(U==seed)[0]]+=mass
        if len(U)<=50_000:
            values=spsolve(system.tocsc(),rhs);linear_status='sparse_direct'
        else:
            preconditioner=sparse.diags(1/((1+sigma)*graph.degree[U]))
            values,info=cg(system,rhs,x0=raw[U],M=preconditioner,rtol=1e-13,atol=1e-12,maxiter=10_000)
            if info:raise RuntimeError('Active-set CG did not converge: '+str(info))
            linear_status='preconditioned_cg'
        negative=float(np.min(values,initial=0))
        if negative < -1e-8*max(1.,float(np.max(values,initial=0))):
            raise RuntimeError('Quadratic active-set finish found negative active optimum')
        raw[U]=np.maximum(values,0)
        candidates=set()
        for u in U:
            candidates.update(map(int,graph.indices[graph.indptr[u]:graph.indptr[u+1]]))
        frontier=np.asarray(sorted(candidates-active),dtype=np.int64)
        additions=[];worst=0.
        for v in frontier:
            lo,hi=graph.indptr[v:v+2]
            gradient=float(graph.degree[v]-np.dot(graph.weights[lo:hi],raw[graph.indices[lo:hi]]))
            worst=min(worst,gradient/max(1.,graph.degree[v]))
            if gradient < -max(1e-11,tolerance*10)*graph.degree[v]:additions.append(int(v))
        residual=float(np.max(np.abs(system@raw[U]-rhs)/graph.degree[U],initial=0))
        trace.append({'iteration':iteration,'active_vertices':len(U),'new_active_vertices':len(additions),
                      'linear_solver':linear_status,'minimum_solution':negative,
                      'scaled_linear_residual':residual,'scaled_inactive_gradient_min':worst})
        if not additions:
            if residual>1e-8:raise RuntimeError('Active-set linear stationarity residual too large')
            return raw,np.asarray([u for u in U if raw[u]>0],dtype=np.int64),trace
        active.update(additions)
    raise RuntimeError('Quadratic active-set finish exceeded 64 expansions')


class Scores(np.ndarray):
    """Dense-addressable scores with an explicitly tracked local support."""


@njit(cache=True)
def _coordinate_queue(indptr, indices, weights, d, seed, mass, sigma, tolerance, max_updates):
    n = len(d)
    x = np.zeros(n, dtype=np.float64)
    # At most n vertices are present at once. The update budget does not
    # determine the allocated queue size.
    queue = np.empty(n+1, dtype=np.int64)
    pending = np.zeros(n, dtype=np.bool_)
    head, tail, count = 0, 1, 1
    queue[0] = seed; pending[seed] = True
    active=np.empty(n,dtype=np.int64);active_count=0
    updates, edge_visits, max_queue = 0, 0, 1
    while count and updates < max_updates:
        u = queue[head]; head = (head+1) % (n+1); count -= 1; pending[u] = False
        neighbor_sum = 0.0
        for j in range(indptr[u], indptr[u+1]):
            neighbor_sum += weights[j] * x[indices[j]]
        edge_visits += indptr[u+1]-indptr[u]
        injection = mass if u == seed else 0.0
        new = max(0.0, (neighbor_sum+injection-d[u])/((1.0+sigma)*d[u]))
        updates += 1
        if abs(new-x[u]) > tolerance:
            if x[u]==0 and new>0:active[active_count]=u;active_count+=1
            x[u] = new
            for j in range(indptr[u], indptr[u+1]):
                v = indices[j]
                if not pending[v]:
                    queue[tail] = v; tail = (tail+1) % (n+1)
                    count += 1; pending[v] = True
            if count > max_queue: max_queue = count
    return x, active[:active_count], updates, edge_visits, count, max_queue


@njit(cache=True)
def _local_telemetry(indptr,indices,weights,d,x,U,seed,mass,sigma):
    # Only support vertices and their neighbors can have nonzero adjacency*x.
    n=len(d);seen=np.zeros(n,dtype=np.bool_);frontier=np.empty(n,dtype=np.int64);count=0
    for u in U:
        if not seen[u]:seen[u]=True;frontier[count]=u;count+=1
        for j in range(indptr[u],indptr[u+1]):
            v=indices[j]
            if not seen[v]:seen[v]=True;frontier[count]=v;count+=1
    kkt=0.0;support_volume=0.0;boundary_flux=0.0;leakage=0.0;max_x=0.0
    for u in frontier[:count]:
        ax=0.0
        for j in range(indptr[u],indptr[u+1]):ax+=weights[j]*x[indices[j]]
        grad=(1+sigma)*d[u]*x[u]-ax+d[u]-(mass if u==seed else 0.0)
        error=abs(grad)/d[u] if x[u]>0 else max(-grad,0.0)/max(d[u],1.0)
        kkt=max(kkt,error)
    for u in U:
        support_volume+=d[u];leakage+=sigma*d[u]*x[u];max_x=max(max_x,x[u])
        for j in range(indptr[u],indptr[u+1]):
            if x[indices[j]]==0:boundary_flux+=weights[j]*x[u]
    return kkt,support_volume,boundary_flux,leakage,max_x,count


def solve_graph(graph, seed, mass, sigma=1e-4, tolerance=1e-12, max_updates=20_000_000):
    if not (0 <= seed < graph.n) or graph.degree[seed] <= 0:
        raise ValueError('A positive-degree seed is required for the frozen objective')
    started = time.perf_counter()
    raw, U, updates, visits, pending, max_queue = _coordinate_queue(
        graph.indptr, graph.indices, graph.weights, graph.degree,
        int(seed), float(mass), float(sigma), float(tolerance), int(max_updates))
    initial_pending=int(pending);finish_trace=[]
    if pending:
        raw,U,finish_trace=_active_linear_finish(graph,raw,U,seed,float(mass),float(sigma),float(tolerance))
        pending=0
    x=raw.view(Scores);x.support=U
    kkt,support_volume,boundary_flux,leakage,max_x,frontier_size=_local_telemetry(
        graph.indptr,graph.indices,graph.weights,graph.degree,x,U,seed,float(mass),float(sigma))
    mass_residual = float(mass)-support_volume-boundary_flux-leakage
    telemetry = {'mass':float(mass),'updates':int(updates),'edge_visits':int(visits),
                 'queue_pending':int(pending),'max_queue':int(max_queue),
                 'termination':'queue_empty' if pending == 0 else 'update_budget',
                 'runtime_seconds':time.perf_counter()-started,
                 'support_size':len(U),'support_volume':support_volume,
                 'scaled_kkt_residual':kkt,'mass_balance_residual':mass_residual,
                 'seed_is_max':bool(x[seed] >= max_x-10*tolerance),
                 'residual_frontier_vertices':int(frontier_size),
                 'support_components':len(graph.components(U)),
                 'support_contains_seed':bool(seed in U),
                 'volume_bound_residual':support_volume-float(mass),
                 'solver_backend':'coordinate_queue_then_sparse_active_set' if finish_trace else 'coordinate_queue',
                 'coordinate_queue_pending_before_finish':initial_pending,
                 'active_set_finish_trace':finish_trace,
                 'precision_mode':'float64_approximate_telemetry_not_exact_theory'}
    return x, telemetry


def activation_mass(graph, seed, sigma=1e-4):
    lo, hi = graph.indptr[seed:seed+2]
    return float(graph.degree[seed] + (1+sigma)*graph.degree[seed]*
                 np.min(graph.degree[graph.indices[lo:hi]]/graph.weights[lo:hi]))
