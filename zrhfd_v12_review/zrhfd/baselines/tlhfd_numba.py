"""CPU acceleration of the same graph Algorithm1; no approximate frontier pruning."""
import math
import time
import numpy as np
import numba
from numba import njit
from ._common import conductance, mass_grid, sweep, validate_query
from .tlhfd import SOURCE


@njit(cache=True,fastmath=False)
def _advance(indptr,indices,weights,degree,seed,mass,sigma,gamma,eta,k,
             x,active_ids,active_mask,grad,inward,boundary_ids,boundary_mask,
             touched,best_x,best_ids,active_count,best_count,best_objective,
             selected_epoch,trace,start_epoch,end_epoch):
    for epoch in range(start_epoch,end_epoch):
        active_ids[:active_count].sort()
        boundary_count=0
        quadratic=regularizer=linear=0.0
        for i in range(active_count):
            v=active_ids[i]
            xv=x[v]
            touched[v]=True
            grad[v]=degree[v]*(1+sigma*xv)-(mass if v==seed else 0.0)
            regularizer+=degree[v]*xv*xv
            linear+=degree[v]*xv
        for i in range(active_count):
            v=active_ids[i]
            xv=x[v]
            for j in range(indptr[v],indptr[v+1]):
                u=indices[j]
                w=weights[j]
                grad[v]+=w*(xv-x[u])
                if xv>0 and (x[u]==0 or v<u):
                    quadratic+=w*(xv-x[u])**2
                if not active_mask[u]:
                    if not boundary_mask[u]:
                        boundary_ids[boundary_count]=u
                        boundary_count+=1
                        boundary_mask[u]=True
                        touched[u]=True
                        grad[u]=degree[u]
                        inward[u]=0.0
                    grad[u]-=w*xv
                    inward[u]+=w
        objective=.5*quadratic+.5*sigma*regularizer+(linear-mass*x[seed])
        if not math.isfinite(objective):
            return active_count,best_count,best_objective,selected_epoch,epoch,False
        if objective<best_objective:
            for i in range(best_count):
                best_x[best_ids[i]]=0.0
            best_count=0
            for i in range(active_count):
                v=active_ids[i]
                if x[v]>0:
                    best_x[v]=x[v]
                    best_ids[best_count]=v
                    best_count+=1
            best_objective=objective
            selected_epoch=epoch
        boundary_ids[:boundary_count].sort()
        scores=np.empty(boundary_count,np.float64)
        pushes=np.empty(boundary_count,np.float64)
        for i in range(boundary_count):
            v=boundary_ids[i]
            pushes[i]=max(0.0,-grad[v]/degree[v])
            scores[i]=pushes[i]*(inward[v]/degree[v])**gamma
        # Boundary IDs start sorted; a stable descending score sort gives ID ties.
        order=np.argsort(-scores,kind='mergesort')
        picked=min(k,boundary_count)
        chosen=np.zeros(boundary_count,np.bool_)
        for i in range(picked):
            chosen[order[i]]=True
        skipped=0.0
        for i in range(boundary_count):
            if not chosen[i]:
                skipped+=degree[boundary_ids[i]]*pushes[i]
        old_active_count=active_count
        for i in range(old_active_count):
            active_mask[active_ids[i]]=False
        active_count=0
        for i in range(old_active_count):
            v=active_ids[i]
            value=max(0.0,x[v]-eta*grad[v]/degree[v]) if degree[v]>0 else 0.0
            if not math.isfinite(value):
                return active_count,best_count,best_objective,selected_epoch,epoch,False
            x[v]=value
            if value>0 or v==seed:
                active_ids[active_count]=v
                active_count+=1
                active_mask[v]=True
        activated=0
        for i in range(picked):
            bi=order[i]
            v=boundary_ids[bi]
            value=eta*pushes[bi]
            if not math.isfinite(value):
                return active_count,best_count,best_objective,selected_epoch,epoch,False
            if value>0:
                x[v]=value
                active_ids[active_count]=v
                active_count+=1
                active_mask[v]=True
                activated+=1
        for i in range(boundary_count):
            boundary_mask[boundary_ids[i]]=False
        trace[epoch,0]=objective
        trace[epoch,1]=old_active_count
        trace[epoch,2]=boundary_count
        trace[epoch,3]=activated
        trace[epoch,4]=skipped
    return active_count,best_count,best_objective,selected_epoch,end_epoch,True


def solve_trial(graph,seed,mass,sigma,gamma,eta,k,iterations,deadline=math.inf,initial_heights=None,chunk_steps=16):
    """Expose full and selected iterates for numerical cross-checks, not tuning."""
    n=graph.n
    x=np.zeros(n,np.float64)
    initial=dict(initial_heights or {})
    for v,value in initial.items():
        x[int(v)]=float(value)
    active_ids=np.empty(n,np.int64)
    initial_nodes=sorted(set(initial)|{seed})
    active_count=len(initial_nodes)
    active_ids[:active_count]=initial_nodes
    active_mask=np.zeros(n,np.bool_)
    active_mask[initial_nodes]=True
    grad=np.empty(n,np.float64)
    inward=np.empty(n,np.float64)
    boundary_ids=np.empty(n,np.int64)
    boundary_mask=np.zeros(n,np.bool_)
    touched=np.zeros(n,np.bool_)
    best_x=np.zeros(n,np.float64)
    best_ids=np.empty(n,np.int64)
    trace=np.empty((iterations,5),np.float64)
    best_count=selected_epoch=completed=0
    best_objective=0.0
    reason='fixed_iterations'
    for start in range(0,iterations,chunk_steps):
        if time.perf_counter()>=deadline:
            reason='time_budget'
            break
        active_count,best_count,best_objective,selected_epoch,completed,finite=_advance(
            graph.indptr,graph.indices,graph.weights,graph.degree,seed,mass,sigma,gamma,eta,k,
            x,active_ids,active_mask,grad,inward,boundary_ids,boundary_mask,touched,best_x,best_ids,
            active_count,best_count,best_objective,selected_epoch,trace,start,min(iterations,start+chunk_steps))
        if not finite:
            raise FloatingPointError('Nonfinite TL* Algorithm1 objective or iterate at iteration '+str(completed))
    return {'last_heights':{int(v):float(x[v]) for v in active_ids[:active_count] if x[v]>0},
            'best_heights':{int(v):float(best_x[v]) for v in best_ids[:best_count]},
            'touched':np.flatnonzero(touched).tolist(),'best_objective':float(best_objective),
            'selected_epoch':int(selected_epoch),'updates':int(completed),'stop':reason,'trace':trace[:completed]}


