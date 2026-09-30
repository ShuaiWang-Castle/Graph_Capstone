#!/usr/bin/env python3
"""Supplemental existing EgoSplit configurations, never a new candidate.

Run the pinned, explicitly bug-fixed upstream class with its PC/Leiden/min5
defaults or a CC/Louvain/min5 filtering control. No labels or case rule.
"""
from pathlib import Path
import argparse, importlib.util, random, sys, time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.io import graph, read_json, write_json, sha256


def main():
    start = time.perf_counter()
    p = argparse.ArgumentParser()
    for name in ['graph', 'output', 'config']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--seed', type=int, required=True)
    a = p.parse_args()
    cfg = read_json(a.config)
    allowed = {'module_path', 'local_clustering', 'global_clustering', 'min_cluster_size', 'resolution', 'threads'}
    if set(cfg) - allowed:
        raise ValueError('Unknown existing-control config fields')
    import numpy as np
    import scipy.sparse as sp
    import sknetwork as sn
    random.seed(a.seed)
    np.random.seed(a.seed)
    n, edges = graph(a.graph)
    e = np.asarray(edges, dtype=np.int32).reshape((-1, 2))
    row = np.r_[e[:, 0], e[:, 1]]
    col = np.r_[e[:, 1], e[:, 0]]
    adj = sp.csr_matrix((np.ones(len(row), dtype=np.float64), (row, col)), shape=(n, n))
    adj.sort_indices()
    source = Path(cfg['module_path']).resolve()
    spec = importlib.util.spec_from_file_location('lab_existing_skego_control', source)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    global_name = cfg['global_clustering']
    if global_name == 'Louvain':
        global_object = sn.clustering.Louvain(resolution=cfg.get('resolution', 1.), random_state=a.seed)
    elif global_name == 'Leiden':
        global_object = 'Leiden'
    else:
        raise ValueError('Only the two explicitly registered existing controls are supported')
    splitter = mod.EgoSplit(local_clustering=cfg['local_clustering'], global_clustering=global_object,
                           min_cluster_size=cfg['min_cluster_size'], random_state=a.seed)
    setup_seconds = time.perf_counter() - start
    phase = time.perf_counter()
    ans = splitter.fit_predict(adj).tocsr()
    fit_seconds = time.perf_counter() - phase
    phase = time.perf_counter()
    communities = [sorted(set(map(int, ans.indices[ans.indptr[c]:ans.indptr[c + 1]]))) for c in range(ans.shape[0])]
    write_json(a.output, {'communities': communities, 'method': 'EXISTING_EgoSplit_CONFIGURATION_CONTROL',
                         'seed': a.seed, 'metadata': {
                             'implementation': 'Pinned egosplit-sknetwork with documented weight/order/isolate bugfixes',
                             'is_new_candidate': False, 'source_sha256': sha256(source),
                             'local_clustering': cfg['local_clustering'], 'global_clustering': global_name,
                             'min_cluster_size': cfg['min_cluster_size'],
                             'source_default_identity': cfg['local_clustering'] == 'PC' and global_name == 'Leiden' and cfg['min_cluster_size'] == 5,
                             'persona_nodes': splitter.persona_graph_.shape[0],
                             'persona_edges': splitter.persona_graph_.nnz // 2,
                             'persona_counts': np.diff(splitter.first_personae_index_).astype(int).tolist(),
                             'persona_clusters_before_original_min_size_filter': int(len(np.unique(splitter.persona_clusters_))),
                             'cold_numba_compilation_included': True},
                         'stage_seconds': {'setup_seconds': setup_seconds, 'fit_seconds': fit_seconds,
                                           'decode_seconds': time.perf_counter() - phase,
                                           'elapsed': time.perf_counter() - start}})


if __name__ == '__main__':
    main()
