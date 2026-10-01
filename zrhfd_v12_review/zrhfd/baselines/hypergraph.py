"""Explicit hypergraph CPU baselines; no graph proxy for HFD or TL*.

ACL alone uses a declared degree-preserving clique expansion, as in protocol.
"""
from pathlib import Path
import copy
import itertools
import math
import tempfile
import time
from ._common import ROOT,mass_grid,source_record,validate_query
from ._execution import execute_julia
from .tlhfd import SOURCE


def _emit(progress,payload):
    if progress is not None:progress(copy.deepcopy(payload))


def conductance(h,vertices):
    volume=float(h.volume(vertices));denominator=min(volume,h.total-volume)
    return float(h.cut(vertices))/denominator if denominator>0 else math.inf


def sweep(h,heights,seed,require_seed=True,keep_ties=False):
    order=sorted((int(v) for v,x in heights.items() if x>0),key=lambda v:(-heights[v],v))
    selected=set();counts={};cut=volume=0.0;best=[];best_phi=math.inf
    for index,v in enumerate(order):
        for eid in h.incidence[v]:
            vertices,theta,w=h.edges[eid];old=counts.get(eid,0)
            cut+=float(theta)*float(w[old+1]-w[old]);counts[eid]=old+1
        selected.add(v);volume+=float(h.degree[v])
        if keep_ties and index+1<len(order) and heights[order[index+1]]==heights[v]:continue
        denominator=min(volume,h.total-volume)
        if denominator>0 and (not require_seed or seed in selected):
            phi=max(0.0,cut)/denominator
            if phi<best_phi:best_phi,best=phi,sorted(selected)
    return best,best_phi


def objective(h,heights,seed,mass,sigma):
    edges={eid for v in heights for eid in h.incidence[v]}
    quadratic=0.0
    for eid in sorted(edges):
        vertices,theta,w=h.edges[eid]
        ordered=sorted(vertices,key=lambda v:(-heights.get(v,0.0),v))
        fe=sum(float(w[i+1]-w[i])*heights.get(v,0.0) for i,v in enumerate(ordered))
        quadratic+=float(theta)*fe*fe
    regularizer=sum(float(h.degree[v])*x*x for v,x in heights.items())
    linear=sum(float(h.degree[v])*x for v,x in heights.items())-mass*heights.get(seed,0.0)
    return .5*quadratic+.5*sigma*regularizer+linear


def algorithm_one(h,heights,seed,mass,sigma,eta,k,gamma):
    active=set(heights)|{seed};incident={eid for v in active for eid in h.incidence[v]}
    local=set(active)
    for eid in incident:local.update(h.edges[eid][0])
    boundary=local-active
    gradients={v:float(h.degree[v])*(1+sigma*heights.get(v,0.0))-(mass if v==seed else 0.) for v in local}
    inward={v:0. for v in boundary}
    for eid in sorted(incident):
        vertices,theta,w=h.edges[eid]
        ordered=sorted(vertices,key=lambda v:(-heights.get(v,0.0),v))
        slopes=[float(w[i+1]-w[i]) for i in range(len(vertices))]
        fe=sum(slopes[i]*heights.get(v,0.) for i,v in enumerate(ordered))
        for i,v in enumerate(ordered):gradients[v]+=float(theta)*fe*slopes[i]
        overlap=len(active.intersection(vertices))
        unit=all(value==1 for value in w[1:-1])
        commitment=float(theta)*(1.0 if unit else float(w[overlap]))
        for v in vertices:
            if v in boundary:inward[v]+=commitment
    result={}
    for v in active:
        if h.degree[v]>0:
            value=max(0.,heights.get(v,0.)-eta*gradients[v]/float(h.degree[v]))
            if value>0:result[v]=value
    pushes={v:max(0.,-gradients[v]/float(h.degree[v])) for v in boundary}
    chosen=sorted(boundary,key=lambda v:(-pushes[v]*(inward[v]/float(h.degree[v]))**gamma,v))[:k]
    for v in chosen:
        value=eta*pushes[v]
        if value>0:result[v]=value
    if any(not math.isfinite(value) for value in result.values()):raise FloatingPointError('Nonfinite TL* hypergraph iterate')
    chosen_set=set(chosen)
    return result,local,{'active_nodes':len(active),'boundary_nodes':len(boundary),'incident_hyperedges':len(incident),'activated_positive_nodes':sum(pushes[v]>0 for v in chosen),'skipped_push_degree_sum':sum(float(h.degree[v])*pushes[v] for v in boundary-chosen_set)}


