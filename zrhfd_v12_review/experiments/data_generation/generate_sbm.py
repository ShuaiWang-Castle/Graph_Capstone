"""Generate the frozen M3 SBM dev inputs; never run clustering quality."""
import json
import time
import numpy as np
from common import ROOT,CONFIG,metrics,queries,sha,write_json

def main():
    cfg=json.loads(CONFIG.read_text())["sbm"];base=ROOT/"data/dev/sbm_v12"
    write_json(base/"GENERATION_FREEZE.json",{"config_sha256":sha(CONFIG),"sbm":cfg,"numpy":np.__version__},immutable=True)
    metadata_path=ROOT/"results/data_generation/sbm_generation.json"
    if metadata_path.exists() and (base/"catalog.json").exists():
        print(metadata_path.read_text());return
    grng=np.random.default_rng(cfg["graph_rng_seed"]);qrng=np.random.default_rng(cfg["query_rng_seed"]);rows=[];start=time.perf_counter()
    for K in cfg["K_values"]:
        for ri,(s,p,q) in enumerate(cfg["regimes"]):
            for rep in range(cfg["replicates"]):
                case=f"sbm_k{K}_r{ri}_rep{rep}";n=K*s;lab=np.repeat(np.arange(K),s)
                before=grng.bit_generator.state
                P=np.where(lab[:,None]==lab[None,:],p,q)
                upper=np.triu(grng.random((n,n))<P,1)
                edges=np.transpose(np.nonzero(upper)).tolist()
                C=[list(range(k*s,(k+1)*s)) for k in range(K)]
                gp=base/f"{case}.graph.json";tp=base/f"{case}.truth.json";qp=base/f"{case}.queries.json"
                gh=write_json(gp,{"n":n,"edges":edges},immutable=True);th=write_json(tp,{"communities":C},immutable=True)
                qbefore=qrng.bit_generator.state;Q=queries(C,qrng);qh=write_json(qp,{"queries":Q},immutable=True)
                row={"case_id":case,"split":"dev","generator":"SBM full-matrix rng upper triangle","K":K,"block_size":s,"p":p,"q":q,"rep":rep,
                     "graph_path":gp.relative_to(ROOT).as_posix(),"truth_path":tp.relative_to(ROOT).as_posix(),"queries_path":qp.relative_to(ROOT).as_posix(),
                     "graph_sha256":gh,"truth_sha256":th,"queries_sha256":qh,"query_count":len(Q),"rng_before_graph":before,"rng_after_graph":grng.bit_generator.state,
                     "rng_before_queries":qbefore,"rng_after_queries":qrng.bit_generator.state,"statistics":metrics(n,edges,C)}
                rows.append(row);print(json.dumps({"case_id":case,"n":n,"edges":len(edges),"queries":len(Q)}),flush=True)
    write_json(base/"catalog.json",{"schema_version":1,"config_sha256":sha(CONFIG),"cases":rows},immutable=True)
    write_json(metadata_path,{"status":"GENERATED","graph_count":len(rows),"query_count":sum(r["query_count"] for r in rows),"seconds":time.perf_counter()-start},immutable=True)

if __name__=="__main__":main()
