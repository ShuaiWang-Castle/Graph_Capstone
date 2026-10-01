"""Activation-aware frozen ZR-HFD graph method and explicitly named ablations."""
from dataclasses import dataclass,asdict
import math
import time
import numpy as np
from .diffusion import solve_graph,activation_mass
from .sweep import level_sweep,capped_region
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
    start:str='3ds'
    mass_budget_fraction:float=.5
    ordering:str='diffusion'
    refine:bool=True
    sweep_objective:str='Z'
    return_hull_best:bool=False
    diffusion_tolerance:float=1e-12
    max_updates:int=20_000_000
    fixed_grid:tuple=()
    random_seed:int=1907


def run(graph,seed,config=None,diffusion_solver=None,progress=None):
    cfg=config or Config()
    solver=diffusion_solver or solve_graph
    start_time=time.perf_counter()
    if graph.degree[seed]<=0:raise ValueError('Frozen Z undefined for zero-degree seed')
    mact=activation_mass(graph,seed,cfg.sigma)
    m0=mact*(1+1e-9) if cfg.start=='mact' else 3*float(graph.degree[seed])
    budget=cfg.mass_budget_fraction*graph.total
    xs=[];sets=[];zs=[];stage=[];touched=set();j_act=None;best=None;noimp=0
    previous=None;j=0;stop='mass_budget'
    while True:
        if cfg.fixed_grid:
            if j>=len(cfg.fixed_grid):stop='fixed_grid_exhausted';break
            mass=float(cfg.fixed_grid[j])
        else:mass=m0*cfg.schedule_ratio**j
        if mass>budget:stop='mass_budget';break
        x,telemetry=solver(graph,seed,mass,cfg.sigma,cfg.diffusion_tolerance,cfg.max_updates)
        if telemetry['queue_pending']:
            raise RuntimeError('Diffusion update budget exhausted; do not score as converged')
        if previous is not None:
            union=np.union1d(x.support,previous.support)
            telemetry['mass_monotonicity_min_delta']=float(np.min(x[union]-previous[union],initial=0))
        S,value,sweep_trace=level_sweep(graph,x,seed,cfg.sweep_objective)
        previous=x;xs.append(x);sets.append(S);zs.append(value)
        touched.update(map(int,x.support))
        telemetry.update(j=j,sweep_vertices=S,sweep_value_exact=str(value),sweep_blocks=sweep_trace)
        stage.append(telemetry)
        if progress is not None:progress({'stage':'diffusion','j':j,'mass':mass,'sweep_vertices':S,'telemetry':telemetry})
        if j_act is None and len(x.support)>1:j_act=j
        if best is None or float(best-value)>cfg.improvement_epsilon:
            best=value;noimp=0
        elif j_act is not None:noimp+=1
        if j_act is not None and noimp>=cfg.patience:stop='post_activation_patience';break
        j+=1
    if j_act is None:
        # The frozen specification explicitly returns the singleton when no
        # activation occurred by budget. It has no j*, so do not invent one.
        S=[int(seed)];R=S;score=np.zeros(graph.n);score[seed]=1
        mm_trace=[];jstar=None;S0=S;status='no_activation'
        certificate=regional_certificate(graph,seed,R)
    else:
        jstar=min(range(len(zs)),key=lambda k:zs[k]);S0=sets[jstar]
        if jstar+1<len(xs):score=xs[jstar+1]
        else:
            mass=(float(cfg.fixed_grid[jstar])*cfg.schedule_ratio if cfg.fixed_grid else m0*cfg.schedule_ratio**(jstar+1))
            score,extra=solver(graph,seed,mass,cfg.sigma,cfg.diffusion_tolerance,cfg.max_updates)
            if extra['queue_pending']:raise RuntimeError('Supplementary region diffusion incomplete')
            extra.update(j=jstar+1,supplement_for_region=True)
            stage.append(extra);touched.update(map(int,score.support))
        if cfg.region=='R-cap':R=capped_region(graph,S0,score,cfg.theta)
        elif cfg.region=='supp-jstar':R=xs[jstar].support.tolist()
        elif cfg.region=='supp-jstar+2':
            if jstar+2<len(xs):larger=xs[jstar+2]
            else:
                mass=m0*cfg.schedule_ratio**(jstar+2)
                larger,extra=solver(graph,seed,mass,cfg.sigma,cfg.diffusion_tolerance,cfg.max_updates)
                if extra['queue_pending']:raise RuntimeError('Larger region diffusion incomplete')
                extra.update(j=jstar+2,supplement_for_region=True);stage.append(extra)
                touched.update(map(int,larger.support))
            R=larger.support.tolist()
        elif cfg.region=='full':R=list(range(graph.n))
        elif cfg.region=='R-supp':R=score.support.tolist()
        else:raise ValueError('Unknown named region')
        if seed not in R or not set(S0).issubset(R):
            raise RuntimeError('Frozen Step3 seed/initial inclusion contradiction')
        touched.update(R)
        if progress is not None:progress({'stage':'region','j_star':jstar,'S0':S0,'region_vertices':sorted(map(int,R))})
        S,mm_trace=mm_refine(graph,seed,R,S0,score,cfg.ordering,cfg.random_seed,progress=progress) if cfg.refine else (S0,[])
        if progress is not None:progress({'stage':'certificate_started','vertices':S,'region_vertices':sorted(map(int,R))})
        certificate=regional_certificate(graph,seed,R)
        status='completed'
    touched.update(R)
    if cfg.return_hull_best:S=certificate['hull_best']
    output_stats=graph.stats(S)
    certificate['gap']=float(output_stats['Z'])-certificate['LB_R']
    if certificate['gap'] < -1e-10:
        raise RuntimeError('Region lower-bound certificate exceeds returned objective')
    return {'vertices':sorted(map(int,S)),'S0':S0,'region_vertices':sorted(map(int,R)),
       'status':status,'stop_reason':stop,'j_act':j_act,'j_star':jstar,'m_act':mact,
       'mass_sequence':[a['mass'] for a in stage],'mass_grid_start':m0,
       'region_volume':float(graph.degree[R].sum()),
       'touched_vertices':sorted(touched),'touched_volume':float(graph.degree[list(touched)].sum()),
       'runtime_seconds':time.perf_counter()-start_time,'stats':output_stats,
       'components':len(graph.components(S)),'certificate':certificate,
       'diffusion_trace':stage,'mm_trace':mm_trace,'config':asdict(cfg),
       'numeric_solver_status':'APPROXIMATE_DIFFUSION_EXACT_INTEGRAL_CUTS',
       'method_semantics':'ZR-HFD frozen v1.2 graph main' if cfg==Config() and diffusion_solver is None else 'explicit_configured_ablation'}