def run_tlhfd(h,seed,config,oracle_volume=None,progress=None):
    started=time.perf_counter();degree=validate_query(h,seed)
    if degree==0:return {'vertices':[seed],'runtime_seconds':time.perf_counter()-started,'touched_vertices':[seed],'metadata':{'method':'TL*-hyper-Algorithm1','stop':'isolated_seed'}}
    if config.get('step_schedule')!='constant' or config.get('return_policy','best_dual')!='best_dual':
        raise ValueError('Hyper TL* currently requires explicit constant step schedule and best_dual; no silent paper default')
    eta=float(config['step_size']);sigma=float(config.get('sigma',1e-4));gamma=float(config.get('gamma',1.))
    iterations=int(config.get('iterations',1000));deadline=started+float(config.get('budget_seconds',600))
    if eta<=0 or sigma<=0 or gamma<0 or iterations<1 or not all(math.isfinite(x) for x in [eta,sigma,gamma]):raise ValueError('Invalid explicit TL* hyper parameters')
    for vertices,theta,w in h.edges:
        slopes=[w[i+1]-w[i] for i in range(len(vertices))]
        if any(slopes[i]<slopes[i+1] for i in range(len(slopes)-1)):raise ValueError('Nonconcave splitting is outside submodular Algorithm1 domain')
    unit=all(all(value==1 for value in w[1:-1]) for vertices,theta,w in h.edges)
    scale=config.get('activation_scale','volume' if unit else 'vertex_count')
    if scale not in {'volume','vertex_count'}:raise ValueError('Unknown explicit top-k scale')
    masses,policy=mass_grid(h,seed,config,oracle_volume)
    fractions=[float(x) for x in config.get('fraction_grid',[.01,.02,.03,.05] if unit else [.01,.02,.03,.05,.07,.10])]
    if any(not math.isfinite(f) or f<0 for f in fractions):raise ValueError('Invalid activation fractions')
    trials=[];touched={seed};support_union=set();best_vertices=[seed];best_phi=conductance(h,[seed]);timed_out=False
    _emit(progress,{'stage':'algorithm_started','method':'TL*-hyper-Algorithm1','backend':'pure_python','mass_grid':masses,'vertices':best_vertices,'completed_trial_count':0,'mass_grid_complete':False})
    for mass in masses:
        estimate=mass/float(config.get('injection_factor',3.))
        if scale=='vertex_count':estimate/=h.total/h.n
        ks=[int(k) for k in config['k_grid']] if 'k_grid' in config else [max(1,int(math.floor(f*estimate+.5))) for f in fractions]
        for fi,k in enumerate(ks):
            if k<0:raise ValueError('Negative top-k')
            heights={};best_heights={};best_objective=0.;selected_epoch=0;trace=[];reason='fixed_iterations'
            for epoch in range(iterations):
                if time.perf_counter()>=deadline:reason='time_budget';timed_out=True;break
                value=objective(h,heights,seed,mass,sigma)
                if not math.isfinite(value):raise FloatingPointError('Nonfinite hypergraph dual objective')
                if value<best_objective:best_objective,best_heights,selected_epoch=value,dict(heights),epoch
                heights,seen,diagnostics=algorithm_one(h,heights,seed,mass,sigma,eta,k,gamma)
                touched.update(seen);trace.append({'iteration':epoch+1,'eta':eta,'objective_before_update':value,**diagnostics})
            support_union.update(best_heights)
            vertices,phi=sweep(h,best_heights,seed,config.get('require_seed',True),config.get('keep_ties',False))
            if vertices and phi<best_phi:best_vertices,best_phi=vertices,phi
            trials.append({'mass':mass,'k':k,'fraction':None if 'k_grid' in config else fractions[fi],'conductance':phi if math.isfinite(phi) else None,'selected_iteration':selected_epoch,'selected_support':sorted(best_heights),'best_dual_objective':best_objective,'updates':len(trace),'stop':reason,'trace':trace})
            _emit(progress,{'stage':'trial_finished','method':'TL*-hyper-Algorithm1','backend':'pure_python','trial_index':len(trials)-1,'trial':trials[-1],'vertices':best_vertices,'diffusion_support_union':sorted(support_union),'touched_vertices':sorted(touched),'mass_grid':masses,'completed_trial_count':len(trials),'mass_grid_complete':False,'status':'PARTIAL_GRID_CHECKPOINT'})
            if timed_out:break
        if timed_out:break
    _emit(progress,{'stage':'grid_finished','method':'TL*-hyper-Algorithm1','backend':'pure_python','vertices':best_vertices,'diffusion_support_union':sorted(support_union),'touched_vertices':sorted(touched),'mass_grid':masses,'completed_trial_count':len(trials),'mass_grid_complete':not timed_out,'status':'PARTIAL_TIMEOUT' if timed_out else 'COMPLETED'})
    return {'vertices':sorted(best_vertices),'runtime_seconds':time.perf_counter()-started,'touched_vertices':sorted(touched),'metadata':{'method':'TL*-hyper-Algorithm1','sources':{'paper':SOURCE,'version':'2606.09340v1','identity':'independent actual Lovasz+Algorithm1 port'},'objective':'HFD quadratic dual with the supplied splitting function','sigma':sigma,'gamma':gamma,'step_schedule':'constant','step_size':eta,'step_size_provenance':'explicit engineering input, paper experiment actual step size undisclosed','return_policy':'best_dual among old iterates 0..T-1','splitting':h.splitting,'unit_profile':unit,'activation_scale':scale,'subgradient_ties':'greedy Lovasz extreme point: descending old height, ascending node ID','topk_ties':'ascending node ID','rounding':'nearest integer; exact halves upward','require_seed_in_sweep':bool(config.get('require_seed',True)),'keep_ties':bool(config.get('keep_ties',False)),'oracle':oracle_volume is not None,'mass_policy':policy,'mass_grid':masses,'mass_grid_complete':not timed_out,'selection':'per-query lowest output conductance across fixed mass/f grid, first tied configuration; differs from paper per-cluster median selection','stop':'TIMEOUT' if timed_out else 'configuration_grid_finished','status':'PARTIAL_TIMEOUT' if timed_out else 'COMPLETED','update_count':sum(t['updates'] for t in trials),'diffusion_support_union':sorted(support_union),'touched_definition':'union of active vertices and all vertices in their scanned incident hyperedges','trials':trials}}


