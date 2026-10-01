"""Tiny stdlib mode/storage checks; helper is mocked, no actual run is read."""
import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inv
from summarize import summarize


def main():
    checks = []
    def check(name, predicate):
        checks.append({"name":name,"passed":bool(predicate)})
    def rejects(name, function):
        try: function()
        except (ValueError, RuntimeError): check(name,True)
        else: check(name,False)
    original = {"cohort_origin":"ORIGINAL_FROZEN_COHORT","manifest":{"manifest_sha256":inv.OFFICIAL_BYTES_SHA,"frozen_sha256":inv.OFFICIAL_SEMANTIC_SHA},"integrity_status":"PASS"}
    check("original strict mode",inv.validate_analysis_cohort(original) is None)
    wrong = copy.deepcopy(original); wrong["manifest"]["manifest_sha256"]="wrong"
    rejects("wrong original manifest",lambda: inv.validate_analysis_cohort(wrong))
    rejects("unpaired fresh flag",lambda: inv.checked_reference_binding(inv.ROOT / "results/m5/reproduction",True,None))
    rejects("binding without fresh flag",lambda: inv.checked_reference_binding(inv.ROOT / "results/m5/reproduction",False,Path("fixture")))
    binding = {"status":"PASS","cohort_origin":"FRESH_REPRODUCTION","binding_receipt_sha256":"binding",
               "reference":{"manifest_sha256":inv.OFFICIAL_BYTES_SHA,"frozen_sha256":inv.OFFICIAL_SEMANTIC_SHA},
               "fresh":{"manifest_sha256":"fresh","frozen_sha256":"semantic"}}
    fresh = {"cohort_origin":"FRESH_REPRODUCTION","run":"results/m5/reproduction","reference_binding_sha256":"binding",
             "manifest":{"manifest_sha256":"fresh","frozen_sha256":"semantic"},"integrity_status":"PASS"}
    fake_path=inv.ROOT / "work/reproduction/artificial_binding.json"
    with patch("experiments.reproduction.cohort_binding.verify_reference_binding",return_value=binding) as mocked:
        check("fresh explicitly reference bound",inv.validate_analysis_cohort(fresh,True,fake_path)==binding)
        check("helper sees exact run and metadata scope",mocked.call_args.kwargs=={"run_path":inv.ROOT / "results/m5/reproduction","verify_files":False})
        rejects("fresh cannot enter original mode",lambda: inv.validate_analysis_cohort(fresh))
        wrong=copy.deepcopy(fresh); wrong["reference_binding_sha256"]="old"
        rejects("binding receipt copied from another run",lambda: inv.validate_analysis_cohort(wrong,True,fake_path))
        wrong=copy.deepcopy(fresh); wrong["manifest"]["frozen_sha256"]="old"
        rejects("fresh semantic mismatch",lambda: inv.validate_analysis_cohort(wrong,True,fake_path))
        result=summarize(fresh,[],False,True,fake_path)
        check("empty fresh summary retains origin NOT_RUN",result["cohort_origin"]=="FRESH_REPRODUCTION" and result["status"]=="NOT_RUN" and result["reference_binding_sha256"]=="binding")
        rejects("fresh cannot write original inventory",lambda: inv.write_inventory(inv.ROOT / "results/m5_analysis/official_v12_001",fresh,[],[]))
    bad_binding=copy.deepcopy(binding); bad_binding["reference"]["manifest_sha256"]="arbitrary"
    with patch("experiments.reproduction.cohort_binding.verify_reference_binding",return_value=bad_binding):
        rejects("arbitrary reference cannot authorize fresh",lambda: inv.validate_analysis_cohort(fresh,True,fake_path))
    rejects("fresh flags cannot relabel original",lambda: inv.validate_analysis_cohort(original,True,fake_path))
    current=inv.storage_scope(verify_sources=True)
    check("canonical pointer receipt source scope",not current["historical_fixture_only"] and current["current_sources_verified"])
    check("current storage measurement boundary unchanged",set(current["source_sha256"])=={"experiments/archival.py","experiments/run_m5_archived.py"})
    old=inv.storage_scope(historical_receipt="provenance/storage_wrapper_v001/receipt.json")
    check("historical v001 fixture scope remains separate",old["historical_fixture_only"] and not old["current_sources_verified"] and old["source_sha256"] != current["source_sha256"])
    # Only tiny pointer/receipt structures are mocked; no archive is opened.
    with patch.object(inv,"read_json",return_value={"receipt":"provenance/storage_wrapper_v004/receipt.json","receipt_sha256":"wrong"}), patch.object(inv,"digest",return_value="actual"):
        rejects("pointer receipt SHA mismatch",lambda: inv.storage_scope())
    check("no numerical or drawing import",not any(name in sys.modules for name in ("numpy","scipy","numba","matplotlib")))
    result={"status":"PASS" if all(c["passed"] for c in checks) else "FAIL","checks":checks,
            "fixture_only":True,"helper_relation_tested_separately":True,"actual_results_read":False,
            "source_sha256":{str(p.relative_to(inv.ROOT)):inv.digest(p) for p in sorted((inv.ROOT / "experiments/m5_analysis").glob("*.py"))},
            "current_storage_scope":current}
    (inv.ROOT / "reviews/m5_analysis/reproduced_contract_receipt.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"checks":len(checks),"failed":[c["name"] for c in checks if not c["passed"]]}))
    return 0 if result["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