def run(graph,seed,config,oracle_volume=None):
    started=time.perf_counter()
    degree=validate_query(graph,seed)
    if degree==0:
        return {'vertices':[seed],'runtime_seconds':time.perf_counter()-started,'touched_vertices':[seed],'metadata':{'method':'TL*-Algorithm1','backend':'numba','stop':'isolated_seed','oracle':oracle_volume is not None}}
    if config.get('step_schedule')!='constant' or config.get('return_policy','best_dual')!='best_dual':
        raise ValueError('Numba Algorithm1 backend currently requires explicit constant schedule and best_dual; other explicit variants use literal backend')
    sigma=float(config.get('sigma',1e-4));gamma=float(config.get('gamma',1.0));eta=float(config['step_size'])
    iterations=int(config.get('iterations',1000));chunk_steps=int(config.get('numba_chunk_steps',16))
    if sigma<=0 or gamma<0 or iterations<1 or eta<=0 or not all(math.isfinite(v) for v in [sigma,gamma,eta]) or chunk_steps<1:
        raise ValueError('Invalid explicit TL* parameters')
    deadline=started+float(config.get('budget_seconds',600))
    masses,policy=mass_grid(graph,seed,config,oracle_volume)
    fractions=[float(f) for f in config.get('fraction_grid',[.01,.02,.03,.05])]
    if any(not math.isfinite(f) or f<0 for f in fractions):
        raise ValueError('Invalid activation fraction grid')
    best_vertices,best_phi=[seed],conductance(graph,[seed])
    trials,touched,support_union=[],{seed},set()
    timed_out=False
    for mass in masses:
        ks=[int(k) for k in config['k_grid']] if 'k_grid' in config else [max(1,int(math.floor(f*mass/float(config.get('injection_factor',3.0))+.5))) for f in fractions]
        for fi,k in enumerate(ks):
            if k<0:raise ValueError('TL* k must be nonnegative')
            trial=solve_trial(graph,seed,mass,sigma,gamma,eta,k,iterations,deadline,chunk_steps=chunk_steps)
            selected=trial['best_heights'];support_union.update(selected);touched.update(trial['touched'])
            vertices,phi=sweep(graph,selected,seed,config.get('require_seed',False),config.get('keep_ties',False))
            if vertices and phi<best_phi:best_vertices,best_phi=vertices,phi
            trace=[{'iteration':i+1,'eta':eta,'objective_before_update':float(row[0]),'active_nodes':int(row[1]),'boundary_nodes':int(row[2]),'activated_positive_nodes':int(row[3]),'skipped_push_degree_sum':float(row[4])} for i,row in enumerate(trial['trace'])]
            trials.append({'mass':mass,'k':k,'fraction':None if 'k_grid' in config else fractions[fi],'conductance':phi if math.isfinite(phi) else None,'stop':trial['stop'],'updates':trial['updates'],'selected_iteration':trial['selected_epoch'],'best_dual_objective':trial['best_objective'],'selected_support':sorted(selected),'trace':trace})
            if trial['stop']=='time_budget' or time.perf_counter()>=deadline:
                timed_out=True
                break
        if timed_out:break
    return {'vertices':sorted(best_vertices),'runtime_seconds':time.perf_counter()-started,'touched_vertices':sorted(touched),
            'metadata':{'method':'TL*-Algorithm1','backend':'numba','backend_version':numba.__version__,'fastmath':False,'parallel':False,'sources':{'paper':SOURCE,'version':'2606.09340v1','implementation_identity':'independent Algorithm1 port; author execution code unavailable'},'objective':'HFD quadratic dual','oracle':oracle_volume is not None,'mass_policy':policy,'mass_grid':masses,'mass_grid_complete':not timed_out,'sigma':sigma,'gamma':gamma,'iterations_requested':iterations,'step_schedule':'constant','step_size':eta,'step_schedule_provenance':'explicit implementation choice; paper experimental step not disclosed','return_policy':'best_dual','return_policy_provenance':'theoretical best-dual iterate','topk_ties':'ascending node ID','rounding':'nearest integer; exact halves upward','require_seed_in_sweep':bool(config.get('require_seed',False)),'keep_ties':bool(config.get('keep_ties',False)),'update_count':sum(t['updates'] for t in trials),'stop':'query_budget' if timed_out else 'configuration_grid_finished','status':'PARTIAL_TIMEOUT' if timed_out else 'COMPLETED','selection':'minimum output conductance over mass and activation grids; first tied configuration','touched_definition':'union of active region and one-hop boundary read by exact local graph update','dense_storage':'O(n) scratch arrays allocated and initialized at trial entry; this cost and JIT/cache loading are included in wrapper runtime','clock_check':'between chunks of '+str(chunk_steps)+' simultaneous Algorithm1 updates; outer task scheduler also imposes wall cap','diffusion_support_union':sorted(support_union),'trials':trials}}