def run_hfd(h,seed,config,oracle_volume=None,progress=None):
    started=time.perf_counter();degree=validate_query(h,seed)
    if degree==0:return {'vertices':[seed],'runtime_seconds':time.perf_counter()-started,'touched_vertices':[seed],'metadata':{'method':'unit-HFD-author-Julia','stop':'isolated_seed'}}
    if any(theta!=1 or any(value!=1 for value in w[1:-1]) for vertices,theta,w in h.edges):
        raise NotImplementedError('Native author hyper HFD verified only for unweighted unit all-or-nothing')
    masses,policy=mass_grid(h,seed,config,oracle_volume)
    iterations=int(config.get('iterations',50));sigma=float(config.get('sigma',1e-4))
    if iterations<1 or sigma<=0 or not math.isfinite(sigma):raise ValueError('Invalid author HFD parameters')
    if not masses:return {'vertices':[seed],'runtime_seconds':time.perf_counter()-started,'touched_vertices':[seed],'metadata':{'method':'unit-HFD-author-Julia','stop':'no_admissible_mass','mass_policy':policy}}
    sources=source_record('hfd',['ucHFD.jl','utils.jl','struct.jl'])
    _emit(progress,{'stage':'algorithm_started','method':'unit-HFD-author-Julia','mass_grid':masses,'vertices':[seed],'completed_trial_count':0,'mass_grid_complete':False,'sources':sources,'native_checkpoint_semantics':'live stdout persists each mass; Python trial callbacks occur after the batch subprocess returns'})
    temporary=ROOT/'reviews/baselines/native-tmp';temporary.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hyper_baseline_',dir=temporary) as tmp:
        edgepath=Path(tmp)/'edges.csv';edgepath.write_text(''.join(','.join(map(str,vertices))+'\n' for vertices,theta,w in h.edges))
        args=[str(ROOT/'external/runtime/julia-1.10.10/bin/julia'),'--startup-file=no','--threads=1','--project='+str(ROOT/'external/runtime/hfd-environment'),str(ROOT/'zrhfd/baselines/native_driver.jl'),'hfd_hyper',str(ROOT/'external/hfd'),str(edgepath),str(h.n),str(seed),str(sigma),str(iterations),'2',','.join(map(str,masses)),'73','.001','.01']
        trials,execution=execute_julia(args,config,started+float(config.get('budget_seconds',600)),sources)
    complete=execution['status']=='COMPLETED'
    if complete and len(trials)!=len(masses):raise RuntimeError('Native hyper source incomplete mass grid')
    support=set();best=None
    for index,t in enumerate(trials):
        support.update(t['final_support']);t.pop('dual_heights',None)
        if t['vertices'] and t['conductance'] is not None and (best is None or t['conductance']<best['conductance']):best=t
        _emit(progress,{'stage':'trial_finished','method':'unit-HFD-author-Julia','trial_index':index,'trial':t,'vertices':sorted(best['vertices']) if best else [seed],'diffusion_support_union':sorted(support),'touched_vertices':list(range(h.n)),'mass_grid':masses,'completed_trial_count':index+1,'mass_grid_complete':False,'status':'PARTIAL_GRID_CHECKPOINT','execution':execution,'native_checkpoint_semantics':'callback delivered after batch process returns; original trial stdout persisted live'})
    _emit(progress,{'stage':'grid_finished','method':'unit-HFD-author-Julia','vertices':sorted(best['vertices']) if best else [seed],'diffusion_support_union':sorted(support),'touched_vertices':list(range(h.n)),'mass_grid':masses,'completed_trial_count':len(trials),'mass_grid_complete':complete,'status':'COMPLETED' if complete else 'PARTIAL_TIMEOUT','execution':execution})
    return {'vertices':sorted(best['vertices']) if best else [seed],'runtime_seconds':time.perf_counter()-started,'touched_vertices':list(range(h.n)),'metadata':{'method':'unit-HFD-author-Julia','sources':sources,'objective':'unit-HFD p=2 quadratic dual, fixed AM approximate solver','sigma':sigma,'p':2,'iterations':iterations,'oracle':oracle_volume is not None,'mass_policy':policy,'mass_grid':masses,'mass_grid_complete':complete,'selection':'minimum original-author best-iterate conductance across requested masses; native ties retained','stop':'mass_grid_finished' if complete else 'TIMEOUT','status':'COMPLETED' if complete else 'PARTIAL_TIMEOUT','update_count':iterations*len(trials) if complete else 'UNKNOWN: partial execution','diffusion_support_union':sorted(support),'kernel_seconds_total':sum(t['kernel_seconds'] for t in trials),'execution':execution,'touched_definition':'full hypergraph data conversion, author full vertex scans, and dense excess/degree vectors included','trials':trials}}


