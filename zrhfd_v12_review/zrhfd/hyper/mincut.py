"""Exact directed hypergraph reductions, int128 and explicit bigint fallback."""
from fractions import Fraction as F
from math import lcm
import subprocess
import time
from ..mincut import BINARY
from .diffusion import capped_coefficients


def directed_cut(n,arcs,source,sink):
    denominator=1
    for u,v,c in arcs:denominator=lcm(denominator,F(c).denominator)
    integers=[(u,v,int(c*denominator)) for u,v,c in arcs if c]
    bound=sum(c for u,v,c in integers);start=time.perf_counter()
    if bound < 1 << 124:
        payload=f'{n} {len(integers)} {source} {sink}\n'+''.join(f'{u} {v} {c}\n' for u,v,c in integers)
        output=subprocess.run([str(BINARY)],input=payload,text=True,capture_output=True,check=True).stdout.splitlines();value=int(output[0]);selected=set(map(int,output[1].split()));backend='Dinic_exact_int128'
    else:
        import networkx as nx
        graph=nx.DiGraph();graph.add_nodes_from(range(n))
        for u,v,c in integers:
            if graph.has_edge(u,v):graph[u][v]['capacity']+=c
            else:graph.add_edge(u,v,capacity=c)
        value,partition=nx.minimum_cut(graph,source,sink,capacity='capacity',flow_func=nx.algorithms.flow.preflow_push);selected=set(partition[0]);value=int(value);backend='NetworkX_exact_arbitrary_integer_preflow_push'
    return selected,F(value,denominator),{'backend':backend,'capacity_denominator':str(denominator),'capacity_sum_bit_length':bound.bit_length(),'capacity_max_bit_length':max((c.bit_length() for u,v,c in integers),default=0),'arcs':len(integers),'vertices':n,'runtime_seconds':time.perf_counter()-start,'float_capacity_fallback':False}


def cut_with_unary(hypergraph,region,seed,unary):
    h=hypergraph;R=sorted(set(map(int,region)));local={u:i for i,u in enumerate(R)}
    if seed not in local:raise ValueError('Seed outside region')
    incident=sorted(set(k for u in R for k in h.incidence[u]))
    arcs=[];constant=F(0);finite_sum=sum((abs(F(unary[u])) for u in R),F(0))+sum((h.edges[k][1]*max(h.edges[k][2]) for k in incident),F(0));infinity=finite_sum+1;next_node=len(R);source=next_node;next_node+=1;sink=next_node;next_node+=1
    def add(u,v,c):
        if c:arcs.append((u,v,F(c)))
    for u in R:
        c=F(unary[u])
        if c>=0:add(local[u],sink,c)
        else:add(source,local[u],-c);constant+=c
    lawler=cardinal=0
    for k in incident:
        e,theta,w=h.edges[k]
        members=[u for u in e if u in local];outside=len(e)-len(members)
        if not members:continue
        if all(v==1 for v in w[1:-1]):
            a,b=next_node,next_node+1;next_node+=2;add(a,b,theta)
            for u in members:add(local[u],a,infinity);add(b,local[u],infinity)
            if outside:add(b,sink,infinity)
            lawler+=1
        else:
            for cap,coefficient in capped_coefficients(w):
                a,b=next_node,next_node+1;next_node+=2;weight=theta*coefficient;add(a,b,weight*cap)
                for u in members:add(local[u],a,weight);add(b,local[u],weight)
                if outside:add(b,sink,weight*outside)
                cardinal+=1
    add(source,local[seed],infinity)
    reachable,value,telemetry=directed_cut(next_node,arcs,source,sink);S=[u for u in R if local[u] in reachable];objective=value+constant
    actual=h.cut(S)+sum((F(unary[u]) for u in S),F(0))
    if seed not in S or objective!=actual:raise RuntimeError('Exact hypergraph reduction objective mismatch')
    telemetry.update(lawler_gadgets=lawler,cardinality_capped_min_gadgets=cardinal,unary_constant_exact=str(constant),full_hypergraph_boundary=True,region_incident_hyperedges=len(incident))
    return S,objective,telemetry


def mm_refine(hypergraph,seed,region,initial,score,objective='ZH'):
    h=hypergraph;R=sorted(set(region));S=set(initial);trace=[]
    if seed not in S or not S<=set(R):raise ValueError('Invalid initial/region')
    while True:
        lam=h.z_exact(S,objective);order=sorted(R,key=lambda u:(0 if u==seed else(1 if u in S else 2),-float(score[u]),u));D=F(0);unary={}
        for u in order:
            previous=D;D+=h.degree_exact[u]
            increment=(h.G(D)-h.G(previous)) if objective=='ZH' else (D*D-previous*previous)/h.total_exact
            unary[u]=increment-lam*h.degree_exact[u]
        current_value=h.cut(S)+sum((unary[u] for u in S),F(0))
        if current_value:raise RuntimeError('Frozen hyper MM zero-at-current contradiction')
        proposed,value,telemetry=cut_with_unary(h,R,seed,unary);new_z=h.z_exact(proposed,objective);accepted=new_z<lam
        if value>0 or value<0 and not accepted:raise RuntimeError('Frozen hyper P5 contradiction')
        trace.append({'iteration':len(trace),'order':order,'vertices':proposed,'Z_before_exact':str(lam),'Z_proposed_exact':str(new_z),'mincut_objective_exact':str(value),'zero_at_current_exact':'0','accepted':accepted,'telemetry':telemetry})
        if not accepted:
            if value:raise RuntimeError('Hyper MM lacks zero optimum at stop')
            return sorted(S),trace
        S=set(proposed)
