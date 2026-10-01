"""Seeded level-set sweeps which never split exact score ties."""
from fractions import Fraction
import numpy as np


def level_sweep(graph, scores, seed, objective='Z'):
    positive = scores.support if hasattr(scores,'support') else np.flatnonzero(scores > 0)
    order = positive[np.lexsort((positive, -scores[positive]))]
    mask = np.zeros(graph.n, dtype=bool)
    cut = volume = 0.0
    best = None; chosen = []; blocks = []
    i = 0
    while i < len(order):
        j = i+1
        while j < len(order) and scores[order[j]] == scores[order[i]]: j += 1
        for u in order[i:j]:
            lo, hi = graph.indptr[u:u+2]
            inner = float(graph.weights[lo:hi][mask[graph.indices[lo:hi]]].sum())
            cut += graph.degree[u]-2*inner; volume += graph.degree[u]; mask[u] = True
        if mask[seed] and volume > 0:
            if graph.integer_weights:
                c, v, M = int(round(cut)), int(round(volume)), int(round(graph.total))
                value = Fraction(c*M+v*v,M*v) if objective == 'Z' else (Fraction(c,min(v,M-v)) if min(v,M-v)>0 else None)
            else:
                value = cut/volume+volume/graph.total if objective=='Z' else (cut/min(volume,graph.total-volume) if min(volume,graph.total-volume)>0 else None)
            if value is not None and (best is None or value < best):
                best = value; chosen = order[:j].tolist()
            blocks.append({'end':j,'score':float(scores[order[i]]),'volume':float(volume),'cut':float(cut),'value':float(value) if value is not None else None})
        i = j
    if best is None:
        raise ValueError('No positive-volume seeded level set')
    return sorted(map(int,chosen)), best, blocks


def capped_region(graph, S0, scores, theta):
    # Zero is excluded: R-cap is a prefix of the positive support, preserving
    # the support/locality semantics of R-supp and the supplied reference.
    S0 = set(S0)
    budget = float(theta)*float(graph.degree[list(S0)].sum())
    positive = scores.support if hasattr(scores,'support') else np.flatnonzero(scores > 0)
    order = positive[np.lexsort((positive,-scores[positive]))]
    L = set(); added = 0.0; i = 0
    while i < len(order):
        j = i+1
        while j < len(order) and scores[order[j]] == scores[order[i]]: j += 1
        block = list(map(int,order[i:j]))
        extra = float(graph.degree[[u for u in block if u not in S0]].sum())
        if added+extra > budget: break
        L.update(block); added += extra; i = j
    return sorted(S0|L)
