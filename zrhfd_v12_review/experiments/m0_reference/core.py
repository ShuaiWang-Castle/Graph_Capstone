"""Isolated compatibility shim for the absent historical code/core.py.

flow_cd reconstructs the graph quadratic diffusion from the user-supplied
inputs/local_hfd/kernels.py flow_diffusion. The circular queue has n+1 slots
instead of max_updates+1; coordinate ordering and update threshold are identical.
This is not the unavailable author's core.py and is not the production solver.
"""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def _flow_bounded(indptr, indices, deg, seed, mass, sigma, tol, max_updates):
    n = deg.shape[0]
    x = np.zeros(n)
    q = np.empty(n + 1, np.int64)
    inq = np.zeros(n, np.bool_)
    head = 0
    tail = 1
    q[0] = seed
    inq[seed] = True
    updates = 0
    changes = 0
    max_queue = 1
    while head < tail and updates < max_updates:
        u = q[head % (n + 1)]
        head += 1
        inq[u] = False
        updates += 1
        neighbor_sum = 0.0
        for p in range(indptr[u], indptr[u + 1]):
            neighbor_sum += x[indices[p]]
        injected = mass if u == seed else 0.0
        new = (neighbor_sum + injected - deg[u]) / ((1.0 + sigma) * deg[u])
        if new < 0.0:
            new = 0.0
        if abs(new - x[u]) > tol:
            x[u] = new
            changes += 1
            for p in range(indptr[u], indptr[u + 1]):
                v = indices[p]
                if not inq[v] and tail - head < max_updates:
                    q[tail % (n + 1)] = v
                    tail += 1
                    inq[v] = True
            if tail - head > max_queue:
                max_queue = tail - head
    return x, updates, changes, head == tail, max_queue


def flow_cd(indptr, indices, deg, seed, mass, sigma=1e-4, tol=1e-12, max_updates=400_000_000):
    return _flow_bounded(indptr, indices, deg, seed, float(mass), float(sigma), float(tol), int(max_updates))
