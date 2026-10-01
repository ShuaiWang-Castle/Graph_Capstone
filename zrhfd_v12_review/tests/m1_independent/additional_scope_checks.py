"""Explicit numerical domains for unit small-edge equality and SBM M′."""
from fractions import Fraction as F
from pathlib import Path
import argparse
import hashlib
import json
import platform
import time
from exact_claim_checks import Graph, Hypergraph, enc


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--check-existing",action="store_true");args=parser.parse_args()
    start=time.perf_counter();unit_cases=[]
    for n,edges in [(2,[((0,1),1,[0,1,0])]),(3,[((0,1,2),1,[0,1,1,0])]),(3,[((0,1),F(1,2),[0,1,0]),((0,1,2),F(3,2),[0,1,1,0])])]:
        h=Hypergraph(n,edges,f"unit_small_edges_n{n}")
        values=[]
        for j in range(41):
            v=h.M*F(j,40);actual=h.G(v);expected=v*v/h.M
            values.append({"v":v,"actual":actual,"expected":expected,"passes":actual==expected})
        unit_cases.append({"graph":h.description(),"values":values})
    K,s,p,q=4,2,F(1,8),F(1,4);delta=(s-1)*p+(K-1)*s*q
    g=Graph(K*s,[(u,v,p if u//s==v//s else q) for u in range(K*s) for v in range(u+1,K*s)],"M_prime_outside_separation")
    C,T=3,7;b=1;actual=g.z[T]-g.z[C];bound=(F(1,K*s)-q/delta)*b
    result={"schema_version":1,"scope":"Numerical scope checks only. Unit small-edge reduction is scoped to w=1 for every nontrivial split; M′ adversarial case is explicitly outside P8 separation.","claims":{"T-b-small-edge-equality-unit-scope":{"checks":123,"violations":sum(not v["passes"] for case in unit_cases for v in case["values"]),"status":"PASS_SCOPED"},"M-prime-without-inherited-domain":{"checks":1,"violations":int(actual<bound),"status":"FAIL_IF_STATED_FOR_ARBITRARY_P_Q","admissibility":"Theoretical domain judgment required; passing P8-separation regime results remain separate."}},"unit_cases":unit_cases,"M_prime_case":{"n":8,"K":K,"s":s,"p":p,"q":q,"delta":delta,"C":[0,1],"T":[0,1,2],"b":b,"Z_C":g.z[C],"Z_T":g.z[T],"difference":actual,"claimed_bound":bound,"bound_minus_difference":bound-actual,"P8_separation_satisfied":(s-1)*p>s*q,"graph":g.description()},"metadata":{"elapsed_seconds":time.perf_counter()-start,"python":platform.python_version(),"platform":platform.platform(),"source_SHA256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    root=Path(__file__).resolve().parents[2];output=args.output or root/"results"/"m1_independent"/"additional_scope_checks.json"
    if output.exists():
        if args.check_existing:
            previous=json.loads(output.read_text());assert previous["claims"]==enc(result["claims"]) and previous["M_prime_case"]==enc(result["M_prime_case"]);print(json.dumps({"check_existing":"PASS","elapsed_seconds":time.perf_counter()-start}));return
        raise RuntimeError("Immutable raw output exists; use --check-existing or fresh --output")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(enc(result),indent=2)+"\n")
    print(json.dumps(enc(result["claims"]),indent=2))


if __name__=="__main__":main()
