"""Truth-conductance-only deterministic native LFR calibration with raw retention."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import numpy as np
from common import ROOT,CONFIG,metrics,queries,sha,write_json

def parse(raw,n):
    edges=set();loops=0;rawrows=0
    for line in (raw/"network.dat").read_text().splitlines():
        if not line.strip() or line.startswith("#"):continue
        u,v=map(int,line.split()[:2]);u-=1;v-=1;rawrows+=1
        if not(0<=u<n and 0<=v<n):raise ValueError("Unexpected node IDs")
        if u==v:loops+=1;continue
        edges.add(tuple(sorted((u,v))))
    membership={};groups={}
    for line in (raw/"community.dat").read_text().splitlines():
        if not line.strip():continue
        v=list(map(int,line.split()));u=v[0]-1
        if u in membership or not 0<=u<n or len(v)!=2:raise ValueError("Membership is not a complete disjoint partition")
        membership[u]=v[1];groups.setdefault(v[1],[]).append(u)
    if len(membership)!=n:raise ValueError("Missing membership nodes")
    C=[sorted(groups[k]) for k in sorted(groups)];E=[list(e) for e in sorted(edges)];m=metrics(n,E,C)
    if m["isolated_nodes"]:raise ValueError("Isolated nodes")
    m.update(raw_edge_rows=rawrows,self_loops_removed=loops)
    return {"n":n,"edges":E},{"communities":C},m

def next_mu(target,current,attempts):
    valid=[a for a in attempts if a["status"]=="VALID"]
    if attempts[-1]["status"]!="VALID":
        offsets=[.015,-.015,.030,-.030,.060,-.060,.100]
        return float(np.clip(target+offsets[len(attempts)-1],.001,.999))
    below=[a for a in valid if a["statistics"]["weighted_truth_conductance"]<target]
    above=[a for a in valid if a["statistics"]["weighted_truth_conductance"]>target]
    if below and above:
        lo=max(below,key=lambda a:a["native_mu"]);hi=min(above,key=lambda a:a["native_mu"])
        candidate=(lo["native_mu"]+hi["native_mu"])/2
    else:candidate=current+target-attempts[-1]["statistics"]["weighted_truth_conductance"]
    return float(np.clip(candidate,.001,.999))

def main():
    config=json.loads(CONFIG.read_text());cfg=config["lfr"];base=ROOT/"data/test/calibrated_lfr";out=ROOT/"results/data_generation"
    binary=ROOT/cfg["generator_binary"];lock=ROOT/"provenance/generators/lfr_native.json"
    freeze={"config_sha256":sha(CONFIG),"generator_provenance_sha256":sha(lock),"generator_binary_sha256":sha(binary),"lfr":cfg}
    write_json(base/"GENERATION_FREEZE.json",freeze,immutable=True)
    metadata_path=out/"lfr_generation.json"
    if metadata_path.exists():
        recorded=json.loads(metadata_path.read_text())
        if sha(base/"catalog.json")!=recorded["catalog_sha256"]:raise RuntimeError("Completed frozen catalog differs")
        print(json.dumps(recorded));return
    qrng=np.random.default_rng(cfg["query_rng_seed"]);rows=[];start=time.perf_counter()
    for n in cfg["n_values"]:
        for target in cfg["target_weighted_conductance"]:
            for seed in cfg["generation_seeds"]:
                case=f"lfr_n{n}_phi{round(100*target):02d}_s{seed}";mu=target;attempts=[];selected=None
                for ai in range(cfg["max_attempts"]):
                    raw=base/"attempts"/case/f"attempt_{ai:02d}";raw.mkdir(parents=True,exist_ok=True);rp=raw/"record.json"
                    if rp.exists():record=json.loads(rp.read_text())
                    else:
                        (raw/"time_seed.dat").write_text(str(seed)+"\n");(raw/"time_seed.before.dat").write_text(str(seed)+"\n")
                        minc,maxc=cfg["community_bounds"][str(n)]
                        flags=["-N",str(n),"-k",str(cfg["mean_degree"]),"-maxk",str(cfg["max_degree"]),"-mu",format(mu,".17g"),"-t1",str(cfg["degree_exponent"]),"-t2",str(cfg["community_exponent"]),"-minc",str(minc),"-maxc",str(maxc),"-on","0","-om","0"]
                        record={"case_id":case,"attempt_index":ai,"generation_seed":seed,"native_mu":mu,"target":target,
                                "argv":[cfg["generator_binary"],*flags],"config_sha256":sha(CONFIG),"started_at_utc":datetime.now(timezone.utc).isoformat()}
                        begin=time.perf_counter()
                        try:
                            with (raw/"stdout.log").open("w") as stdout,(raw/"stderr.log").open("w") as stderr:
                                run=subprocess.run([str(binary),*flags],cwd=raw,stdout=stdout,stderr=stderr,timeout=cfg["seconds_per_attempt"],check=False)
                            record["exit_code"]=run.returncode
                            if run.returncode:raise RuntimeError(f"Native generator exit {run.returncode}")
                            g,t,m=parse(raw,n)
                            write_json(raw/"graph.json",g,immutable=True);write_json(raw/"truth.json",t,immutable=True)
                            record.update(status="VALID",statistics=m,absolute_deviation=abs(m["weighted_truth_conductance"]-target),
                                          graph_sha256=sha(raw/"graph.json"),truth_sha256=sha(raw/"truth.json"))
                        except subprocess.TimeoutExpired:record.update(status="TIMEOUT")
                        except Exception as exc:record.update(status="ERROR",error=repr(exc))
                        if (raw/"time_seed.dat").exists():(raw/"time_seed.after.dat").write_bytes((raw/"time_seed.dat").read_bytes())
                        record["seconds"]=time.perf_counter()-begin
                        record["raw_files_sha256"]={p.name:sha(p) for p in sorted(raw.iterdir()) if p.is_file() and p!=rp}
                        write_json(rp,record,immutable=True)
                    attempts.append(record)
                    print(json.dumps({"case_id":case,"attempt":ai,"status":record["status"],"native_mu":mu,"observed_phi":record.get("statistics",{}).get("weighted_truth_conductance"),"seconds":record.get("seconds")}),flush=True)
                    if record["status"]=="VALID" and record["absolute_deviation"]<=cfg["tolerance"]:
                        selected=record;break
                    if ai+1<cfg["max_attempts"]:mu=next_mu(target,mu,attempts)
                valid=[r for r in attempts if r["status"]=="VALID"]
                if selected is None and valid:selected=min(valid,key=lambda r:(r["absolute_deviation"],r["attempt_index"]))
                row={"case_id":case,"split":"test","n":n,"target_weighted_conductance":target,"generation_seed":seed,"attempt_count":len(attempts),
                     "attempt_records":[(base/"attempts"/case/f"attempt_{r['attempt_index']:02d}"/"record.json").relative_to(ROOT).as_posix() for r in attempts]}
                if selected is None:row["status"]="GENERATION_FAILED"
                else:
                    raw=base/"attempts"/case/f"attempt_{selected['attempt_index']:02d}";g=json.loads((raw/"graph.json").read_text());t=json.loads((raw/"truth.json").read_text())
                    gp=base/"graphs"/f"{case}.graph.json";tp=base/"truth"/f"{case}.truth.json";qp=base/"queries"/f"{case}.queries.json"
                    gh=write_json(gp,g,immutable=True);th=write_json(tp,t,immutable=True)
                    qbefore=qrng.bit_generator.state;Q=queries(t["communities"],qrng,6);qh=write_json(qp,{"queries":Q},immutable=True)
                    row.update(status="CALIBRATED" if selected["absolute_deviation"]<=cfg["tolerance"] else "UNREACHED",selected_attempt=selected["attempt_index"],native_mu=selected["native_mu"],statistics=selected["statistics"],
                               graph_path=gp.relative_to(ROOT).as_posix(),truth_path=tp.relative_to(ROOT).as_posix(),queries_path=qp.relative_to(ROOT).as_posix(),
                               graph_sha256=gh,truth_sha256=th,queries_sha256=qh,query_count=len(Q),rng_before_queries=qbefore,rng_after_queries=qrng.bit_generator.state)
                rows.append(row);write_json(base/"catalog.json",{"schema_version":1,"generation_freeze_sha256":sha(base/"GENERATION_FREEZE.json"),"cases":rows})
    metadata={"completed_at_utc":datetime.now(timezone.utc).isoformat(),"python":sys.version,"platform":platform.platform(),"numpy":np.__version__,"seconds":time.perf_counter()-start,
              "environment":{k:os.environ.get(k) for k in ["OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS"]},"status_counts":{s:sum(r["status"]==s for r in rows) for s in ["CALIBRATED","UNREACHED","GENERATION_FAILED"]},
              "attempts":sum(r["attempt_count"] for r in rows),"query_count":sum(r.get("query_count",0) for r in rows),"catalog_sha256":sha(base/"catalog.json")}
    write_json(metadata_path,metadata,immutable=True);print(json.dumps(metadata),flush=True)
if __name__=="__main__":main()
