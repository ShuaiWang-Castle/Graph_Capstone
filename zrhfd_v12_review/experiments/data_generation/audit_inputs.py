"""Verify frozen data hashes, structural invariants, queries and native telemetry."""
import csv
import json
from pathlib import Path
import re
import numpy as np
from common import ROOT,CONFIG,metrics,queries,sha,write_json

def main():
    cfg=json.loads(CONFIG.read_text());rows=[];failures=[]
    for group,base,query_seed in [("sbm",ROOT/"data/dev/sbm_v12",cfg["sbm"]["query_rng_seed"]),("lfr",ROOT/"data/test/calibrated_lfr",cfg["lfr"]["query_rng_seed"])]:
        catalog=json.loads((base/"catalog.json").read_text());rng=np.random.default_rng(query_seed)
        for row in catalog["cases"]:
            if "graph_path" not in row:
                failures.append({"case_id":row["case_id"],"error":"no selected graph"});continue
            paths={name:ROOT/row[f"{name}_path"] for name in ["graph","truth","queries"]}
            hashes={name:sha(path)==row[f"{name}_sha256"] for name,path in paths.items()}
            g=json.loads(paths["graph"].read_text());t=json.loads(paths["truth"].read_text())["communities"];Q=json.loads(paths["queries"].read_text())["queries"]
            edges=[tuple(e) for e in g["edges"]]
            simple=all(0<=u<v<g["n"] for u,v in edges) and len(set(edges))==len(edges) and edges==sorted(edges)
            m=metrics(g["n"],g["edges"],t)
            query_replay=Q==queries(t,rng,6 if group=="lfr" else None)
            query_membership=all(q["seed"] in t[q["community_index"]] for q in Q)
            stat_equal=m["weighted_truth_conductance"]==row["statistics"]["weighted_truth_conductance"]
            record={"case_id":row["case_id"],"group":group,"n":g["n"],"edge_count":len(edges),"query_count":len(Q),
                    "hashes_match":all(hashes.values()),"simple_sorted_graph":simple,"query_replay_equal":query_replay,"query_membership_valid":query_membership,
                    "truth_statistics_recomputed_equal":stat_equal,"mean_degree":m["mean_degree"],"max_degree":m["max_degree"],
                    "min_community_size":min(m["community_sizes"]),"max_community_size":max(m["community_sizes"]),
                    "weighted_truth_conductance":m["weighted_truth_conductance"],"native_input_mu":row.get("native_mu"),
                    "target":row.get("target_weighted_conductance"),"native_printed_mean_mu":None,"native_printed_mu_sd":None,
                    "absolute_target_deviation":None,"native_bounds_met":None}
            if group=="lfr":
                raw=base/"attempts"/row["case_id"]/f"attempt_{row['selected_attempt']:02d}"
                match=re.search(r"average mixing parameter:\s*([0-9.eE+-]+)\s*\+/-\s*([0-9.eE+-]+)",(raw/"stdout.log").read_text())
                if match:record.update(native_printed_mean_mu=float(match.group(1)),native_printed_mu_sd=float(match.group(2)))
                lo,hi=cfg["lfr"]["community_bounds"][str(g["n"])]
                record["native_bounds_met"]=lo<=min(m["community_sizes"]) and max(m["community_sizes"])<=hi and m["max_degree"]<=cfg["lfr"]["max_degree"]
                record["absolute_target_deviation"]=abs(record["weighted_truth_conductance"]-record["target"])
            checks=[all(hashes.values()),simple,query_replay,query_membership,stat_equal]
            if not all(checks):failures.append({"case_id":row["case_id"],"record":record})
            rows.append(record)
    out=ROOT/"results/data_generation"
    with (out/"input_statistics.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    lfr=[r for r in rows if r["group"]=="lfr"]
    summary={"all_structural_hash_query_checks_pass":not failures,"failures":failures,"graph_counts":{"lfr":len(lfr),"sbm":len(rows)-len(lfr)},
             "query_count":sum(r["query_count"] for r in rows),"lfr_all_calibration_targets_reached":all(r["absolute_target_deviation"]<=cfg["lfr"]["tolerance"] for r in lfr),
             "lfr_max_absolute_target_deviation":max(r["absolute_target_deviation"] for r in lfr),"lfr_native_bound_violation_count":sum(not r["native_bounds_met"] for r in lfr),
             "config_sha256":sha(CONFIG),"catalog_sha256":{group:sha(ROOT/path/"catalog.json") for group,path in [("sbm","data/dev/sbm_v12"),("lfr","data/test/calibrated_lfr")]}}
    write_json(out/"input_audit.json",summary)
    print(json.dumps(summary),flush=True)
if __name__=="__main__":main()
