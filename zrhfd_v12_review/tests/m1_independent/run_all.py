"""Single CPU reproduction entry point; preserve raw results and review fail state."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--check-existing",action="store_true",help="Recompute and compare existing raw results without replacing them")
    parser.add_argument("--skip-core",action="store_true")
    args=parser.parse_args();directory=Path(__file__).resolve().parent;project=directory.parents[1];start=time.perf_counter()
    scripts=[("quick_scope_checks.py","scope_counterexamples.json"),("exact_claim_checks.py","exact_claim_checks.json"),("all_order_checks.py","all_order_checks.json"),("hyper_diffusion_checks.py","hyper_diffusion_checks.json"),("additional_scope_checks.py","additional_scope_checks.json")]
    if not args.skip_core:scripts.append(("core_cross_checks.py","core_cross_checks_corrected_fixture.json"))
    runs=[]
    for script,output in scripts:
        command=[sys.executable,str(directory/script)]
        if args.check_existing:command.append("--check-existing")
        result=subprocess.run(command,check=False)
        runs.append({"script":script,"raw":f"results/m1_independent/{output}","reproduction_exit_code":result.returncode})
        if result.returncode:print(f"Reproduction error in {script}");return result.returncode
    summaries={}
    for run in runs:
        result=json.loads((project/run["raw"]).read_text());summaries[run["script"]]={k:{key:claim[key] for key in ["checks","violations","status"] if key in claim} for k,claim in result["claims"].items()}
    summary={"schema_version":1,"reproduction_status":"PASS","M1_literal_frozen_gate":"FAIL","reason":"Exact T-b small-edge counterexamples and literal V(c) empty-support counterexamples; unspecified concavity and M′ domain need theoretical judgment.","unaffected_tested_graph_and_unit_hypergraph_checks":"PASS_WITH_STATED_FINITE_NUMERICAL_SCOPE","run_all_elapsed_seconds":time.perf_counter()-start,"runs":runs,"claim_counts":summaries,"raw_measurements_immutable":True}
    review=project/"reviews"/"m1_independent"/"status.json";review.parent.mkdir(parents=True,exist_ok=True);review.write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({"reproduction_status":summary["reproduction_status"],"M1_literal_frozen_gate":summary["M1_literal_frozen_gate"],"review":"reviews/m1_independent/status.json"}))
    # Exit code denotes ability to reproduce recorded evidence, not theory acceptance.
    # The explicit frozen M1 FAIL remains in the derived status artifact above.
    return 0


if __name__=="__main__":raise SystemExit(main())
