"""Named dev variants. No label is accepted by any variant."""
from dataclasses import replace
import math,time
import numpy as np
from zrhfd.pipeline import Config,run
from zrhfd.diffusion import Scores,solve_graph
from zrhfd.mincut import mm_refine
from zrhfd.sweep import level_sweep

NAMES=['R-cap-0.25','R-cap-0.5','R-cap-1','supp-jstar','supp-jstar+2','full',
       'patience-2','ZR-mact','sqrt2-grid','fixed-grid','ZR-budgetM','ordering-bfs',
       'ordering-random','multi-start','diffusion-TL-star','no-refinement','hull-best','conductance-sweep']

def run_variant(graph,seed,name,base=None,progress=None):
    cfg=base or Config();started=time.perf_counter()
    if name.startswith('R-cap-'):cfg=replace(cfg,region='R-cap',theta=float(name.removeprefix('R-cap-')))
    elif name in ['supp-jstar','supp-jstar+2','full']:cfg=replace(cfg,region=name)
    elif name=='patience-2':cfg=replace(cfg,patience=2)
    elif name=='ZR-mact':cfg=replace(cfg,start='mact')
    elif name=='sqrt2-grid':cfg=replace(cfg,schedule_ratio=math.sqrt(2))
    elif name=='fixed-grid':cfg=replace(cfg,fixed_grid=tuple(3*m for m in [50,100,200,400,800,1600,3200,6400]))
    elif name=='ZR-budgetM':cfg=replace(cfg,mass_budget_fraction=1.)
    elif name=='ordering-bfs':cfg=replace(cfg,ordering='bfs')
    elif name=='ordering-random':cfg=replace(cfg,ordering='random')
    elif name=='no-refinement':cfg=replace(cfg,refine=False)
    elif name=='hull-best':cfg=replace(cfg,return_hull_best=True)
    elif name=='conductance-sweep':cfg=replace(cfg,sweep_objective='phi')
    elif name=='multi-start':
        r=run(graph,seed,replace(cfg,refine=False),progress=progress)
        if r['j_star'] is None:r.update(variant=name);return r
        mass=r['mass_grid_start']*cfg.schedule_ratio**(r['j_star']+1)
        score,telemetry=solve_graph(graph,seed,mass,cfg.sigma,cfg.diffusion_tolerance,cfg.max_updates)
        starts=[r['S0'],[seed],r['certificate']['hull_best']];trials=[]
        for initial in starts:
            vertices,trace=mm_refine(graph,seed,r['region_vertices'],initial,score,cfg.ordering,cfg.random_seed,progress=progress)
            trials.append({'initial_vertices':initial,'vertices':vertices,'MM':trace,'Z_exact':str(graph.z_exact(vertices))})
        selected=min(trials,key=lambda a:graph.z_exact(a['vertices']));r['vertices']=selected['vertices'];r['mm_trace']=selected['MM']
        r['stats']=graph.stats(r['vertices']);r['components']=len(graph.components(r['vertices']))
        r['certificate']['gap']=r['stats']['Z']-r['certificate']['LB_R'];r.update(multi_start_trials=trials,score_recompute_telemetry=telemetry)
        r['runtime_seconds']=time.perf_counter()-started;r['variant']=name;r['method_semantics']='explicit multi-start variant';return r
    elif name=='diffusion-TL-star':
        from zrhfd.baselines.tlhfd_numba import solve_trial
        def tl_solver(g,s,mass,sigma,tolerance,max_updates):
            candidates=[];trialmeta=[];touched=set();trialstart=time.perf_counter()
            for f in [.01,.02,.03,.05]:
                k=max(1,int(math.floor(f*mass/3+.5)))
                t=solve_trial(g,s,mass,sigma,1.,.25,k,1000)
                x=np.zeros(g.n).view(Scores)
                for u,v in t['best_heights'].items():x[u]=v
                x.support=np.asarray(sorted(t['best_heights']),dtype=np.int64)
                S,z,trace=level_sweep(g,x,s,'Z');candidates.append((z,x))
                touched.update(t['touched']);trialmeta.append({'fraction':f,'k':k,'best_dual_objective':t['best_objective'],
                     'updates':t['updates'],'stop':t['stop'],'sweep_value_exact':str(z),'sweep_vertices':S})
            _,score=min(candidates,key=lambda t:t[0])
            return score,{'mass':mass,'queue_pending':0,'runtime_seconds':time.perf_counter()-trialstart,
                 'support_size':len(score.support),'support_volume':float(g.degree[score.support].sum()),
                 'solver_backend':'TL*-Algorithm1-numba-1000-selected-best-dual',
                 'selection':'min Z-sweep over fixed f grid, no labels','actual_frontier_vertices':len(touched),
                 'precision_mode':'finite_iteration_approximate','trials':trialmeta}
        r=run(graph,seed,cfg,diffusion_solver=tl_solver,progress=progress);r.update(variant=name,method_semantics='explicit TL* diffusion variant');return r
    else:raise ValueError('Unknown registered ablation '+name)
    r=run(graph,seed,cfg,progress=progress);r.update(variant=name);return r
