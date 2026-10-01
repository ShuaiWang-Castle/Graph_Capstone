"""High-accuracy same-objective conductance control, distinct from author HFD."""
import time
from ..diffusion import solve_graph
from ..sweep import level_sweep
from ._common import mass_grid,conductance

def run(graph,seed,config,oracle_volume=None):
    start=time.perf_counter();masses,policy=mass_grid(graph,seed,config,oracle_volume)
    best=[seed];best_phi=conductance(graph,best);trials=[];support=set();frontier=set();partial=False
    deadline=start+float(config.get('budget_seconds',600))
    for mass in masses:
        if time.perf_counter()>=deadline:partial=True;break
        x,telemetry=solve_graph(graph,seed,mass,float(config.get('sigma',1e-4)),
                               float(config.get('diffusion_tolerance',1e-12)),int(config.get('max_updates',20_000_000)))
        if telemetry['queue_pending']:raise RuntimeError('High-accuracy HFD-CD diffusion unfinished; do not score as converged')
        support.update(map(int,x.support))
        for u in x.support:
            frontier.add(int(u));frontier.update(map(int,graph.indices[graph.indptr[u]:graph.indptr[u+1]]))
        try:S,value,trace=level_sweep(graph,x,seed,'phi')
        except ValueError:
            S=[];value=None;trace=[]
        if S and float(value)<best_phi:best,best_phi=S,float(value)
        trials.append({'mass':mass,'conductance_exact':str(value) if value is not None else None,
                       'vertices':S,'diffusion':telemetry,'sweep_blocks':trace,
                       'selected_support':sorted(map(int,x.support))})
    return {'vertices':best,'runtime_seconds':time.perf_counter()-start,'touched_vertices':sorted(frontier),
            'metadata':{'method':'HFD-CD-high-accuracy-conductance-control',
              'identity':'root quadratic coordinate/active-set solver with conductance sweep; not author execution algorithm',
              'objective':'same frozen HFD graph quadratic dual','sigma':config.get('sigma',1e-4),
              'mass_policy':policy,'oracle':oracle_volume is not None,'mass_grid':masses,
              'mass_grid_complete':not partial,'stop':'query_budget' if partial else 'configuration_grid_finished',
              'selection':'minimum seeded tie-block conductance across full fixed mass grid',
              'tie_policy':'exact floating-height equality blocks; no split',
              'diffusion_support_union':sorted(support),'touched_definition':'support and actual one-hop residual frontier read',
              'trials':trials}}
