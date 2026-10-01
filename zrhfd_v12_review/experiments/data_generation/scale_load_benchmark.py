"""Independent-process CSR loading measurements; no clustering algorithms."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from zrhfd.storage import load_csr

def main():
    p=argparse.ArgumentParser();p.add_argument("--csr");p.add_argument("--case");a=p.parse_args()
    if a.csr:
        before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;start=time.perf_counter();g=load_csr(ROOT/a.csr)
        result={"case_id":a.case,"n":g.n,"edge_count":len(g.edges),"csr_path":a.csr,"load_seconds":time.perf_counter()-start,
                "baseline_max_rss_bytes":before,"loaded_max_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "arrays_logical_bytes":sum(x.nbytes for x in [g.indptr,g.indices,g.weights,g.degree]),
                "edges_type":type(g.edges).__name__,"edge_list_materialized":False,"hash_verification":False,
                "timing_status":"pure loader; operating-system file-cache state uncontrolled"}
        print(json.dumps(result));return
    rows=[]
    for row in json.loads((ROOT/"data/scale/catalog.json").read_text())["cases"]:
        if "csr_path" not in row:continue
        result=subprocess.check_output([sys.executable,str(Path(__file__).resolve()),"--csr",row["csr_path"],"--case",row["case_id"]],cwd=ROOT,text=True)
        rows.append(json.loads(result))
    (ROOT/"results/data_generation/scale_load_benchmark.json").write_text(json.dumps({"method":"one fresh Python process per graph, no algorithm or lazy-edge iteration","rows":rows},indent=1))
    print(json.dumps({"measured_graphs":len(rows)}))
if __name__=="__main__":main()
