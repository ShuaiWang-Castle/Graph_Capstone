"""One frozen-seed small synthetic HSBM engineering round; no timing claims."""
from pathlib import Path
import hashlib
import json
import platform
import random
import sys
import time
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.hyper import Hypergraph,run,Config


def main():
    start=time.perf_counter();random_seed=271828;rng=random.Random(random_seed);K,s=4,6;edges=[]
    for block in range(K):
        C=list(range(block*s,(block+1)*s))
        edges.extend(tuple(sorted([C[u],C[(u+1)%s]])) for u in range(s))
        possible=[]
        from itertools import combinations
        possible=list(combinations(C,4));edges.extend(rng.sample(possible,8))
    for _ in range(6):edges.append(tuple(block*s+rng.randrange(s) for block in range(K)))
    queries=[]
    for splitting in ['all_or_nothing','cardinality_min']:
        h=Hypergraph.from_edges(K*s,edges,splitting)
        for block in range(K):
            seed=block*s;truth=set(range(block*s,(block+1)*s))
            try:
                output=run(h,seed,Config(diffusion_backend='cvxpy'));selected=set(output['vertices']);tp=len(truth&selected);precision=tp/len(selected);recall=tp/len(truth);f1=2*precision*recall/(precision+recall) if precision+recall else 0
                queries.append({'splitting':splitting,'seed':seed,'truth':sorted(truth),'precision':precision,'recall':recall,'F1':f1,'truth_Z_exact':str(h.z_exact(truth)),'covered':truth<=set(output['region_vertices']),'output':output,'status':'COMPLETED'})
                print(splitting,seed,'F1',f1,'region',len(output['region_vertices']),flush=True)
            except Exception as error:
                queries.append({'splitting':splitting,'seed':seed,'truth':sorted(truth),'status':'FAILED','exception':repr(error)})
                print(splitting,seed,'FAILED',repr(error),flush=True)
    result={'schema_version':1,'protocol':{'purpose':'small engineering smoke only; no competitive or timing conclusion','random_seed':random_seed,'K':K,'block_size':s,'n':K*s,'within_pair_ring_per_block':6,'within_rank4_edges_per_block':8,'cross_rank4_edges':6,'query_seeds':[0,6,12,18],'primary_splitting':'all_or_nothing','cardinality_min':'explicitly scoped concave subgroup; Mono observational; general G-E0 remains blocked','truth_use':'posthoc metrics only; never passed into method','config':{'sigma':1e-4,'patience':3,'mass_budget_fraction':.5,'region':'R-supp','objective':'ZH','diffusion_backend':'cvxpy'}},'edges':[list(e) for e in edges],'queries':queries,'metadata':{'elapsed_seconds':time.perf_counter()-start,'timing_claim':False,'python':platform.python_version(),'platform':platform.platform(),'source_SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    output=PROJECT/'results/m5_core/hsbm_smoke.json';output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise RuntimeError('Preserve immutable raw measurement')
    output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