def run_acl(h,seed,config,oracle_volume=None,progress=None):
    from ..graph import Graph
    from .acl import run as graph_acl
    started=time.perf_counter()
    _emit(progress,{'stage':'conversion_started','method':'ACL-degree-preserving-clique-expansion','global_input_vertices':h.n,'global_input_hyperedges':len(h.edges),'intermediate_alpha_rho_trials_available':False})
    weights={}
    for vertices,theta,w in h.edges:
        pairweight=float(theta)/(len(vertices)-1)
        for u,v in itertools.combinations(vertices,2):weights[(min(u,v),max(u,v))]=weights.get((min(u,v),max(u,v)),0.)+pairweight
    clique=Graph.from_edges(h.n,[(u,v,w) for (u,v),w in weights.items()])
    import numpy as np
    if not np.allclose(clique.degree,h.degree,rtol=3e-13,atol=3e-13):raise RuntimeError('Declared clique expansion did not preserve incidence degree')
    _emit(progress,{'stage':'conversion_finished','method':'ACL-degree-preserving-clique-expansion','clique_edges':len(clique.edges),'degree_preserved':True,'touched_vertices':list(range(h.n)),'vertices':[seed],'intermediate_alpha_rho_trials_available':False})
    remaining=float(config.get('budget_seconds',600))-(time.perf_counter()-started)
    updated=dict(config,budget_seconds=max(0.,remaining))
    _emit(progress,{'stage':'algorithm_started','method':'ACL-degree-preserving-clique-expansion','vertices':[seed],'touched_vertices':list(range(h.n)),'mass_grid_complete':False,'intermediate_alpha_rho_trials_available':False,'checkpoint_semantics':'shared graph ACL has no callback; no intermediate trial coverage claimed'})
    out=graph_acl(clique,seed,updated,oracle_volume)
    out['runtime_seconds']=time.perf_counter()-started
    out['metadata'].update(method='ACL-degree-preserving-clique-expansion',clique_weight='each hyperedge contributes theta/(rank-1) to each unordered pair; duplicate pair weights summed',clique_edges=len(clique.edges),clique_degree_preserved=True,selection_objective='clique graph conductance; actual hypergraph output conductance evaluated offline',splitting_dependence='graph projection ignores supplied splitting; declared clique baseline only',clique_build_global_vertices=h.n,clique_build_global_hyperedges=len(h.edges),actual_clique_conversion_global=True)
    out['metadata']['push_frontier_vertices']=out['touched_vertices']
    out['touched_vertices']=list(range(h.n))
    _emit(progress,{'stage':'grid_finished','method':'ACL-degree-preserving-clique-expansion','vertices':out['vertices'],'touched_vertices':out['touched_vertices'],'metadata':out['metadata'],'intermediate_alpha_rho_trials_available':False})
    out['runtime_seconds']=time.perf_counter()-started
    return out
