"""Audit every frozen scale input and query, without clustering quality."""
import json
from pathlib import Path
import sys
import numpy as np
from scale_storage import sha

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from zrhfd.storage import load_csr

def main():
    cfg=json.loads((ROOT/"experiments/data_generation/scale_config.json").read_text());catalog=json.loads((ROOT/"data/scale/catalog.json").read_text());rows=[]
    for r in catalog["cases"]:
        if "csr_path" not in r:
            rows.append({"case_id":r["case_id"],"status":r["status"],"input_available":False});continue
        path=ROOT/r["csr_path"];meta=json.loads((path/"csr_metadata.json").read_text());g=load_csr(path,verify_hashes=True)
        truth=json.loads((ROOT/r["truth_path"]).read_text())["communities"];Q=json.loads((ROOT/r["queries_path"]).read_text())["queries"]
        rng=np.random.default_rng(cfg["query_rng_seed"]);ids=rng.choice(len(truth),min(6,len(truth)),replace=False)
        replay=[{"community_index":int(ci),"seed":int(s)} for ci in ids for s in rng.choice(truth[int(ci)],min(2,len(truth[int(ci)])),replace=False)]
        checks={"csr_metadata_hash":sha(path/"csr_metadata.json")==r["csr_metadata_sha256"],"truth_hash":sha(ROOT/r["truth_path"])==r["truth_sha256"],
                "queries_hash":sha(ROOT/r["queries_path"])==r["queries_sha256"],"queries_replay":Q==replay,
                "query_membership":all(q["seed"] in truth[q["community_index"]] for q in Q),
                "degree_matches_offsets":np.array_equal(g.degree,np.diff(g.indptr)),"weights_all_one":bool(np.all(g.weights==1)),
                "total_integer_exact":g.total==int(g.degree.sum()),"producer_sparse_structure_passed":meta["structural_violations"]==0,
                "row_statistics_match":r["statistics"]==meta["statistics"],"readonly":all(not a.flags.writeable for a in [g.indptr,g.indices,g.weights,g.degree])}
        raw=ROOT/"data/scale"/r["case_id"]/"attempts"/f"attempt_{r['selected_attempt']:02d}"
        checks["raw_network_hash"]=sha(raw/"network.dat")==meta["source_network_sha256"]
        checks["raw_community_hash"]=sha(raw/"community.dat")==meta["source_community_sha256"]
        rows.append({"case_id":r["case_id"],"n":g.n,"status":r["status"],"checks":{k:bool(v) for k,v in checks.items()},"all_checks_pass":all(checks.values())})
        print(json.dumps({"case_id":r["case_id"],"all_checks_pass":all(checks.values())}),flush=True)
    result={"expected_input_count":9,"input_count":sum(r.get("all_checks_pass",False) for r in rows),"all_available_inputs_pass":all(r.get("all_checks_pass",False) for r in rows),
            "all_nine_completed":len(rows)==9,"rows":rows,"catalog_sha256":sha(ROOT/"data/scale/catalog.json"),"config_sha256":sha(ROOT/"experiments/data_generation/scale_config.json")}
    (ROOT/"results/data_generation/scale_input_audit.json").write_text(json.dumps(result,indent=1))
    manifest={}
    for r in catalog["cases"]:
        if "csr_path" not in r:continue
        path=ROOT/r["csr_path"];meta=json.loads((path/"csr_metadata.json").read_text())
        manifest.update({(path/fname).relative_to(ROOT).as_posix():meta["sha256"][name] for name,fname in meta["files"].items()})
        for field in ["truth_path","queries_path"]:manifest[r[field]]=r[field.replace("_path","_sha256")]
        manifest[(path/"csr_metadata.json").relative_to(ROOT).as_posix()]=r["csr_metadata_sha256"]
        for record in r["attempt_records"]:manifest[record]=sha(ROOT/record)
    manifest["data/scale/catalog.json"]=result["catalog_sha256"]
    (ROOT/"results/data_generation/scale_checksums.json").write_text(json.dumps(manifest,indent=1))
if __name__=="__main__":main()
