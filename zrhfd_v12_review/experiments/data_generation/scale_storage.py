"""Sparse native-file to memmapped CSR conversion and truth-only telemetry."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import resource
import time
import numpy as np
from numba import njit

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);data=(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()
    if path.exists() and path.read_bytes()!=data:raise RuntimeError(f"Refuse overwrite immutable {path}")
    path.write_bytes(data);return hashlib.sha256(data).hexdigest()

@njit(cache=False)
def _check_and_external(ptr,idx,labels):
    n=len(ptr)-1;external=np.zeros(n,np.int64);violations=0
    for u in range(n):
        previous=-1
        for j in range(ptr[u],ptr[u+1]):
            v=int(idx[j])
            if v<=previous or v==u or v<0 or v>=n:violations+=1
            previous=v
            if labels[u]!=labels[v]:external[u]+=1
            lo=ptr[v];hi=ptr[v+1]
            while lo<hi:
                mid=(lo+hi)//2
                if idx[mid]<u:lo=mid+1
                else:hi=mid
            if lo==ptr[v+1] or idx[lo]!=u:violations+=1
    return violations,external

def convert(raw,dest,n):
    begin=time.perf_counter();dest.mkdir(parents=True,exist_ok=True)
    if (dest/"csr_metadata.json").exists():return json.loads((dest/"csr_metadata.json").read_text())
    counts=np.zeros(n,np.int64);rawrows=loops=0
    with (raw/"network.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):continue
            u,v=map(int,line.split()[:2]);u-=1;v-=1;rawrows+=1
            if not(0<=u<n and 0<=v<n):raise ValueError("Native edge node ID out of range")
            if u==v:loops+=1;continue
            counts[u]+=1
    initial_ptr=np.r_[0,np.cumsum(counts)].astype(np.int64);cursor=initial_ptr[:-1].copy()
    tmp=dest/"indices.initial.npy";dtype=np.int32 if n<2**31 else np.int64
    idx=np.lib.format.open_memmap(tmp,mode="w+",dtype=dtype,shape=(int(initial_ptr[-1]),))
    with (raw/"network.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):continue
            u,v=map(int,line.split()[:2]);u-=1;v-=1
            if u==v:continue
            idx[cursor[u]]=v;cursor[u]+=1
    if not np.array_equal(cursor,initial_ptr[1:]):raise ValueError("Native network changed between streaming passes")
    ptr=np.zeros(n+1,np.int64);pos=0
    for u in range(n):
        unique=np.unique(idx[initial_ptr[u]:initial_ptr[u+1]])
        idx[pos:pos+len(unique)]=unique;pos+=len(unique);ptr[u+1]=pos
    idx.flush();del idx
    if pos==initial_ptr[-1]:tmp.rename(dest/"indices.npy")
    else:
        source=np.load(tmp,mmap_mode="r");final=np.lib.format.open_memmap(dest/"indices.npy",mode="w+",dtype=dtype,shape=(pos,))
        for start in range(0,pos,1_000_000):final[start:start+1_000_000]=source[start:start+1_000_000]
        final.flush();del final,source;tmp.unlink()
    np.save(dest/"indptr.npy",ptr,allow_pickle=False)
    degree=np.lib.format.open_memmap(dest/"degree.npy",mode="w+",dtype=np.float64,shape=(n,));degree[:]=np.diff(ptr);degree.flush()
    weights=np.lib.format.open_memmap(dest/"weights.npy",mode="w+",dtype=np.float64,shape=(pos,));weights[:]=1.;weights.flush();del weights
    native_labels=np.full(n,-1,np.int32);groups={}
    with (raw/"community.dat").open() as f:
        for line in f:
            if not line.strip():continue
            values=list(map(int,line.split()));u=values[0]-1
            if len(values)!=2 or not 0<=u<n or native_labels[u]!=-1:raise ValueError("Bad native truth partition")
            native_labels[u]=values[1];groups.setdefault(values[1],[]).append(u)
    if np.any(native_labels<0):raise ValueError("Incomplete native truth")
    communities=[sorted(groups[k]) for k in sorted(groups)];labels=np.empty(n,np.int32)
    for ci,C in enumerate(communities):labels[C]=ci
    idx=np.load(dest/"indices.npy",mmap_mode="r");violations,external=_check_and_external(ptr,idx,labels)
    if violations:raise ValueError(f"CSR has {violations} sorted/simple/symmetry violations")
    if np.any(degree==0):raise ValueError("Isolated node")
    M=int(degree.sum());volumes=np.bincount(labels,weights=degree,minlength=len(communities));cuts=np.bincount(labels,weights=external,minlength=len(communities))
    phi=cuts/np.minimum(volumes,M-volumes)
    truth_sha=write(dest/"truth.json",{"communities":communities})
    files={name:f"{name}.npy" for name in ["indptr","indices","weights","degree"]}
    meta={"schema_version":1,"n":n,"edge_count":pos//2,"total_volume":M,"integer_weights":True,"unweighted":True,"files":files,"sha256":{name:sha(dest/path) for name,path in files.items()},
          "truth_file":"truth.json","truth_sha256":truth_sha,"source_network_sha256":sha(raw/"network.dat"),"source_community_sha256":sha(raw/"community.dat"),
          "neighbor_dtype":np.dtype(dtype).name,"offset_dtype":"int64","raw_edge_rows":rawrows,"removed_self_loops":loops,"removed_duplicate_arcs":int(initial_ptr[-1])-pos,
          "structural_violations":int(violations),"statistics":{"weighted_truth_conductance":float(np.dot(volumes,phi)/M),"truth_conductance":phi.tolist(),"truth_volumes":volumes.astype(int).tolist(),"truth_cuts":cuts.astype(int).tolist(),
          "truth_conductance_quantiles":np.quantile(phi,[0,.25,.5,.75,1]).tolist(),"community_sizes":[len(C) for C in communities],"mean_degree":M/n,"max_degree":int(degree.max()),"min_degree":int(degree.min())},
          "conversion_seconds":time.perf_counter()-begin,"process_max_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"created_at_utc":datetime.now(timezone.utc).isoformat()}
    write(dest/"csr_metadata.json",meta);return meta
