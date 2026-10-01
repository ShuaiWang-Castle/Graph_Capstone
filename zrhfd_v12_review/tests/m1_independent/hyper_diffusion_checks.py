"""Independent CPU CVXPY checks; exact permutation epigraph, numeric solves.

This does not redefine frozen claims and does not equate small residuals to proof.
"""
from fractions import Fraction as F
from itertools import permutations
from pathlib import Path
import argparse
import hashlib
import json
import platform
import random
import time
import cvxpy as cp
import numpy as np
from exact_claim_checks import Claims, Hypergraph, enc, popcount


def prepare(h,sigma):
    rows=[]; owners=[]
    for k,(e,theta,w) in enumerate(h.hyperedges):
        slopes=[w[j+1]-w[j] for j in range(len(e))]
        assert all(slopes[j]>=slopes[j+1] for j in range(len(slopes)-1))
        seen=set()
        for perm in permutations(e):
            row=[F(0)]*h.n
            for v,a in zip(perm,slopes): row[v]=a
            tup=tuple(row)
            if tup in seen: continue
            seen.add(tup); rows.append(list(map(float,row)));owners.append(k)
    B=np.array(rows); owner=np.array(owners); d=np.array(list(map(float,h.d)))
    theta=np.array([float(t) for e,t,w in h.hyperedges]); x=cp.Variable(h.n); t=cp.Variable(len(h.hyperedges)); m=cp.Parameter(nonneg=True)
    source=np.zeros(h.n);source[0]=1
    positive=x>=0; tp=t>=0; epi=B@x<=t[owner]
    objective=.5*cp.sum(cp.multiply(theta,cp.square(t)))+.5*sigma*cp.sum(cp.multiply(d,cp.square(x)))-(m*source-d)@x
    problem=cp.Problem(cp.Minimize(objective),[positive,tp,epi])
    return problem,x,t,m,positive,tp,epi,B,owner,d,theta


def solve(h,prepared,m,sigma):
    problem,xvar,tvar,param,positive,tp,epi,B,owner,d,theta=prepared
    param.value=float(m); start=time.perf_counter()
    objective=problem.solve(solver="CLARABEL",tol_gap_abs=1e-12,tol_gap_rel=1e-12,tol_feas=1e-12,max_iter=500)
    x=np.maximum(xvar.value,0); t=np.maximum(tvar.value,0); nu=np.asarray(epi.dual_value)
    source=np.zeros(h.n);source[0]=float(m)
    rx=sigma*d*x-(source-d)+B.T@nu-np.asarray(positive.dual_value)
    rt=theta*t-np.bincount(owner,weights=nu,minlength=len(theta))-np.asarray(tp.dual_value)
    primal=max(0,float(np.max(B@x-t[owner])),float(np.max(-x)))
    stationarity=max(float(np.max(np.abs(rx))),float(np.max(np.abs(rt))))/max(1,float(m))
    complementary=max(float(np.max(np.abs(nu*(B@x-t[owner])))),float(np.max(np.abs(np.asarray(positive.dual_value)*x))),float(np.max(np.abs(np.asarray(tp.dual_value)*t))))/max(1,float(m))
    threshold=1e-7*max(1,float(x.max())); U=sum(1 << v for v in range(h.n) if x[v]>threshold)
    fe=[]
    for e,theta_e,w in h.hyperedges:
        xs=sorted((x[v] for v in e),reverse=True)
        fe.append(sum(float(w[j])*(xs[j-1]-xs[j]) for j in range(1,len(e))))
    rhs=sum(float(theta_e)*f*float(w[sum(U >> v & 1 for v in e)]) for (e,theta_e,w),f in zip(h.hyperedges,fe))+sigma*sum(float(h.d[v])*x[v] for v in range(h.n) if U >> v & 1)
    lhs=float(m-h.vol[U]); balance=abs(lhs-rhs)/max(1,float(m))
    return {"m":str(m),"x":x.tolist(),"support":U,"support_threshold":threshold,"objective":float(objective),"solver_status":problem.status,"elapsed_seconds":time.perf_counter()-start,"scaled_stationarity":stationarity,"scaled_complementarity":complementary,"primal_residual":primal,"mass_lhs":lhs,"mass_rhs":rhs,"scaled_mass_balance_residual":balance}


