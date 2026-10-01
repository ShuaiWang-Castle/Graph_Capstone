"""Enumerate all S-first, seed-first internal orders on finite n<=6 graphs."""
from fractions import Fraction as F
from itertools import permutations
from pathlib import Path
import argparse
import hashlib
import json
import platform
import time
from exact_claim_checks import Claims, Graph, enc, mm_values, penalty


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--check-existing",action="store_true");args=parser.parse_args()
    start=time.perf_counter();claims=Claims();records=[]
    graphs=[Graph(3,[(0,1,1),(1,2,1)],"path3"),Graph(4,[(u,v,1) for u in range(4) for v in range(u+1,4)],"K4"),Graph(5,[(0,1,2),(1,2,1),(2,3,2),(3,4,1),(4,0,1),(1,3,1)],"weighted5"),Graph(6,[(0,1,1),(1,2,1),(2,0,1),(3,4,1),(4,5,1),(5,3,1)],"two_triangles")]
    for g in graphs:
        qualifying=[]
        for C in g.seeded:
            if all(T==C or g.z[T]-g.z[C]>penalty(g,T,C,g.full) for T in g.seeded):qualifying.append(C)
        fixed=[];order_count=0
        for S in g.seeded:
            left=[v for v in range(1,g.n) if S >> v & 1];right=[v for v in range(1,g.n) if not S >> v & 1]
            for l in permutations(left):
                for r in permutations(right):
                    order=[0]+list(l)+list(r);order_count+=1;_,vals=mm_values(g,S,g.full,order)
                    best=min(vals.values());claims.check("P5-all-orders-zero",vals[S]==0)
                    for T,val in vals.items():claims.check("P5-all-orders-negative",val>=0 or g.z[T]<g.z[S],{"graph":g.name,"S":S,"T":T,"order":order})
                    if best!=0:continue
                    fixed.append({"S":S,"order":order})
                    for C in qualifying:claims.check("MM-exact-all-orders",S==C,{"graph":g.name,"S":S,"C":C,"order":order})
                    for C in g.seeded:
                        prefix=0;num=F(0)
                        for v in order:
                            prefix|=1 << v
                            if C >> v & 1:num+=2*g.d[v]*g.vol[prefix & ~C]
                        bound=num/(g.M*g.vol[C]);pen=penalty(g,S,C,g.full)
                        claims.check("FP-all-orders-first",g.z[S]-g.z[C]<=bound,{"graph":g.name,"S":S,"C":C,"order":order})
                        claims.check("FP-all-orders-second",bound<=pen,{"graph":g.name,"S":S,"C":C,"order":order})
                        claims.check("FP-all-orders-third",pen<=2*g.vol[g.full & ~C]/g.M)
        records.append({"graph":g.description(),"order_count":order_count,"fixedpoints_with_orders":fixed,"MM_exact_qualifying":qualifying})
    result={"schema_version":1,"scope":"Every seeded subset, every compatible S-first seed-first ordering, and every candidate C′/T on four finite n<=6 graphs","claims":claims.data,"raw":records,"metadata":{"elapsed_seconds":time.perf_counter()-start,"python":platform.python_version(),"platform":platform.platform(),"source_SHA256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    root=Path(__file__).resolve().parents[2];output=args.output or root/"results"/"m1_independent"/"all_order_checks.json"
    if output.exists():
        if args.check_existing:
            previous=json.loads(output.read_text());assert previous["claims"]==enc(result["claims"]);print(json.dumps({"check_existing":"PASS","elapsed_seconds":time.perf_counter()-start}));return
        raise RuntimeError("Immutable raw output exists; use --check-existing or fresh --output")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(enc(result),indent=2)+"\n")
    print(json.dumps({k:{"checks":v["checks"],"violations":v["violations"]} for k,v in claims.data.items()},indent=2))


if __name__=="__main__":main()
