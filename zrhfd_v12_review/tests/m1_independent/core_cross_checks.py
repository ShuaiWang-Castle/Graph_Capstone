"""Independent brute-force engineering checks of root-owned ordinary-graph core."""
from fractions import Fraction as F
from pathlib import Path
import argparse
import hashlib
import json
import platform
import random
import sys
import time
import numpy as np
from exact_claim_checks import Claims, Graph as ExactGraph, enc, graph_diffusion, lower_hull

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT))
from zrhfd.graph import Graph
from zrhfd.mincut import cut_with_unary, mm_refine
from zrhfd.certificate import regional_certificate
from zrhfd.sweep import level_sweep, capped_region
from zrhfd.diffusion import solve_graph


def mask(vertices): return sum(1 << int(u) for u in vertices)
def vertices(S,n): return [u for u in range(n) if S >> u & 1]
def subsets(R,seed):
    S=R
    while S:
        if S >> seed & 1:yield S
        S=(S-1)&R


def mm_oracle(g,S,R,seed,score):
    order=sorted(vertices(R,g.n),key=lambda u:(0 if u==seed else (1 if S >> u & 1 else 2),-score[u],u))
    D=F(0); unary={}
    for u in order:
        previous=D;D+=g.d[u];unary[u]=(D*D-previous*previous)/g.M-g.z[S]*g.d[u]
    vals={T:g.cut[T]+sum((unary[u] for u in vertices(T,g.n)),F(0)) for T in subsets(R,seed)}
    return order,vals


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--check-existing",action="store_true");args=parser.parse_args()
    begin=time.perf_counter();rng=random.Random(930817);claims=Claims();records=[]
    inputs=[(2,[(0,1,1)],"edge"),(3,[(0,1,1),(1,2,1)],"path3"),(5,[(0,1,2),(1,2,1),(2,3,2),(3,4,1),(0,4,1),(1,3,1)],"weighted5"),(6,[(0,1,1),(1,2,1),(2,0,1),(3,4,1),(4,5,1),(5,3,1)],"two_triangles")]
    for n in [8,14]:
        edges=[(u,u+1,rng.randrange(1,4)) for u in range(n-1)]
        edges += [(u,v,rng.randrange(1,4)) for u in range(n) for v in range(u+2,n) if rng.random()<.17]
        inputs.append((n,edges,f"random_integer_n{n}"))
    for n,edges,name in inputs:
        core=Graph.from_edges(n,edges);oracle=ExactGraph(n,edges,name);item={"graph":oracle.description(),"cuts":[],"MM":[],"certificates":[],"diffusion":[]}
        for S in range(1,1 << n):
            stat=core.stats(vertices(S,n))
            claims.check("core-volume",F(stat["volume"])==oracle.vol[S],{"graph":name,"S":S})
            claims.check("core-cut",F(stat["cut"])==oracle.cut[S],{"graph":name,"S":S})
            claims.check("core-Z",F(stat["Z_exact"])==oracle.z[S],{"graph":name,"S":S})
        for seed in sorted(set([0,n-1])):
            regions=sorted(set([oracle.full,(1 << seed)|mask(core.indices[core.indptr[seed]:core.indptr[seed+1]]),(1 << seed)|(1 << ((seed+1)%n))]))
            for R in regions:
                Rv=vertices(R,n);candidates=list(subsets(R,seed))
                for rep in range(8):
                    denom=(1 << 80)+7 if rep==0 else rng.randrange(1,18)
                    unary={u:F(rng.randrange(-20,21),denom) for u in Rv}
                    # Large rational denominator alone exceeds int64 capacities.
                    # Keep its product with unary below the documented int128 limit.
                    if rep==0:unary[seed]+=F(1)
                    vals={S:oracle.cut[S]+sum((unary[u] for u in vertices(S,n)),F(0)) for S in candidates};minimum=min(vals.values())
                    try:
                        selected,value,telemetry=cut_with_unary(core,Rv,seed,unary);S=mask(selected)
                    except Exception as e:
                        claims.check("core-mincut-exception",False,{"graph":name,"seed":seed,"R":R,"unary":unary,"exception":repr(e)});continue
                    ctx={"graph":name,"seed":seed,"R":R,"unary":unary,"selected":S,"returned":value,"expected":minimum}
                    claims.check("core-mincut-optimum",value==minimum,ctx)
                    claims.check("core-mincut-full-boundary",vals[S]==value,ctx)
                    claims.check("core-mincut-seed-region",bool(S >> seed & 1) and S & ~R == 0,ctx)
                    item["cuts"].append({**ctx,"telemetry":telemetry})
                # Exact all-subset lower hull coordinates; collinear interiors excluded.
                expected=lower_hull([(oracle.vol[S],oracle.cut[S],S) for S in candidates]);expected_coordinates=[(v,c) for v,c,S in expected]
                try:
                    cert=regional_certificate(core,seed,Rv)
                    coords=[(F(p["volume"]),F(p["cut"])) for p in cert["hull_vertices"]]
                    claims.check("core-hull-vertices",coords==expected_coordinates,{"graph":name,"seed":seed,"R":R,"actual":coords,"expected":expected_coordinates})
                    optimum=min(oracle.z[S] for S in candidates);hbest=min(oracle.z[S] for _,_,S in expected)
                    claims.check("core-LB-range",cert["LB_R"]<=float(optimum)+1e-12 and optimum<=F(cert["hull_best_Z_exact"]),{"graph":name,"seed":seed,"R":R,"certificate":cert,"optimum":optimum})
                    claims.check("core-hull-best",F(cert["hull_best_Z_exact"])==hbest)
                    bound=max(((b[0]-a[0])**2/(4*oracle.M*a[0]) for a,b in zip(expected,expected[1:])),default=F(0))
                    claims.check("core-hull-width",F(cert["gap_bound_exact"])==bound)
                    claims.check("core-LB-T-c-prime",cert["LB_R"]+1e-12>=float(hbest-bound))
                    item["certificates"].append({"seed":seed,"R":R,"certificate":cert,"exact_optimum":optimum})
                except Exception as e:claims.check("core-certificate-exception",False,{"graph":name,"seed":seed,"R":R,"exception":repr(e)})
                score=np.array([float(u%3) for u in range(n)]) # Seed may have a lower score than others.
                for initial in sorted(set([1 << seed,R,candidates[len(candidates)//2]])):
                    try:
                        selected,trace=mm_refine(core,seed,Rv,vertices(initial,n),score)
                    except Exception as e:
                        claims.check("core-MM-exception",False,{"graph":name,"seed":seed,"R":R,"initial":initial,"exception":repr(e)});continue
                    previous=initial
                    for row in trace:
                        expected_order,vals=mm_oracle(oracle,previous,R,seed,score)
                        T=mask(row["vertices"]);val=F(row["mincut_objective_exact"])
                        ctx={"graph":name,"seed":seed,"R":R,"previous":previous,"row":row,"expected_order":expected_order}
                        claims.check("core-MM-order",row["order"]==expected_order,ctx)
                        claims.check("core-MM-optimum",val==min(vals.values()) and vals[T]==val,ctx)
                        claims.check("core-MM-acceptance",row["accepted"]==(oracle.z[T]<oracle.z[previous]),ctx)
                        if row["accepted"]:previous=T
                    claims.check("core-MM-final",mask(selected)==previous and F(trace[-1]["mincut_objective_exact"])==0,{"graph":name,"seed":seed,"R":R,"selected":selected,"trace":trace})
                    item["MM"].append({"seed":seed,"R":R,"initial":initial,"final":mask(selected),"trace":trace})
        # Positive tied score levels: enumerate complete blocks independently.
        seed=0;score=np.array([float(max(0,3-u//2)) for u in range(n)])
        for objective in ["Z","phi"]:
            levels=[mask(np.flatnonzero(score>=t)) for t in sorted(set(score),reverse=True) if t>0]
            values=[(S,oracle.z[S] if objective=="Z" else oracle.phi(S)) for S in levels]
            values=[(S,v) for S,v in values if v is not None]
            if not values:
                try:level_sweep(core,score,seed,objective)
                except ValueError:claims.check("core-sweep-no-admissible-level-rejected",True)
                else:claims.check("core-sweep-no-admissible-level-rejected",False,{"graph":name,"objective":objective})
                continue
            try:
                selected,value,blocks=level_sweep(core,score,seed,objective)
                best=min(v for S,v in values);claims.check("core-sweep-value",value==best,{"graph":name,"objective":objective,"selected":selected,"actual":value,"expected":best})
                claims.check("core-sweep-ties",mask(selected) in [S for S,v in values if v==best],{"graph":name,"objective":objective,"selected":selected,"levels":levels})
            except Exception as e:claims.check("core-sweep-exception",False,{"graph":name,"objective":objective,"exception":repr(e)})
        S0=1
        for theta in [F(1,4),F(1,2),F(1)]:
            levels=[mask(np.flatnonzero(score>=t)) for t in sorted(set(score),reverse=True) if t>0];levels=[0]+[L for L in levels if oracle.vol[L & ~S0]<=theta*oracle.vol[S0]]
            expected=S0|max(levels,key=lambda L:oracle.vol[L])
            result=mask(capped_region(core,[0],score,theta))
            claims.check("core-cap-ties",result==expected,{"graph":name,"theta":theta,"actual":result,"expected":expected})
        for m in sorted(set([3*oracle.d[0],oracle.M/2,oracle.M])):
            xexact,_=graph_diffusion(oracle,m);x,telemetry=solve_graph(core,0,float(m),tolerance=1e-13,max_updates=3000000)
            difference=max(abs(float(a)-b) for a,b in zip(xexact,x));tol=1e-8*max(1,max(map(float,xexact)))
            claims.check("core-diffusion-agreement",difference<=tol,{"graph":name,"mass":m,"difference":difference,"tolerance":tol,"telemetry":telemetry})
            claims.check("core-diffusion-KKT",telemetry["scaled_kkt_residual"]<=1e-8,{"graph":name,"mass":m,"telemetry":telemetry})
            item["diffusion"].append({"m":m,"maximum_absolute_error":difference,"telemetry":telemetry})
        records.append(item);print(name,"complete",flush=True)
    # Independent direct 128-bit test on a tiny graph, avoiding denominator overflow.
    graph=Graph.from_edges(2,[(0,1)])
    huge=F(1 << 120);selected,value,meta=cut_with_unary(graph,[0,1],0,{0:huge,1:F(0)})
    claims.check("core-capacity-above-int64",value==huge and int(meta["flow_integer"])>(1 << 63),{"selected":selected,"value":value,"telemetry":meta})
    try:cut_with_unary(graph,[0,1],0,{0:F(1 << 124),1:F(0)})
    except OverflowError:claims.check("core-capacity-overflow-rejected",True)
    else:claims.check("core-capacity-overflow-rejected",False)
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (PROJECT/"zrhfd").glob("*.py")}
    result={"schema_version":1,"scope":"Engineering core only. Independent exact all-subset oracle, integer graph topology; Fraction unaries, 128-bit capacities, complete score-tie blocks, full-graph boundaries, exact lower hull, float LB and diffusion comparisons.","fixture_history":{"initial_raw":"core_cross_checks.json","reason":"Initial test mixed a 2^80 denominator and a 2^110 unary, exceeding supported capacity. It also treated no valid phi level on a fully tied single edge as a failure. Both correct rejections were fixture errors; initial raw preserved. Only fixtures were corrected; core unchanged."},"claims":claims.data,"raw":records,"metadata":{"elapsed_seconds":time.perf_counter()-begin,"python":platform.python_version(),"platform":platform.platform(),"source_SHA256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"core_source_SHA256":source_hashes}}
    output=args.output or PROJECT/"results"/"m1_independent"/"core_cross_checks_corrected_fixture.json"
    if output.exists():
        if args.check_existing:
            old=json.loads(output.read_text());assert {k:(v["checks"],v["violations"]) for k,v in old["claims"].items()}=={k:(v["checks"],v["violations"]) for k,v in result["claims"].items()}
            print(json.dumps({"check_existing":"PASS","elapsed_seconds":time.perf_counter()-begin}));return
        raise RuntimeError("Immutable raw output exists; use --check-existing or fresh --output")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(enc(result),indent=2)+"\n")
    print(json.dumps({k:{"checks":v["checks"],"violations":v["violations"]} for k,v in claims.data.items()},indent=2))


if __name__=="__main__":main()
