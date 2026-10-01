"""Measured 10k input loading plus analytic million-node CSR storage estimates."""
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from zrhfd.graph import Graph

def main():
    catalog=json.loads((ROOT/"data/test/calibrated_lfr/catalog.json").read_text())
    case=next(r for r in catalog["cases"] if r["n"]==10000)
    before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    start=time.perf_counter();graph=Graph.load(ROOT/case["graph_path"]);seconds=time.perf_counter()-start
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    persistent=sum(a.nbytes for a in [graph.indptr,graph.indices,graph.weights,graph.degree])
    edge_python=sys.getsizeof(graph.edges)+sum(sys.getsizeof(e)+sum(sys.getsizeof(v) for v in e) for e in graph.edges)
    n=1_000_000;m=10_000_000;M=2*m
    estimate={"n":n,"mean_degree":20,"undirected_edges":m,"stored_directed_indices":M,
              "current_int64_float64_arrays_bytes":8*(n+1)+8*M+8*M+8*n,
              "planned_unweighted_int32_indices_int64_indptr_float64_degrees_bytes":4*M+8*(n+1)+8*n,
              "current_python_edge_object_estimate_bytes":edge_python/len(graph.edges)*m,
              "dense_float64_adjacency_bytes":8*n*n,
              "solver_dense_score_bytes":8*n,"bounded_int64_queue_bytes":8*(n+1),"bool_in_queue_bytes":n,
              "estimate_status":"analytical linear extrapolation; no million-node graph generated or loaded"}
    out={"measured_case":case["case_id"],"measured_n":graph.n,"measured_edges":len(graph.edges),"graph_load_seconds":seconds,
         "measured_numpy_arrays_bytes":persistent,"measured_python_edges_recursive_bytes_with_duplicates":edge_python,
         "process_max_rss_before":before,"process_max_rss_after":rss,"rss_unit":"bytes on macOS, KiB on Linux",
         "runtime":{"python":sys.version,"platform":platform.platform(),"host_ram_bytes":int(subprocess.check_output(["sysctl","-n","hw.memsize"],text=True))},
         "scale_estimate":estimate,
         "recommendations":["Generate native sparse edge stream; never draw or allocate n*n arrays for scale LFR",
                            "Store CSR arrays separately as .npy and memory-map; use int32 neighbor IDs while n<2^31, int64 offsets; no per-edge float64 weights for unweighted graphs",
                            "Add CSR-native loader without Graph.edges Python tuple list, and avoid JSON graph parsing/COO staging for million-node input",
                            "Run measured algorithms serially; log peak RSS, touched support, and generation/loading time separately",
                            "Generate only after root authorizes M6; freeze parameters and resource budget first; scale runtime remains NOT RUN"]}
    path=ROOT/"results/data_generation/storage_assessment.json";path.write_text(json.dumps(out,indent=1));print(json.dumps(out,indent=1))
if __name__=="__main__":main()
