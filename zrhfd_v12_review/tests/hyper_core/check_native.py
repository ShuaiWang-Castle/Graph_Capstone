"""Author finite-iteration scores against frozen small convex reference."""
from pathlib import Path
import hashlib
import json
import sys
import time
import numpy as np
from scipy.optimize import linprog
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.hyper import Hypergraph,solve_hypergraph
from zrhfd.baselines.hfd import solve_hyper


def objective(h,x,seed,mass,sigma):
    fe=[float(max(x[list(e)])-min(x[list(e)])) for e,theta,w in h.edges];source=np.zeros(h.n);source[seed]=mass
    return .5*sum(float(theta)*f*f for (e,theta,w),f in zip(h.edges,fe))+.5*sigma*float(h.degree@(x*x))-float((source-h.degree)@x)


def kkt(h,x,seed,mass,sigma):
    columns=[];owners=[];f=[]
    for k,(e,theta,w) in enumerate(h.edges):
        xe=x[list(e)];hi=float(max(xe));lo=float(min(xe));tol=1e-8*max(1,hi);f.append(float(theta)*(hi-lo))
        for u in e:
            for v in e:
                if u!=v and x[u]>=hi-tol and x[v]<=lo+tol:
                    c=np.zeros(h.n);c[u]=1;c[v]=-1;columns.append(c);owners.append(k)
        if not any(owner==k for owner in owners):
            columns.append(np.zeros(h.n));owners.append(k)
    B=np.array(columns).T;count=B.shape[1];eq=np.zeros((len(h.edges),count+1))
    for i,k in enumerate(owners):eq[k,i]=1
    baseline=sigma*h.degree*x+h.degree;baseline[seed]-=mass;rows=[];bounds=[]
    for u in range(h.n):
        row=np.r_[B[u],-1.];rows.append(-np.r_[B[u],1.]);bounds.append(baseline[u])
        if x[u]>1e-7*max(1,float(x.max())):rows.append(row);bounds.append(-baseline[u])
    c=np.zeros(count+1);c[-1]=1
    solution=linprog(c,A_ub=np.array(rows),b_ub=np.array(bounds),A_eq=eq,b_eq=np.array(f),bounds=[(0,None)]*(count+1),method='highs')
    return {'subgradient_stationarity_Linf':float(solution.fun) if solution.success else None,'linprog_success':bool(solution.success),'scaled_subgradient_stationarity':float(solution.fun)/max(1,mass) if solution.success else None}


def main():
    start=time.perf_counter();h=Hypergraph.from_edges(5,[(0,1),(1,2),(2,3),(3,4),(0,1,2),(1,2,3),(2,3,4)]);raw=[];sigma=1e-4
    for mass in [3*h.degree[0],h.total]:
        reference,refmeta=solve_hypergraph(h,0,mass,sigma,tolerance=1e-12)
        for iterations in [50,200]:
            x,telemetry=solve_hyper(h,0,mass,sigma=sigma,iterations=iterations,budget_seconds=180,artifact_directory='reviews/m5_core/native_logs')
            if telemetry['status']!='COMPLETED':raw.append({'mass':mass,'iterations':iterations,'status':telemetry['status'],'telemetry':telemetry});continue
            x=np.asarray(x);U=np.flatnonzero(x>1e-7*max(1,float(x.max())));Us=set(map(int,U));rhs=sum(float(theta)*(float(max(x[list(e)])-min(x[list(e)])))*(1 if 0<len(Us.intersection(e))<len(e) else 0) for e,theta,w in h.edges)+sigma*float(h.degree@x);residual=mass-float(h.volume(U))-rhs;value=objective(h,x,0,mass,sigma);optimal=objective(h,np.asarray(reference),0,mass,sigma)
            raw.append({'mass':mass,'iterations':iterations,'maximum_x_difference':float(np.max(np.abs(x-reference))),'frozen_objective':value,'reference_objective':optimal,'objective_gap':value-optimal,'scaled_mass_balance_residual':abs(residual)/max(1,mass),'KKT':kkt(h,x,0,mass,sigma),'scores':x.tolist(),'reference_scores':reference.tolist(),'telemetry':telemetry,'status':'APPROXIMATE_AUTHOR_ITERATE_ONLY'})
            print(mass,iterations,'gap',value-optimal,flush=True)
    result={'schema_version':1,'scope':'Small native unit HFD p=2 scores, actual author final excess/degree/sigma; fixed iterations compared with frozen quadratic CVXPY minimizer; no timing or convergence claim','raw':raw,'metadata':{'elapsed_seconds':time.perf_counter()-start,'timing_claim':False,'source_SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
    p=PROJECT/'results/m5_core/native_small_checks.json';p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():raise RuntimeError('Preserve immutable raw output')
    p.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
