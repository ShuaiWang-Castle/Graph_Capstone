"""Offline dev truth diagnostics. Truth never enters the method/pipeline."""
from fractions import Fraction as F
from hashlib import sha256
import time
import numpy as np
from scipy.sparse.csgraph import connected_components
from zrhfd.diffusion import solve_graph

_GRAPH_KEYS={}
_CACHE={}


def graph_key(g):
    ident=id(g)
    if ident not in _GRAPH_KEYS:
        digest=sha256(str(g.n).encode()+g.indptr.tobytes()+g.indices.tobytes()+g.weights.tobytes()).hexdigest()
        _GRAPH_KEYS[ident]=(g,digest)
    return _GRAPH_KEYS[ident][1]


def volume(g,S):return sum(int(round(g.degree[u])) for u in set(S))


def penalty(g,R,T,C):
    C,T,R=set(C),set(T),set(R);a=volume(g,C)
    return F(2*(volume(g,C&T)*volume(g,T-C)+volume(g,C-T)*volume(g,R-C)),int(round(g.total))*a)


def _query_cache(g,seed,sigma):
    key=(graph_key(g),int(seed),float(sigma))
    return _CACHE.setdefault(key,{'graph_key':key[0],'seed':seed,'sigma':sigma,'by_mass':{},'measurements':[]})


def support_at(g,seed,mass,sigma=1e-4,full_score=False):
    cache=_query_cache(g,seed,sigma);key=float(mass).hex();existing=cache['by_mass'].get(key)
    if existing is not None and (not full_score or existing.get('scores') is not None):return existing,True
    started=time.perf_counter();score,telemetry=solve_graph(g,seed,float(mass),sigma=sigma,tolerance=1e-12,max_updates=100000)
    if telemetry['queue_pending'] or telemetry['scaled_kkt_residual']>1e-7:raise RuntimeError('Diagnostic diffusion failed convergence check')
    row={'mass':float(mass),'support':list(map(int,score.support)),'scores':score,'telemetry':telemetry,'measurement_role':'offline dev diagnostic; no headline time','diagnosis_seconds':time.perf_counter()-started,'source':'independent_recompute_same_quadratic_objective'}
    cache['by_mass'][key]=row;cache['measurements'].append(row);return row,False


def _known_supports(g,seed,result,sigma):
    cache=_query_cache(g,seed,sigma)
    for stage in result.get('diffusion_trace',[]):
        support=None
        if stage.get('support_size')==1:support=[seed]
        elif len(stage.get('sweep_vertices',[]))==stage.get('support_size'):support=stage['sweep_vertices']
        if result.get('config',{}).get('region','R-supp')=='R-supp' and result.get('j_star') is not None and stage.get('j')==result['j_star']+1:support=result['region_vertices']
        if support is None:continue
        key=float(stage['mass']).hex()
        if key not in cache['by_mass']:
            row={'mass':float(stage['mass']),'support':list(map(int,support)),'scores':None,'telemetry':stage,'source':'immutable_pipeline_record_support_inferred_exactly_from_size_or_Rsupp','diagnosis_seconds':0.0}
            cache['by_mass'][key]=row;cache['measurements'].append(row)


def coverage_mass(g,seed,C,result):
    C=set(C);sigma=result.get('config',{}).get('sigma',1e-4);_known_supports(g,seed,result,sigma)
    _,labels=connected_components(g.adjacency(),directed=False,return_labels=True)
    if any(labels[u]!=labels[seed] for u in C):return {'status':'NO_FINITE_COVERAGE','reason':'Target contains vertices outside the full-graph seed component','bisections':[]}
    started=time.perf_counter();grid=sorted(set(float(s['mass']) for s in result.get('diffusion_trace',[])));trace=[];low=float(g.degree[seed]);high=None
    def evaluate(m,role):
        row,cached=support_at(g,seed,m,sigma);covered=C<=set(row['support']);entry={'mass':float(m),'covered':covered,'support_size':len(row['support']),'support_volume':volume(g,row['support']),'outside_truth_volume':volume(g,set(row['support'])-C),'cached':cached,'source':row['source'],'role':role,'scaled_kkt_residual':row['telemetry'].get('scaled_kkt_residual'),'solver_backend':row['telemetry'].get('solver_backend')};trace.append(entry);return covered
    for mass in grid:
        if evaluate(mass,'recorded_grid_bracket'):high=mass;break
        low=mass
    if high is None:
        high=max(low*2,3*float(g.degree[seed]),1.0)
        for _ in range(20):
            if evaluate(high,'diagnostic_bracket_extension'):break
            low=high;high*=2
        else:return {'status':'COVERAGE_BRACKET_FAILED','bracket_trace':trace,'diagnosis_seconds':time.perf_counter()-started}
    bracket_initial=[low,high];bisections=[]
    for iteration in range(20):
        if (high-low)/max(1,high)<=1e-4:break
        mid=(low+high)/2;covered=evaluate(mid,'coverage_bisection');bisections.append({'iteration':iteration,'low_before':low,'high_before':high,'mid':mid,'covered':covered})
        if covered:high=mid
        else:low=mid
    row,_=support_at(g,seed,high,sigma);jstar=result.get('j_star');mj=next((float(s['mass']) for s in result.get('diffusion_trace',[]) if s.get('j')==jstar),None) if jstar is not None else None;mn=next((float(s['mass']) for s in result.get('diffusion_trace',[]) if jstar is not None and s.get('j')==jstar+1),None)
    return {'status':'NUMERIC_COVERAGE_BRACKET','m_c_upper':high,'m_c_lower':low,'relative_bracket_width':(high-low)/max(1,high),'relative_tolerance':1e-4,'max_bisections':20,'initial_bracket':bracket_initial,'m_c_over_m_jstar':high/mj if mj else None,'m_c_over_m_jstar_plus1':high/mn if mn else None,'outside_truth_volume_first_covered_upper':volume(g,set(row['support'])-C),'support_size_first_covered_upper':len(row['support']),'bracket_trace':trace,'bisections':bisections,'diagnosis_seconds':time.perf_counter()-started,'precision_scope':'float64 same-objective solver and strict stored positivity; not exact real activation certificate'}


