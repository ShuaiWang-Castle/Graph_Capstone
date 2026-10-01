"""Exact integral seeded cuts, with explicit full-graph boundary penalties."""
from fractions import Fraction
from math import lcm
from pathlib import Path
import subprocess
import time

BINARY = Path(__file__).resolve().parents[1]/'work'/'bin'/'mincut128'


def cut_with_unary(graph, region, seed, unary):
    region = sorted(set(map(int,region)))
    if seed not in region: raise ValueError('Seed absent from region')
    local = {u:i for i,u in enumerate(region)}
    boundary = {u:0 for u in region}; inner=[]
    for u in region:
        lo,hi=graph.indptr[u:u+2]
        for j in range(lo,hi):
            v=int(graph.indices[j]);w=Fraction(str(float(graph.weights[j])))
            if v not in local: boundary[u]+=w
            elif u<v:inner.append((u,v,w))
    coefficients={u:Fraction(unary[u])+boundary[u] for u in region}
    denominator=1
    for c in coefficients.values():denominator=lcm(denominator,c.denominator)
    for _,_,w in inner:denominator=lcm(denominator,w.denominator)
    source,sink=len(region),len(region)+1
    arcs=[];constant=0
    for u,c in coefficients.items():
        integer=int(c*denominator)
        if integer>=0:arcs.append((local[u],sink,integer))
        else:arcs.append((source,local[u],-integer));constant+=integer
    for u,v,w in inner:
        integer=int(w*denominator)
        arcs.extend([(local[u],local[v],integer),(local[v],local[u],integer)])
    force=sum(c for _,_,c in arcs)+1
    arcs.append((source,local[seed],force))
    if force>=(1<<124):raise OverflowError('Exact cut exceeds 128-bit engineering backend; no floating fallback')
    text=f'{len(region)+2} {len(arcs)} {source} {sink}\n'+''.join(f'{u} {v} {c}\n' for u,v,c in arcs)
    started=time.perf_counter()
    result=subprocess.run([str(BINARY)],input=text,text=True,capture_output=True,check=True)
    lines=result.stdout.splitlines();value=int(lines[0]);reachable=set(map(int,lines[1].split()))
    selected=[u for u,i in local.items() if i in reachable]
    if seed not in selected:raise RuntimeError('Exact seeded cut failed force constraint')
    objective=Fraction(value+constant,denominator)
    actual=Fraction(graph.stats(selected)['cut'])+sum(Fraction(unary[u]) for u in selected)
    if objective!=actual:raise RuntimeError('Cut encoding/return objective disagreement')
    return selected,objective,{'flow_integer':str(value),'constant_integer':str(constant),
      'capacity_denominator':str(denominator),'arcs':len(arcs),'vertices':len(region),
      'runtime_seconds':time.perf_counter()-started,'backend':'Dinic_exact_int128'}


def mm_refine(graph, seed, region, initial, score, ordering='diffusion', rng_seed=0, progress=None):
    import numpy as np
    R=sorted(set(region));Rset=set(R);S=set(initial);trace=[];rng=np.random.default_rng(rng_seed)
    if not S.issubset(R) or seed not in S:raise ValueError('Invalid frozen MM initial/region')
    if ordering=='bfs':
        distances={seed:0};queue=[seed]
        for u in queue:
            for v in graph.indices[graph.indptr[u]:graph.indptr[u+1]]:
                v=int(v)
                if v in Rset and v not in distances:distances[v]=distances[u]+1;queue.append(v)
        priority={u:-distances.get(u,graph.n+1) for u in R}
    elif ordering=='random':priority={u:float(rng.random()) for u in R}
    else:priority={u:float(score[u]) for u in R}
    while True:
        current=graph.z_exact(S)
        order=sorted(R,key=lambda u:(0 if u==seed else (1 if u in S else 2),-priority[u],u))
        cumulative=0;unary={}
        for u in order:
            d=int(round(graph.degree[u]));cumulative+=d
            g=cumulative*cumulative-(cumulative-d)**2
            unary[u]=Fraction(g,int(round(graph.total)))-current*d
        zero=Fraction(graph.stats(S)['cut'])+sum(unary[u] for u in S)
        if zero!=0:raise RuntimeError('P5 MM value at current set is nonzero')
        new,value,telemetry=cut_with_unary(graph,R,seed,unary)
        next_z=graph.z_exact(new)
        accepted=next_z<current
        if value>0 or (value<0 and not accepted):raise RuntimeError('Frozen P5 exact contradiction')
        trace.append({'iteration':len(trace),'Z_before_exact':str(current),
            'Z_proposed_exact':str(next_z),'mincut_objective_exact':str(value),
            'zero_at_current_exact':str(zero),'accepted':accepted,'vertices':new,
            'order':order,'telemetry':telemetry})
        if progress is not None:progress({'stage':'mm','iteration':len(trace)-1,'current_vertices':sorted(S),'proposed_vertices':new,'step':trace[-1]})
        if not accepted:
            if value!=0:raise RuntimeError('MM stopped without zero optimum')
            return sorted(S),trace
        S=set(new)