def connected(h,U):
    reached={0} if U else set(); stack=list(reached)
    while stack:
        u=stack.pop()
        for e,theta,w in h.hyperedges:
            if u in e:
                for v in e:
                    if U >> v & 1 and v not in reached: reached.add(v);stack.append(v)
    return len(reached)==popcount(U)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--check-existing",action="store_true");args=parser.parse_args()
    start=time.perf_counter(); rng=random.Random(930291);claims=Claims();raw=[];sigma=1e-4
    for kind in ["all_or_nothing","cardinality_min"]:
        for n in [5,8,14]:
            vertices=[(u,u+1) for u in range(n-1)]
            vertices += [tuple(sorted(rng.sample(range(n),rng.randrange(3,min(n,5)+1)))) for _ in range(n)]
            edges=[]
            for e in vertices:
                r=len(e);w=[0]+[1 if kind=="all_or_nothing" else min(j,r-j) for j in range(1,r)]+[0]
                edges.append((e,F(rng.randrange(1,5),2),w))
            h=Hypergraph(n,edges,f"random_{kind}_n{n}"); prepared=prepare(h,sigma); previous=None; records=[]
            masses=sorted(set([h.d[0]*F(11,10),2*h.d[0],3*h.d[0],4*h.d[0],8*h.d[0],h.M/2,h.M,2*h.M]))
            for m in masses:
                record=solve(h,prepared,m,sigma); x=record["x"];U=record["support"];scale=max(1,max(x));tol=2e-7*scale
                reliable=record["scaled_stationarity"]<1e-8 and record["scaled_complementarity"]<1e-8 and record["primal_residual"]<1e-8
                claims.check("hyper-solver-KKT",reliable,{"graph":h.name,**record})
                if reliable:
                    claims.check("V-a-hypergraph",x[0]>=max(x)-tol,{"graph":h.name,**record})
                    claims.check("V-b-hypergraph",connected(h,U),{"graph":h.name,**record})
                    claims.check("V-c-volume-hypergraph",float(h.vol[U])<=float(m)+1e-8*max(1,float(m)),{"graph":h.name,**record})
                    claims.check("V-c-balance-hypergraph",record["scaled_mass_balance_residual"]<2e-7,{"graph":h.name,**record})
                    claims.check("P7-region-volume-hypergraph",float(h.vol[U])<=float(m)+1e-8*max(1,float(m)))
                if previous:
                    differences=[a-b for a,b in zip(x,previous["x"])]; min_diff=min(differences)
                    name="Mono-all-or-nothing" if kind=="all_or_nothing" else "Mono-cardinality-observation"
                    claims.check(name,min_diff>=-tol,{"graph":h.name,"previous":previous,"current":record,"minimum_difference":min_diff,"tolerance":tol})
                previous=record;records.append(record)
            # Enumeration includes every seeded subset on this finite random hypergraph.
            raw.append({"graph":h.description(),"all_seeded_subsets_enumerated":len(h.seeded),"exact_best_Z":min(h.z[S] for S in h.seeded),"solves":records})
            print(h.name,"complete",flush=True)
    result={"schema_version":1,"scope":{"random_seed":930291,"sigma":sigma,"arithmetic":"Exact Fraction splitting, degree, objective enumeration; float64 high-accuracy CLARABEL diffusion with independent permutation epigraph KKT residuals","seeded_subset_enumeration":"Every seeded subset for each random n=5,8,14 hypergraph in each family","support_tolerance":"1e-7*max(1,max(x)); near-zero membership is numerical telemetry","cardinality_Mono":"Observational only; violations are not frozen gate failures","assertion_scope":"Numerical verification after residual <1e-8; no exact-solution or proof claim"},"claims":claims.data,"raw":raw,"metadata":{"elapsed_seconds":time.perf_counter()-start,"python":platform.python_version(),"platform":platform.platform(),"cvxpy":cp.__version__,"source_SHA256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    root=Path(__file__).resolve().parents[2]; output=args.output or root/"results"/"m1_independent"/"hyper_diffusion_checks.json"
    if output.exists():
        if args.check_existing:
            previous=json.loads(output.read_text());assert {k:(v["checks"],v["violations"]) for k,v in previous["claims"].items()}=={k:(v["checks"],v["violations"]) for k,v in result["claims"].items()}
            print(json.dumps({"check_existing":"PASS","elapsed_seconds":time.perf_counter()-start}));return
        raise RuntimeError("Immutable raw output exists; use --check-existing or fresh --output")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(enc(result),indent=2)+"\n")
    print(json.dumps({k:{"checks":v["checks"],"violations":v["violations"]} for k,v in claims.data.items()},indent=2))


if __name__=="__main__":main()
