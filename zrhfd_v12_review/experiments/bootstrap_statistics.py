"""Paired graph-then-query bootstrap, fixed seeds and explicit denominators."""
import numpy as np

def paired_bootstrap(groups,replicates=10000,seed=20261005):
    arrays=[np.asarray(g,dtype=float) for g in groups]
    if not arrays or any(not len(a) for a in arrays):raise ValueError('Every bootstrap graph needs paired queries')
    rng=np.random.default_rng(seed);G=len(arrays)
    chosen=rng.integers(G,size=(replicates,G));total=np.zeros(replicates);weight=np.zeros(replicates)
    median_samples=[]
    for k in range(G):
        for gi,a in enumerate(arrays):
            rows=np.flatnonzero(chosen[:,k]==gi)
            if not len(rows):continue
            draws=a[rng.integers(len(a),size=(len(rows),len(a)))]
            total[rows]+=draws.sum(axis=1);weight[rows]+=len(a)
    means=total/weight;all_values=np.concatenate(arrays)
    return {'statistic':'query-weighted mean paired F1 difference',
        'point_estimate':float(all_values.mean()),'percentile_95_CI':np.quantile(means,[.025,.975]).tolist(),
        'paired_difference_median_descriptive':float(np.median(all_values)),
        'query_pairs':len(all_values),'independent_graphs':G,'replicates':replicates,'random_seed':seed,
        'resampling':'sample graphs with replacement, then matched query pairs within each selected graph',
        'interpretation':'conditional on frozen generation regimes; 10000 replicates do not increase independent sample size'}

