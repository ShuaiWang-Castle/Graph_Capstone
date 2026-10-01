"""Run the frozen nine native scale inputs and build sparse memmapped CSR."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import platform
import re
import resource
import signal
import subprocess
import sys
import time
import numpy as np
from scale_storage import convert,sha,write

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from zrhfd.storage import load_csr
CONFIG=ROOT/"experiments/data_generation/scale_config.json"

def main():
    cfg=json.loads(CONFIG.read_text());base=ROOT/"data/scale";binary=ROOT/cfg["generator_binary"]
    write(base/"GENERATION_FREEZE.json",{"config":cfg,"config_sha256":sha(CONFIG),"binary_sha256":sha(binary),"generator_lock_sha256":sha(ROOT/"provenance/generators/lfr_native.json")})
    done=ROOT/"results/data_generation/scale_generation.json"
    if done.exists():
        metadata=json.loads(done.read_text())
        if metadata["catalog_sha256"]!=sha(base/"catalog.json"):raise RuntimeError("Scale catalog differs")
        print(json.dumps(metadata));return
    rows=[];overall=time.perf_counter()
    for n in cfg["n_values"]:
        for seed in cfg["generation_seeds"]:
            case=f"lfr_scale_n{n}_s{seed}";mu=cfg["target_weighted_conductance"];attempts=[];selected=None
            for ai in range(cfg["max_attempts"]):
                raw=base/case/"attempts"/f"attempt_{ai:02d}";raw.mkdir(parents=True,exist_ok=True);recpath=raw/"record.json"
                csrdir=base/case/"csr_attempts"/f"attempt_{ai:02d}"
                if recpath.exists():record=json.loads(recpath.read_text())
                else:
                    print(json.dumps({"event":"starting","case_id":case,"n":n,"attempt":ai,"native_mu":mu}),flush=True)
                    (raw/"time_seed.dat").write_text(f"{seed}\n");(raw/"time_seed.before.dat").write_text(f"{seed}\n")
                    lo,hi=cfg["community_bounds"]
                    flags=["-N",str(n),"-k",str(cfg["mean_degree"]),"-maxk",str(cfg["max_degree"]),"-mu",format(mu,".17g"),"-t1",str(cfg["degree_exponent"]),"-t2",str(cfg["community_exponent"]),"-minc",str(lo),"-maxc",str(hi),"-on","0","-om","0"]
                    record={"case_id":case,"attempt_index":ai,"n":n,"seed":seed,"native_mu":mu,"argv":[cfg["generator_binary"],*flags],"started_at_utc":datetime.now(timezone.utc).isoformat(),"config_sha256":sha(CONFIG)}
                    start=time.perf_counter()
                    try:
                        with (raw/"stdout.log").open("w") as stdout,(raw/"stderr.log").open("w") as stderr:
                            process=subprocess.Popen(["/usr/bin/time","-l",str(binary),*flags],cwd=raw,stdout=stdout,stderr=stderr,start_new_session=True)
                            sampled_peak=0
                            while process.poll() is None:
                                if time.perf_counter()-start>cfg["seconds_per_generation_attempt"]:
                                    os.killpg(process.pid,signal.SIGKILL);process.wait();raise subprocess.TimeoutExpired(process.args,cfg["seconds_per_generation_attempt"])
                                inventory=subprocess.check_output(["ps","-axo","pid=,ppid=,rss="],text=True)
                                processes=[tuple(map(int,line.split())) for line in inventory.splitlines() if len(line.split())==3]
                                descendants={process.pid}
                                for _ in range(4):
                                    descendants.update(pid for pid,ppid,rss in processes if ppid in descendants)
                                rss=sum(rss*1024 for pid,ppid,rss in processes if pid in descendants)
                                sampled_peak=max(sampled_peak,rss)
                                if rss>cfg["memory_limit_bytes"]:
                                    os.killpg(process.pid,signal.SIGKILL);process.wait();raise MemoryError(f"Native process-group RSS {rss} exceeds frozen limit")
                                time.sleep(1)
                            code=process.returncode
                            record["sampled_process_group_peak_rss_bytes"]=sampled_peak
                        record["generation_seconds"]=time.perf_counter()-start;record["exit_code"]=code
                        peak=re.search(r"(\d+)\s+maximum resident set size",(raw/"stderr.log").read_text())
                        if peak:record["native_max_rss_bytes"]=int(peak.group(1))
                        if code:raise RuntimeError(f"Native generation exit {code}")
                        print(json.dumps({"event":"native_complete","case_id":case,"generation_seconds":record["generation_seconds"],"native_max_rss_bytes":record.get("native_max_rss_bytes")}),flush=True)
                        meta=convert(raw,csrdir,n)
                        deviation=abs(meta["statistics"]["weighted_truth_conductance"]-cfg["target_weighted_conductance"])
                        record.update(status="VALID",absolute_deviation=deviation,statistics=meta["statistics"],csr_path=csrdir.relative_to(ROOT).as_posix(),csr_metadata_sha256=sha(csrdir/"csr_metadata.json"),conversion_seconds=meta["conversion_seconds"])
                    except subprocess.TimeoutExpired:record.update(status="TIMEOUT",generation_seconds=time.perf_counter()-start,algorithm_status="NOT_RUN_RESOURCE_TIMEOUT")
                    except Exception as exc:record.update(status="ERROR",error=repr(exc),algorithm_status="NOT_RUN_INPUT_ERROR")
                    if (raw/"time_seed.dat").exists():(raw/"time_seed.after.dat").write_bytes((raw/"time_seed.dat").read_bytes())
                    record["raw_files_sha256"]={p.name:sha(p) for p in sorted(raw.iterdir()) if p.is_file() and p!=recpath}
                    write(recpath,record)
                attempts.append(record);print(json.dumps({"event":"attempt_complete","case_id":case,"attempt":ai,"status":record["status"],"phi":record.get("statistics",{}).get("weighted_truth_conductance")}),flush=True)
                if record["status"]=="VALID" and record["absolute_deviation"]<=cfg["tolerance"]:selected=record;break
                if ai+1<cfg["max_attempts"]:
                    valid=[r for r in attempts if r["status"]=="VALID"]
                    if record["status"]!="VALID":mu=float(np.clip(cfg["target_weighted_conductance"]+[.015,-.015][ai],.001,.999))
                    else:
                        below=[r for r in valid if r["statistics"]["weighted_truth_conductance"]<cfg["target_weighted_conductance"]]
                        above=[r for r in valid if r["statistics"]["weighted_truth_conductance"]>cfg["target_weighted_conductance"]]
                        if below and above:mu=(max(r["native_mu"] for r in below)+min(r["native_mu"] for r in above))/2
                        else:mu=float(np.clip(mu+cfg["target_weighted_conductance"]-record["statistics"]["weighted_truth_conductance"],.001,.999))
            valid=[r for r in attempts if r["status"]=="VALID"]
            if selected is None and valid:selected=min(valid,key=lambda r:(r["absolute_deviation"],r["attempt_index"]))
            row={"case_id":case,"n":n,"generation_seed":seed,"attempt_count":len(attempts),"target_weighted_conductance":cfg["target_weighted_conductance"],"algorithm_status":"NOT_RUN_DATA_GENERATION_ONLY",
                 "attempt_records":[(base/case/"attempts"/f"attempt_{a['attempt_index']:02d}"/"record.json").relative_to(ROOT).as_posix() for a in attempts]}
            if selected is None:row.update(status="GENERATION_FAILED",failure_statuses=[a["status"] for a in attempts])
            else:
                csrdir=ROOT/selected["csr_path"];meta=json.loads((csrdir/"csr_metadata.json").read_text())
                truth=json.loads((csrdir/"truth.json").read_text())["communities"];rng=np.random.default_rng(cfg["query_rng_seed"])
                ids=rng.choice(len(truth),min(6,len(truth)),replace=False)
                Q=[{"community_index":int(ci),"seed":int(s)} for ci in ids for s in rng.choice(truth[int(ci)],min(2,len(truth[int(ci)])),replace=False)]
                qp=base/case/"queries.json";qh=write(qp,{"queries":Q});loadstart=time.perf_counter();graph=load_csr(csrdir,verify_hashes=True);loadsecs=time.perf_counter()-loadstart
                row.update(status="CALIBRATED" if selected["absolute_deviation"]<=cfg["tolerance"] else "UNREACHED",selected_attempt=selected["attempt_index"],native_mu=selected["native_mu"],
                           csr_path=selected["csr_path"],csr_metadata_sha256=selected["csr_metadata_sha256"],truth_path=(csrdir/"truth.json").relative_to(ROOT).as_posix(),truth_sha256=meta["truth_sha256"],
                           queries_path=qp.relative_to(ROOT).as_posix(),queries_sha256=qh,query_count=len(Q),statistics=selected["statistics"],
                           generation_seconds=selected["generation_seconds"],conversion_seconds=selected["conversion_seconds"],load_verify_hash_seconds=loadsecs,native_max_rss_bytes=selected.get("native_max_rss_bytes"),
                           controller_max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,csr_arrays_bytes=sum(a.nbytes for a in [graph.indptr,graph.indices,graph.weights,graph.degree]))
                del graph,truth
            rows.append(row)
            catalog={"schema_version":1,"config_sha256":sha(CONFIG),"cases":rows}
            (base/"catalog.json").write_text(json.dumps(catalog,sort_keys=True,separators=(",",":"))+"\n")
            print(json.dumps({"event":"case_complete","case_id":case,"status":row["status"],"generation_seconds":row.get("generation_seconds"),"conversion_seconds":row.get("conversion_seconds"),"load_seconds":row.get("load_verify_hash_seconds")}),flush=True)
    metadata={"completed_at_utc":datetime.now(timezone.utc).isoformat(),"seconds":time.perf_counter()-overall,"status_counts":{s:sum(r["status"]==s for r in rows) for s in ["CALIBRATED","UNREACHED","GENERATION_FAILED"]},"query_count":sum(r.get("query_count",0) for r in rows),"catalog_sha256":sha(base/"catalog.json"),"python":sys.version,"platform":platform.platform(),"numpy":np.__version__}
    write(done,metadata);print(json.dumps(metadata),flush=True)
if __name__=="__main__":main()
