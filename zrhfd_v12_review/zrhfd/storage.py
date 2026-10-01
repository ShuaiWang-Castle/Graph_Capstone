"""Read-only CSR input loading with a lazy upper-edge view for global baselines."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from .graph import Graph

class UpperEdges:
    """Reentrant iterable; retains only CSR references, never a Python edge list."""
    def __init__(self,indptr,indices,weights):
        self.indptr=indptr;self.indices=indices;self.weights=weights
    def __len__(self):return len(self.indices)//2
    def __iter__(self):
        for u in range(len(self.indptr)-1):
            for j in range(int(self.indptr[u]),int(self.indptr[u+1])):
                v=int(self.indices[j])
                if u<v:yield (u,v,float(self.weights[j]))

def _sha(path):
    digest=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()

def load_csr(path,verify_hashes=False):
    """Return the existing Graph interface backed by read-only .npy memmaps.

    path is either a CSR directory or its csr_metadata.json. Structure validation
    is recorded by the producer; loading checks shapes/endpoints and optional
    file hashes without materializing edges or a dense adjacency.
    """
    path=Path(path);meta_path=path/"csr_metadata.json" if path.is_dir() else path
    meta=json.loads(meta_path.read_text());base=meta_path.parent
    arrays={name:np.load(base/filename,mmap_mode="r",allow_pickle=False) for name,filename in meta["files"].items()}
    n=int(meta["n"]);ptr=arrays["indptr"];idx=arrays["indices"];weights=arrays["weights"];degree=arrays["degree"]
    if ptr.shape!=(n+1,) or degree.shape!=(n,) or ptr[0]!=0 or ptr[-1]!=len(idx) or weights.shape!=idx.shape:
        raise ValueError("Malformed CSR shapes")
    if np.any(ptr[1:]<ptr[:-1]):raise ValueError("CSR offsets are not monotone")
    if verify_hashes:
        for name,filename in meta["files"].items():
            if _sha(base/filename)!=meta["sha256"][name]:raise ValueError(f"CSR hash differs: {name}")
    total=float(degree.sum())
    if total!=float(meta["total_volume"]):raise ValueError("CSR degree total differs")
    return Graph(n,UpperEdges(ptr,idx,weights),ptr,idx,weights,degree,total,bool(meta["integer_weights"]))
