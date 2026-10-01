"""Frozen hypergraph four-step pipeline, with injectable native diffusion."""
from dataclasses import dataclass,asdict
from fractions import Fraction as F
import time
import numpy as np
from .diffusion import solve_hypergraph,native_author_diffusion
from .mincut import mm_refine
from .certificate import regional_certificate


@dataclass(frozen=True)
class Config:
    sigma:float=1e-4
    patience:int=3
    improvement_epsilon:float=1e-6
    region:str='R-supp'
    theta:float=.5
    schedule_ratio:float=2.0
    mass_budget_fraction:float=.5
    refine:bool=True
    objective:str='ZH'
    diffusion_tolerance:float=1e-10
    support_tolerance:float=1e-7
    diffusion_backend:str='auto'


def level_sweep(h,score,seed,objective='ZH'):
    positive=score.support if hasattr(score,'support') else np.flatnonzero(score>0);order=sorted(map(int,positive),key=lambda u:(-float(score[u]),u));S=set();best=None;chosen=None;trace=[];i=0;counts={};cut=F(0);volume=F(0)
    while i<len(order):
        j=i+1
        while j<len(order) and score[order[j]]==score[order[i]]:j+=1
        for u in order[i:j]:
            S.add(u);volume+=h.degree_exact[u]
            for k in h.incidence[u]:
                e,theta,w=h.edges[k];previous=counts.get(k,0);counts[k]=previous+1;cut+=theta*(w[previous+1]-w[previous])
        if seed in S:
            null=h.G(volume) if objective=='ZH' else volume*volume/h.total_exact;value=(cut+null)/volume;trace.append({'end':j,'score':float(score[order[i]]),'volume_exact':str(volume),'cut_exact':str(cut),'value_exact':str(value)})
            if best is None or value<best:best=value;chosen=sorted(S)
        i=j
    if best is None:raise ValueError('No seeded positive hypergraph level')
    return chosen,best,trace


def capped_region(h,S0,score,theta):
    S0=set(S0);budget=F(str(theta))*h.volume(S0);positive=score.support if hasattr(score,'support') else np.flatnonzero(score>0);order=sorted(map(int,positive),key=lambda u:(-float(score[u]),u));L=set();i=0
    while i<len(order):
        j=i+1
        while j<len(order) and score[order[j]]==score[order[i]]:j+=1
        proposed=L|set(order[i:j])
        if h.volume(proposed-S0)>budget:break
        L=proposed;i=j
    return sorted(S0|L)


def run(hypergraph,seed,config=None,diffusion=None):
    h=hypergraph;cfg=config or Config()
    if diffusion is not None:solver=diffusion
    elif cfg.diffusion_backend=='native_hfd' or cfg.diffusion_backend=='auto' and h.n>200:solver=native_author_diffusion
    elif cfg.diffusion_backend in ['auto','cvxpy']:solver=solve_hypergraph
    else:raise ValueError('Unknown diffusion backend')
    start=time.perf_counter();m0=3*h.degree[seed];budget=cfg.mass_budget_fraction*h.total;xs=[];sets=[];zs=[];stage=[];touched=set();best=None;noimp=0;j_act=None;j=0;previous=None
    while True:
        mass=m0*cfg.schedule_ratio**j
        if mass>budget:stop='mass_budget';break
        score,telemetry=solver(h,seed,mass,sigma=cfg.sigma,tolerance=cfg.diffusion_tolerance,support_tolerance=cfg.support_tolerance)
        if not hasattr(score,'support'):raise ValueError('Diffusion adapter must return scores with explicit support')
        S,value,sweep_trace=level_sweep(h,score,seed,cfg.objective);telemetry.update(j=j,sweep_vertices=S,sweep_value_exact=str(value),sweep_blocks=sweep_trace);stage.append(telemetry);xs.append(score);sets.append(S);zs.append(value);touched.update(map(int,score.support))
        if previous is not None:
            union=np.union1d(score.support,previous.support);telemetry['mass_monotonicity_min_delta']=float(np.min(score[union]-previous[union],initial=0));telemetry['monotonicity_status']='observational_only' if h.splitting!='all_or_nothing' else 'numeric_unit_monotonicity_telemetry'
        previous=score
        if j_act is None and len(score.support)>1:j_act=j
        if best is None or float(best-value)>cfg.improvement_epsilon:best=value;noimp=0
        elif j_act is not None:noimp+=1
        if j_act is not None and noimp>=cfg.patience:stop='post_activation_patience';break
        j+=1
    if j_act is None:S=[seed];S0=S;R=S;trace=[];jstar=None;status='no_activation'
    else:
        jstar=min(range(len(zs)),key=lambda k:zs[k]);S0=sets[jstar]
        if jstar+1<len(xs):score=xs[jstar+1]
        else:
            score,extra=solver(h,seed,m0*cfg.schedule_ratio**(jstar+1),sigma=cfg.sigma,tolerance=cfg.diffusion_tolerance,support_tolerance=cfg.support_tolerance);extra.update(j=jstar+1,supplement_for_region=True);stage.append(extra);touched.update(map(int,score.support))
        if cfg.region=='R-supp':R=score.support.tolist()
        elif cfg.region=='R-cap':R=capped_region(h,S0,score,cfg.theta)
        else:raise ValueError('Unknown explicitly named hyper region')
        if seed not in R or not set(S0)<=set(R):raise RuntimeError('Frozen hyper region inclusion contradiction; do not bypass')
        S,trace=mm_refine(h,seed,R,S0,score,cfg.objective) if cfg.refine else(S0,[]);status='completed'
    touched.update(R);certificate=regional_certificate(h,seed,R,cfg.objective);z=h.z_exact(S,cfg.objective);certificate['gap']=float(z)-certificate['LB_R']
    if certificate['gap'] < -1e-8:raise RuntimeError('Hyper numeric region lower bound exceeds objective')
    return {'vertices':sorted(S),'S0':S0,'region_vertices':sorted(R),'status':status,'stop_reason':stop,'j_act':j_act,'j_star':jstar,'mass_sequence':[item['mass'] for item in stage],'region_volume':float(h.volume(R)),'touched_vertices':sorted(touched),'touched_volume':float(h.volume(touched)),'runtime_seconds':time.perf_counter()-start,'stats':h.stats(S),'selected_objective':cfg.objective,'selected_Z_exact':str(z),'components':len(h.components(S)),'certificate':certificate,'diffusion_trace':stage,'mm_trace':trace,'config':asdict(cfg),'splitting':h.splitting,'numeric_solver_status':'APPROXIMATE_DIFFUSION_EXACT_RATIONAL_HYPERCUTS','scope_gate':'FROZEN_GENERAL_CARDINALITY_GATE_REMAINS_BLOCKED_BY_M1'}
