"""Portable input schema and truth-only generation statistics."""
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/"experiments/data_generation/generation_config.json"
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,value,immutable=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()
    if immutable and path.exists() and path.read_bytes()!=data:raise RuntimeError(f"Immutable artifact differs: {path}")
    path.write_bytes(data);return hashlib.sha256(data).hexdigest()
def metrics(n,edges,communities):
    e=np.asarray(edges,np.int64).reshape(-1,2);d=np.bincount(e.ravel(),minlength=n);M=int(d.sum())
    lab=np.full(n,-1,np.int64)
    for ci,C in enumerate(communities):
        if np.any(lab[C]>=0):raise ValueError("Truth is overlapping")
        lab[C]=ci
    if np.any(lab<0):raise ValueError("Incomplete truth")
    external=lab[e[:,0]]!=lab[e[:,1]]
    ext_d=np.bincount(e[external].ravel(),minlength=n)
    volumes=np.asarray([d[C].sum() for C in communities],float)
    cuts=np.asarray([ext_d[C].sum() for C in communities],float)
    den=np.minimum(volumes,M-volumes)
    if np.any(den<=0):raise ValueError("Truth conductance undefined")
    phi=cuts/den
    return {"n":n,"edge_count":len(edges),"total_volume":M,"mean_degree":M/n,"max_degree":int(d.max()),"min_degree":int(d.min()),
            "isolated_nodes":int((d==0).sum()),"community_count":len(communities),"community_sizes":[len(C) for C in communities],
            "truth_volumes":volumes.astype(int).tolist(),"truth_cuts":cuts.astype(int).tolist(),"truth_conductance":phi.tolist(),
            "weighted_truth_conductance":float(np.dot(volumes,phi)/M),"truth_conductance_quantiles":np.quantile(phi,[0,.25,.5,.75,1]).tolist(),
            "external_edge_fraction":float(external.mean()),"truth_block_labels_sha256":hashlib.sha256(lab.astype("<i8").tobytes()).hexdigest()}
def queries(communities,rng,selected_count=None):
    ids=np.arange(len(communities)) if selected_count is None or len(communities)<=selected_count else rng.choice(len(communities),selected_count,replace=False)
    return [{"community_index":int(ci),"seed":int(s)} for ci in ids for s in rng.choice(communities[int(ci)],min(2,len(communities[int(ci)])),replace=False)]