def distribution(values):
    numbers=np.array([float(v) for v in values]);return {'count':len(values),'negative':sum(v<0 for v in values),'zero':sum(v==0 for v in values),'positive':sum(v>0 for v in values),'min':float(numbers.min()) if len(values) else None,'median':float(np.median(numbers)) if len(values) else None,'q05':float(np.quantile(numbers,.05)) if len(values) else None,'q95':float(np.quantile(numbers,.95)) if len(values) else None,'max':float(numbers.max()) if len(values) else None}


def diagnose_graph_query(g,seed,communities,target_index,pipeline_result):
    """Posthoc dev-only diagnostics; does not invoke or modify the pipeline."""
    started=time.perf_counter();C=set(map(int,communities[target_index]));R=set(map(int,pipeline_result['region_vertices']));S=set(map(int,pipeline_result['vertices']));a=volume(g,C);M=int(round(g.total));stats=g.stats(C);c=int(stats['cut']);zc=g.z_exact(C);zs=g.z_exact(S);covered=C<=R;outside=volume(g,R-C)
    rho=max((len(R&set(group))/len(group) for j,group in enumerate(communities) if j!=target_index and len(group)),default=0.0)
    margins=[]
    for u in sorted(C-{seed}):
        d=int(round(g.degree[u]));lo,hi=g.indptr[u:u+2];e=sum(int(round(g.weights[j])) for j in range(lo,hi) if int(g.indices[j]) in C);v=a-d;cut=c-d+2*e;zt=F(cut,v)+F(v,M);pen=F(2*d*outside,M*a);margin=zt-zc-pen
        margins.append({'operation':'delete','vertex':u,'Z_gap_exact':str(zt-zc),'penalty_exact':str(pen),'margin_exact':str(margin),'C_and_T_within_R':covered})
    for u in sorted(R-C):
        d=int(round(g.degree[u]));lo,hi=g.indptr[u:u+2];e=sum(int(round(g.weights[j])) for j in range(lo,hi) if int(g.indices[j]) in C);v=a+d;cut=c+d-2*e;zt=F(cut,v)+F(v,M);pen=F(2*d,M);margin=zt-zc-pen
        margins.append({'operation':'add','vertex':u,'Z_gap_exact':str(zt-zc),'penalty_exact':str(pen),'margin_exact':str(margin),'C_and_T_within_R':covered})
    order=pipeline_result.get('mm_trace',[{}])[-1].get('order',[]) if pipeline_result.get('mm_trace') else [seed]+sorted(R-{seed});prefix_outside=0;numerator=0
    for u in order:
        if u not in C:prefix_outside+=int(round(g.degree[u]))
        else:numerator+=2*int(round(g.degree[u]))*prefix_outside
    prefix=F(numerator,M*a);pen=penalty(g,R,S,C);last=F(2*outside,M);fp={'C_admissible_for_FP':covered,'order':order,'objective_difference_exact':str(zs-zc),'prefix_bound_exact':str(prefix),'penalty_exact':str(pen),'last_bound_exact':str(last),'inequalities_numerically_checked_if_admissible':[zs-zc<=prefix,prefix<=pen,pen<=last] if covered else None,'scope_note':'FP comparison with truth is applicable only when C subset R; otherwise arithmetic is descriptive only'}
    mc=coverage_mass(g,seed,C,pipeline_result)
    failure='H1' if not covered else ('H2' if S!=C else None)
    return {'schema_version':1,'scope':'offline development truth diagnostic; truth never passed into pipeline','seed':seed,'target_index':target_index,'truth_size':len(C),'truth_volume':a,'region_size':len(R),'region_volume':volume(g,R),'C_subset_R':covered,'rho_hat':rho,'outside_truth_volume':outside,'outside_volume_ratio':outside/a,'failure_class':failure,'symmetric_difference':sorted(S^C),'Z_truth_exact':str(zc),'Z_output_exact':str(zs),'FP':fp,'single_step_margins':margins,'single_step_margin_distribution':distribution([F(row['margin_exact']) for row in margins]),'delete_margin_distribution':distribution([F(row['margin_exact']) for row in margins if row['operation']=='delete']),'add_margin_distribution':distribution([F(row['margin_exact']) for row in margins if row['operation']=='add']),'coverage_mass':mc,'diagnosis_seconds':time.perf_counter()-started}


def cache_snapshot():
    rows=[]
    for key,cache in _CACHE.items():
        records=[]
        for row in cache['measurements']:
            records.append({k:v for k,v in row.items() if k!='scores'})
            if row.get('scores') is not None:records[-1]['score_float64_sha256']=sha256(np.asarray(row['scores'],dtype=np.float64).tobytes()).hexdigest()
        rows.append({'graph_key':cache['graph_key'],'seed':cache['seed'],'sigma':cache['sigma'],'measurements':records})
    return rows
