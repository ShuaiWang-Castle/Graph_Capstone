"""Canonical comparison/instance summary for the newly measured M0 runs."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/"results/m0_reference"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    catalog=read(ROOT/"data/dev/same12/catalog.json")
    comparisons={}
    for name in ["checks_g2","checks_g3b"]:
        reference=ROOT/"inputs/local_hfd/theory"/f"{name}.json"
        generated=OUT/name/f"{name}.json"
        comparisons[name]={"parsed_json_identical":read(reference)==read(generated),"historical_sha256":sha(reference),"new_run_sha256":sha(generated),
                           "new_run":generated.relative_to(ROOT).as_posix()}
    old=read(ROOT/"inputs/local_hfd/review_round1/attractor_and_leiden.json")
    legacy=read(OUT/"legacy_reconstruction/raw.json")
    diffs=[]
    for place,rows in old["attractor"].items():
        for qi,row in enumerate(rows):
            for key,value in row.items():
                observed=legacy["attractor"][place][qi][key]
                if observed!=value:
                    diffs.append({"place":place,"query_index":qi,"field":key,"historical":value,"observed":observed})
    comparisons["attractor"]={"all_24_rows_all_7_fields_identical":not diffs,"differences":diffs,
                              "historical_sha256":sha(ROOT/"inputs/local_hfd/review_round1/attractor_and_leiden.json"),
                              "new_run":(OUT/"legacy_reconstruction/raw.json").relative_to(ROOT).as_posix()}
    rows=[]
    trajectories=[]
    for name,variants in [("checks_g2",["spec-v1","A","B"]),("checks_g3b",["pat2-theta0.5","pat2-theta1.0","pat2-thetainf","pat3-theta0.5","pat3-theta1.0","pat3-thetainf"])]:
        events=read(OUT/name/"events.json")
        ms=[]
        schedule=[]
        reset_schedule=True
        last_flow=None
        for event in events:
            if event["event"]=="instance":
                reset_schedule=True
                schedule=[]
            elif event["event"]=="diffusion":
                last_flow=event
            elif event["event"]=="sweep":
                if reset_schedule:
                    schedule=[]
                    reset_schedule=False
                schedule.append({"j":len(schedule),"mass":last_flow["mass"],"support_size":len(last_flow["support"]),
                                 "support_volume":last_flow["support_volume"],"Z_sweep":event["Z"],"S_sweep":event["S"]})
            elif event["event"]=="mm":
                ms.append((event,list(schedule)))
                reset_schedule=True
        for ci,case in enumerate(catalog["cases"]):
            graph=read(ROOT/case["graph_path"])
            adjacency=[set() for _ in range(graph["n"])]
            for u,v in graph["edges"]:
                adjacency[u].add(v);adjacency[v].add(u)
            d=np.asarray([len(a) for a in adjacency])
            C=set(range(case["block_size"]))
            for vi,variant in enumerate(variants):
                event,schedule=ms[ci*len(variants)+vi]
                jstar=int(np.argmin([step["Z_sweep"] for step in schedule]))
                jact=next((step["j"] for step in schedule if step["support_size"]>=2),None)
                patience=3 if variant.startswith("pat3") else 2
                started=variant in {"spec-v1","A"}
                best=float("inf");noimp=0
                for step in schedule:
                    started=started or step["support_size"]>=2
                    if step["Z_sweep"]<best-1e-6:
                        best=step["Z_sweep"];noimp=0
                    elif started:noimp+=1
                stop_reason="patience" if noimp>=patience else "budget"
                trajectories.append({"case_id":case["case_id"],"script":name,"variant":variant,"j_act":jact,"j_star":jstar,
                                     "region_mass":schedule[0]["mass"]*2**(jstar+1),"stop_reason":stop_reason,
                                     "stopped_before_activation":jact is None,"schedule":schedule})
                S=set(event["out"]);R=set(event["R"])
                volume=int(d[list(S)].sum());cut=sum(len(adjacency[u]-S) for u in S);tp=len(S&C)
                rows.append({"case_id":case["case_id"],"script":name,"variant":variant,"seed":case["seed"],"n":case["n"],
                             "K":case["K"],"block_size":case["block_size"],"p":case["p"],"q":case["q"],
                             "out_size":len(S),"precision":tp/len(S),"recall":tp/len(C),"F1":2*tp/(len(S)+len(C)),
                             "out_equal_truth":S==C,"truth_in_region":C<=R,"failure_class":"success" if S==C else ("H1" if not C<=R else "H2"),
                             "region_size":len(R),"region_volume":int(d[list(R)].sum()),"region_outside_truth_volume":int(d[list(R-C)].sum()),
                             "out_volume":volume,"out_cut":cut,"out_Z":cut/volume+volume/case["total_volume"],
                             "symmetric_difference_size":len(S^C),"accepted_MM_steps":event["accepted_steps"],
                             "m_act":case["m_act"],"j_act":jact,"j_star":jstar,"J":len(schedule),
                             "region_mass":schedule[0]["mass"]*2**(jstar+1),"stop_reason":stop_reason,
                             "stopped_before_activation":jact is None,"MM_seconds":event["seconds"]})
    with (OUT/"per_instance.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (OUT/"reference_trajectories.json").write_text(json.dumps(trajectories,indent=1))
    summary={"comparisons":comparisons,"source_status":"historical core and hfd_gate per-query files missing; reference substitute explicitly documented",
             "same12_summary":read(OUT/"checks_g3b/checks_g3b.json")["summary"],"legacy_diagnostic_summary":read(OUT/"legacy_reconstruction/summary.json"),
             "claim_boundary":{"same12":"full measured numerical reproduction through verified kernel-derived shim; originalcore unavailable",
                               "attractor":"all24 historical query rows exactly reproduced through documented reconstruction; originalcore unavailable",
                               "two_mu50_historical_baselines":"NOT RUN as exact per-query reproduction; originalquery/results unavailable. New diagnostic rows do not establish oldmedian reproduction."}}
    (OUT/"summary.json").write_text(json.dumps(summary,indent=1))
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(OUT.rglob("*")) if p.is_file() and p.name!="raw_measurements.sha256.json"}
    (OUT/"raw_measurements.sha256.json").write_text(json.dumps(hashes,indent=1))
    print(json.dumps({"same12_reference_match":all(comparisons[n]["parsed_json_identical"] for n in ["checks_g2","checks_g3b"]),"attractor_reference_match":not diffs,"per_instance_rows":len(rows)}))


if __name__=="__main__":main()
