#!/usr/bin/env python3
"""Thin wrappers around upstream implementations; no new clustering algorithm.
Only `components_smoke` is bundled without external dependencies/source checkout.
Native wrappers require install/API smoke checks on the execution host.
"""
from __future__ import annotations
import argparse,importlib.util,json,random,sys,time,subprocess,os,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lab.io import graph,read_json,write_json,sha256

def nxgraph(n,edges):
    import networkx as nx
    g=nx.Graph();g.add_nodes_from(range(n));g.add_edges_from(edges);return g

def load_source(name,path):
    spec=importlib.util.spec_from_file_location(name,Path(path).resolve())
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def main():
    p=argparse.ArgumentParser();p.add_argument('--method',required=True);p.add_argument('--graph',required=True)
    p.add_argument('--output',required=True);p.add_argument('--seed',type=int,required=True);p.add_argument('--config',required=True);a=p.parse_args()
    t0=time.perf_counter();cfg=read_json(a.config);random.seed(a.seed)
    import numpy as np
    np.random.seed(a.seed);n,edges=graph(a.graph);stage={'load_seconds':time.perf_counter()-t0};meta={}
    start=time.perf_counter()
    if a.method=='components_smoke':
        import networkx as nx
        communities=[sorted(c) for c in nx.connected_components(nxgraph(n,edges))]
        meta['scope']='HARNESS_SMOKE_ONLY_NOT_A_COMPETITIVE_BASELINE'
    elif a.method=='slpa':
        source=Path(cfg['module_path']).resolve()
        mod=load_source('lab_upstream_slpa',source)
        communities=mod.slpa_nx(nxgraph(n,edges),T=int(cfg.get('t',21)),r=float(cfg.get('r',.1)))
        meta.update(implementation='Pinned CDlib SLPA_nx via exact wrapper call; narrow dependency loading',source_sha256=sha256(source))
    elif a.method=='highway':
        source=Path(cfg['module_path']).resolve()
        if not source.exists():raise FileNotFoundError('Fetch the pinned CDlib Highway.py first: '+str(source))
        if cfg.get('module_sha256') and sha256(source)!=cfg['module_sha256']:raise ValueError('Highway source hash mismatch')
        name='lab_upstream_highway';spec=importlib.util.spec_from_file_location(name,source)
        mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
        # Timing instrumentation wraps the unmodified helper and returns its result unchanged.
        if hasattr(mod,'_select_anchors_greedy_dedup'):
            original=mod._select_anchors_greedy_dedup
            def logged(*args,**kwargs):
                t=time.perf_counter();result=original(*args,**kwargs)
                meta['anchor_count']=len(result);meta['anchor_ids']=list(map(int,result))
                stage['anchor_seconds']=time.perf_counter()-t;return result
            mod._select_anchors_greedy_dedup=logged
        communities=mod.highway_nx(nxgraph(n,edges),**cfg.get('parameters',{}))
        meta.update(implementation='Pinned CDlib pure-Python Highway; NOT the native C++ performance baseline',source_sha256=sha256(source))
    elif a.method=='ego_karateclub':
        src=Path(cfg['source_dir']).resolve()
        # Load the actual upstream modules without unrelated embedding dependencies.
        package=types.ModuleType('karateclub');package.__path__=[str(src/'karateclub')];sys.modules['karateclub']=package
        load_source('karateclub.estimator',src/'karateclub/estimator.py')
        module=load_source('lab_upstream_ego',src/'karateclub/community_detection/overlapping/ego_splitter.py')
        EgoNetSplitter=module.EgoNetSplitter
        splitter=EgoNetSplitter(resolution=float(cfg.get('resolution',1.0)),seed=a.seed)
        if cfg.get('loopless_fix',False):
            def check_graph(self,g):
                self._check_indexing(g);return g
            splitter._check_graph=types.MethodType(check_graph,splitter)
        for name in ['_check_graph','_create_egonets','_map_personalities','_create_persona_graph','_create_partitions']:
            original=getattr(splitter,name)
            def timed(*args,_name=name,_original=original,**kwargs):
                t=time.perf_counter();result=_original(*args,**kwargs);stage[_name+'_seconds']=time.perf_counter()-t;return result
            setattr(splitter,name,timed)
        splitter.fit(nxgraph(n,edges));members=splitter.get_memberships();d={}
        for v,groups in members.items():
            for c in groups:d.setdefault(int(c),[]).append(int(v))
        communities=[d[c] for c in sorted(d)]
        meta.update(implementation='Karate Club third-party EgoNetSplitter; not author distributed backend',
                    loopless_fix=bool(cfg.get('loopless_fix',False)),internal_self_loops=list(map(int,__import__('networkx').nodes_with_selfloops(splitter.graph))),
                    persona_nodes=splitter.persona_graph.number_of_nodes(),persona_edges=splitter.persona_graph.number_of_edges(),
                    persona_counts=[len(splitter.personalities[i]) for i in range(n)],
                    source_sha256=sha256(src/'karateclub/community_detection/overlapping/ego_splitter.py'))
        if cfg.get('detailed_trace',False):
            write_json(Path(a.output).parent/'ego_stage_trace.json',{'components':splitter.components,'personalities':splitter.personalities,'partitions':splitter.partitions})
    elif a.method=='ego_sknetwork':
        import scipy.sparse as sp
        import sknetwork as sn
        source=Path(cfg['module_path']).resolve();module=load_source('lab_upstream_skego',source)
        e=np.asarray(edges,dtype=np.int32).reshape((-1,2))
        rows=np.r_[e[:,0],e[:,1]];cols=np.r_[e[:,1],e[:,0]]
        adj=sp.csr_matrix((np.ones(len(rows),dtype=np.float64),(rows,cols)),shape=(n,n))
        adj.sort_indices()
        splitter=module.EgoSplit(local_clustering='CC',global_clustering=sn.clustering.Louvain(resolution=float(cfg.get('resolution',1.)),random_state=a.seed),min_cluster_size=0,random_state=a.seed)
        ans=splitter.fit_predict(adj).tocsr()
        communities=[ans.indices[ans.indptr[c]:ans.indptr[c+1]].astype(int).tolist() for c in range(ans.shape[0])]
        meta.update(implementation='egosplit-sknetwork third-party CC/Louvain; cold-process numba compilation included',source_sha256=sha256(source),
                    explicit_bugfix=bool(cfg.get('bugfix',False)),persona_nodes=splitter.persona_graph_.shape[0],persona_edges=splitter.persona_graph_.nnz//2,
                    persona_counts=np.diff(splitter.first_personae_index_).astype(int).tolist())
    elif a.method=='highway_native':
        binary=Path(cfg['binary']).resolve();outdir=Path(a.output).resolve().parent
        edgefile=outdir/'native_edges.tsv'
        # Upstream registers IDs before discarding self-loop lines. These lines
        # register the full node universe and its stable order, not graph edges.
        edgefile.write_text(''.join(f'{v}\t{v}\n' for v in range(n))+''.join(f'{u}\t{v}\n' for u,v in edges),encoding='utf-8')
        cmd=[str(binary),'--input',str(edgefile)]
        for key,value in cfg['parameters'].items():cmd+=['--'+key,str(value)]
        subprocess.run(cmd,cwd=outdir,check=True)
        native=read_json(outdir/'communities.json')
        wrapper=load_source('lab_highway_author_wrapper',cfg['module_path'])
        communities=wrapper._read_cpp_communities_json(outdir/'communities.json',list(range(n)),min_community_size=1)
        communities=wrapper._remove_exact_duplicate_communities(communities,deduplicate_communities=True)
        meta.update(implementation='Author Highway C++17 native backend, serial OpenMP unavailable',binary_sha256=sha256(binary),native_command=cmd,
                    native_raw_groups=len(native),author_wrapper_default_dedup=True,wrapper_sha256=sha256(cfg['module_path']),
                    node_serialization='v v registration rows are discarded by upstream after ID registration; original loopless topology preserved')
    elif a.method=='bigclam':
        binary=Path(cfg['binary']).resolve()
        if not binary.is_file():raise FileNotFoundError('Compile audited SNAP examples/bigclam first')
        outdir=Path(a.output).resolve().parent;edgefile=outdir/'native_edges.tsv'
        edgefile.write_text(''.join(f'{u}\t{v}\n' for u,v in edges),encoding='utf-8')
        prefix=outdir/'native_'
        # The inspected upstream executable has a fixed internal RNG seed, not a -seed option.
        cmd=[str(binary),'-i:'+str(edgefile),'-o:'+str(prefix),'-c:'+str(cfg.get('k',-1)),
             '-nt:'+str(cfg.get('threads',1)),'-sa:'+str(cfg.get('line_alpha',.05)),'-sb:'+str(cfg.get('line_beta',.3))]
        if int(cfg.get('k',-1))==-1:
            maximum=max(int(cfg.get('min_k',5)),int(np.ceil(n*float(cfg.get('max_k_fraction',.1))))) if 'max_k_fraction' in cfg else int(cfg.get('max_k',100))
            cmd+=['-mc:'+str(cfg.get('min_k',5)),'-xc:'+str(maximum),'-nc:'+str(cfg.get('k_trials',10))]
        subprocess.run(cmd,check=True)  # Entire adapter process tree is bounded by the outer runner.
        outfile=Path(str(prefix)+'cmtyvv.txt')
        if not outfile.exists():raise RuntimeError('Native BigCLAM did not produce cmtyvv.txt')
        communities=[]
        for line in outfile.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            communities.append([int(x) for x in line.split()])
        present=set(v for e in edges for v in e)
        meta.update(implementation='SNAP native BigCLAM',binary_sha256=sha256(binary),
                    requested_seed=a.seed,seed_policy='Upstream TAGMFast(G,10,10); repeated requests are not independent algorithm seeds',
                    omitted_isolates=n-len(present),native_command=cmd)
    else:raise ValueError('Unknown adapter '+a.method)
    stage['fit_or_native_pipeline_seconds']=time.perf_counter()-start
    communities=[sorted(set(map(int,c))) for c in communities]
    # Across-group duplicates and uncovered vertices are intentionally not repaired.
    for c in communities:
        if any(v<0 or v>=n for v in c):raise ValueError('Upstream output has unmapped node IDs')
    stage['adapter_elapsed_seconds']=time.perf_counter()-t0
    write_json(a.output,{'communities':communities,'method':a.method,'seed':a.seed,'metadata':meta,'stage_seconds':stage})
if __name__=='__main__':main()
