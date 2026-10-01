"""Validate sparse storage against existing small JSON input, without algorithms."""
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import numpy as np
from numba import njit
from scale_storage import convert,sha,write

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from zrhfd.graph import Graph
from zrhfd.storage import load_csr

@njit(cache=False)
def neighbor_checksum(ptr,idx,weights):
    total=0.
    for u in range(len(ptr)-1):
        for j in range(ptr[u],ptr[u+1]):total+=(u+1)*(int(idx[j])+1)*weights[j]
    return total

def main():
    case="lfr_n1000_phi30_s202610011"
    catalog=json.loads((ROOT/"data/test/calibrated_lfr/catalog.json").read_text())
    row=next(r for r in catalog["cases"] if r["case_id"]==case)
    raw=ROOT/"data/test/calibrated_lfr/attempts"/case/f"attempt_{row['selected_attempt']:02d}"
    dest=ROOT/"data/scale/validation"/case;meta=convert(raw,dest,1000)
    start=time.perf_counter();csr=load_csr(dest,verify_hashes=True);loadsecs=time.perf_counter()-start
    standard=Graph.load(ROOT/row["graph_path"])
    C=json.loads((ROOT/row["truth_path"]).read_text())["communities"]
    rng=np.random.default_rng(202610060);sets=C+[rng.choice(1000,size=size,replace=False).tolist() for size in [1,2,7,21,199,501]]
    stats_equal=all(csr.stats(S)==standard.stats(S) for S in sets)
    neighbor_equal=all(np.array_equal(csr.indices[csr.indptr[u]:csr.indptr[u+1]],standard.indices[standard.indptr[u]:standard.indptr[u+1]]) for u in range(1000))
    upper=[[u,v] for u,v,w in csr.edges]
    expected=json.loads((ROOT/row["graph_path"]).read_text())
    canonical=(json.dumps({"n":1000,"edges":upper},sort_keys=True,separators=(",",":"))+"\n").encode()
    upper_hash=hashlib.sha256(canonical).hexdigest()
    readonly=all(not a.flags.writeable for a in [csr.indptr,csr.indices,csr.weights,csr.degree])
    checksum_equal=neighbor_checksum(csr.indptr,csr.indices,csr.weights)==neighbor_checksum(standard.indptr,standard.indices,standard.weights)
    result={"fixture":case,"stats_test_set_count":len(sets),"stats_identical":stats_equal,"all_node_neighbors_identical":neighbor_equal,
            "lazy_edges_identical":list(csr.edges)==standard.edges,"canonical_upper_edge_hash":upper_hash,"expected_graph_hash":row["graph_sha256"],
            "canonical_hash_equal":upper_hash==row["graph_sha256"],"all_arrays_readonly":readonly,"numba_readonly_int32_csr_compatible":bool(checksum_equal),
            "total_volume_identical":csr.total==standard.total,"integer_weights":csr.integer_weights,"load_and_verify_seconds":loadsecs,
            "process_max_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"storage_source_sha256":sha(ROOT/"zrhfd/storage.py"),
            "all_checks_pass":bool(stats_equal and neighbor_equal and upper_hash==row["graph_sha256"] and readonly and checksum_equal and csr.total==standard.total)}
    write(ROOT/"results/data_generation/scale_storage_validation.json",result);print(json.dumps(result,indent=1))
if __name__=="__main__":main()
