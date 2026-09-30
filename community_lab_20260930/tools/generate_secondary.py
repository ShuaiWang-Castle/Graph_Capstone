#!/usr/bin/env python3
"""Conditional secondary generators. No algorithm, evaluation or label transfer.

The CLI consumes configs/secondary_generators_v1.json only when its caller has
authorized the registered conditional phase. This file does not inspect gates.
It never changes work/state.json or retries a failed case under a different seed.
"""
from __future__ import annotations
from pathlib import Path
import argparse, collections, datetime, hashlib, itertools, json, math, os, shlex, sys, tempfile, time, traceback
import numpy as np

SCHEMA='secondary-independent-pairs-v1'
def utc():return datetime.datetime.now(datetime.timezone.utc)
def stamp():return utc().isoformat()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def json_hash(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(obj,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
def find_root():
    for directory in Path(__file__).resolve().parents:
        if (directory/'work/state.json').exists() and (directory/'lab/io.py').exists():return directory
    raise RuntimeError('Cannot locate original LAB work/state.json')
def portable(path,root):
    path=Path(path).resolve()
    try:return str(path.relative_to(root))
    except ValueError:return str(path)

class GenerationError(ValueError):
    def __init__(self,message,context=None):super().__init__(message);self.context=context or {}
class DeadlineReached(RuntimeError):
    def __init__(self,message='Original round deadline reached',context=None):super().__init__(message);self.context=context or {}
class RoundBudget:
    def __init__(self,path):
        self.path=Path(path);raw=self.path.read_bytes();self.state_sha256=hashlib.sha256(raw).hexdigest()
        state=json.loads(raw);self.deadline=datetime.datetime.fromisoformat(state['deadline'].replace('Z','+00:00'))
        if self.deadline.tzinfo is None:raise ValueError('Deadline must be timezone-aware')
        self.started_at=state['started_at'];self.checked_at=stamp()
    def remaining(self):return (self.deadline-utc()).total_seconds()
    def check(self):
        if self.remaining()<=0:raise DeadlineReached()
    def metadata(self):return {'original_started_at':self.started_at,'original_deadline':self.deadline.isoformat(),
                              'state_sha256_at_read':self.state_sha256,'state_read_at_utc':self.checked_at,
                              'remaining_seconds_observed':self.remaining(),'deadline_was_reset':False}

def validate_n_seed(n,seed):
    if type(n) is not int or n<2:raise GenerationError('n must be Python int >=2')
    if type(seed) is not int or seed<0:raise GenerationError('seed must be a nonnegative Python int')
def observed_stats(n,edges):
    degree=np.zeros(n,dtype=np.int64)
    for u,v in edges:degree[u]+=1;degree[v]+=1
    return {'n':n,'m':len(edges),'degree_mean':float(degree.mean()),'degree_min':int(degree.min()),
            'degree_max':int(degree.max()),'degree_std':float(degree.std()),'isolated_nodes':int(np.sum(degree==0))},degree
def membership_cover(core,extra,k):
    communities=[[] for _ in range(k)]
    for u,(a,b) in enumerate(zip(core,extra)):
        communities[int(a)].append(u)
        if b>=0:communities[int(b)].append(u)
    return communities
def shared_count(core,extra,k):
    sizes=np.bincount(core,minlength=k)+np.bincount(extra[extra>=0],minlength=k)
    twice=collections.Counter(tuple(sorted((int(core[u]),int(extra[u])))) for u in np.flatnonzero(extra>=0))
    # Any pair shares two groups iff its nodes have the same two memberships.
    count=sum(int(s)*(int(s)-1)//2 for s in sizes)-sum(s*(s-1)//2 for s in twice.values())
    return count,sizes
def shared_row(core,extra,u):
    vcore=core[u+1:];vextra=extra[u+1:]
    mask=(vcore==core[u])|(vextra==core[u])
    if extra[u]>=0:mask=mask|(vcore==extra[u])|(vextra==extra[u])
    return mask
def draw_pairs(n,rng,probability_row,check_deadline=None):
    edges=[];expected_degrees=np.zeros(n,dtype=np.float64);drawn=0
    try:
        for u in range(n-1):
            if check_deadline:check_deadline()
            p=np.asarray(probability_row(u),dtype=np.float64)
            if p.shape!=(n-u-1,) or not np.isfinite(p).all() or np.any((p<0)|(p>1)):
                raise GenerationError('Invalid independent-pair probability row')
            expected_degrees[u]+=float(p.sum());expected_degrees[u+1:]+=p
            selected=np.flatnonzero(rng.random(n-u-1)<p)+u+1
            edges.extend((u,int(v)) for v in selected);drawn+=n-u-1
    except (DeadlineReached,GenerationError,KeyboardInterrupt) as exc:
        if not hasattr(exc,'context'):exc.context={}
        exc.context.update(partial_graph={'schema_version':1,'n':n,'edges':[list(e) for e in edges]},
                           processed_source_rows=u,drawn_pairs=drawn,partial_expected_degrees=expected_degrees.tolist())
        raise
    return edges,expected_degrees,drawn

def generate_overlapping_sbm(n,k,overlap_fraction,mu,mean_degree,seed,check_deadline=None):
    validate_n_seed(n,seed)
    if type(k) is not int or k<2 or n%k:raise GenerationError('Balanced core requires integer k>=2 dividing n')
    if not 0<=overlap_fraction<=1 or not 0<=mu<=1 or not 0<mean_degree<n:
        raise GenerationError('Invalid overlap/mu/mean degree')
    if check_deadline:check_deadline()
    rng=np.random.Generator(np.random.PCG64(seed))
    core=np.repeat(np.arange(k,dtype=np.int64),n//k)[rng.permutation(n)]
    extra=np.full(n,-1,dtype=np.int64);overlap_count=round(n*overlap_fraction)
    selected=rng.choice(n,size=overlap_count,replace=False)
    choices=rng.integers(0,k-1,size=overlap_count,dtype=np.int64)
    extra[selected]=choices+(choices>=core[selected])
    cover=membership_cover(core,extra,k);S,sizes=shared_count(core,extra,k);Q=n*(n-1)//2;E=n*mean_degree/2
    latent={'cover':{'communities':cover,'labels_complete':True,'source':SCHEMA,'planted_k':k},
            'core_membership':core.tolist(),'extra_membership':extra.tolist()}
    meta={'kind':'overlapping_independent_pair_Bernoulli_SBM','n':n,'k':k,'seed':seed,
          'core_size':n//k,'overlap_fraction_requested':overlap_fraction,'actual_overlap_nodes':overlap_count,
          'group_sizes':sizes.tolist(),'S_shared_unordered_pairs':S,'Q_all_unordered_pairs':Q,
          'target_expected_edges':E,'target_expected_mean_degree':mean_degree,
          'global_expected_external_edge_fraction':mu,
          'probability_definition':'shared: (1-mu)*(n*mean_degree/2)/S; unshared: mu*(n*mean_degree/2)/(Q-S)',
          'warning':'Global expected external fraction is not LFR per-node native mu; graph degree is stochastic, not fixed or hard-capped.'}
    context={'latent':latent,'metadata':meta}
    if not 0<S<Q:raise GenerationError('Invalid S or Q-S denominator; no retry',context)
    p_shared=(1-mu)*E/S;p_unshared=mu*E/(Q-S)
    meta.update(p_shared=p_shared,p_unshared=p_unshared,
                expected_shared_edges=S*p_shared,expected_external_edges=(Q-S)*p_unshared)
    if not all(math.isfinite(p) and 0<=p<=1 for p in [p_shared,p_unshared]):
        raise GenerationError('Probability outside [0,1]; no clipping, retry or seed replacement',context)
    try:edges,expected_degrees,drawn=draw_pairs(n,rng,lambda u:np.where(shared_row(core,extra,u),p_shared,p_unshared),check_deadline)
    except (DeadlineReached,GenerationError,KeyboardInterrupt) as exc:exc.context.update(context);raise
    shared_edges=sum(bool(core[u]==core[v] or core[u]==extra[v] or
                          (extra[u]>=0 and (extra[u]==core[v] or extra[u]==extra[v]))) for u,v in edges)
    stats,degrees=observed_stats(n,edges)
    meta.update(actual_shared_edges=shared_edges,actual_external_edges=len(edges)-shared_edges,
                observed_external_edge_fraction=(len(edges)-shared_edges)/len(edges) if edges else None,
                independent_pair_draws=drawn,actual_expected_degree_mean=float(expected_degrees.mean()),
                expectation_degree_sum=float(expected_degrees.sum()))
    return {'graph':{'schema_version':1,'n':n,'edges':[list(e) for e in edges]},'latent':latent,'metadata':meta,
            'observed_stats':stats,'observed_degrees':degrees,'actual_expected_degrees':expected_degrees}

def clipped_rank_weights(n,mean_degree,min_degree=1.,max_degree=50.):
    if type(n) is not int or n<2 or not all(math.isfinite(x) for x in [mean_degree,min_degree,max_degree]):
        raise GenerationError('Invalid clipped-rank parameters')
    if not 0<min_degree<=mean_degree<=max_degree:raise GenerationError('Target mean must lie within positive clip bounds')
    rank=np.arange(1,n+1,dtype=np.float64)
    lo=0.;hi=float(max_degree*n)
    if mean_degree==min_degree:c=0.;iterations=0
    elif mean_degree==max_degree:c=hi;iterations=0
    else:
        for iterations in range(1,201):
            c=(lo+hi)/2.;m=float(np.clip(c/rank,min_degree,max_degree).mean())
            if m<mean_degree:lo=c
            else:hi=c
            if hi==lo or abs(m-mean_degree)<=1e-12:break
        c=(lo+hi)/2.
        # If the last tested midpoint already met the tolerance, retain it.
        if abs(m-mean_degree)<=1e-12:c=(lo if m<mean_degree else hi)
    weights=np.clip(c/rank,min_degree,max_degree)
    if abs(float(weights.mean())-mean_degree)>2e-11:raise GenerationError('Deterministic bisection mean tolerance failed')
    return weights,{'c':c,'bisection_iterations':iterations,'rank_order_weight_mean':float(weights.mean()),
                    'minimum_weight_bound':min_degree,'maximum_weight_bound':max_degree,'bisection_tolerance':1e-12}
def generate_degree_only(n,mean_degree,seed,min_degree=1.,max_degree=50.,check_deadline=None):
    validate_n_seed(n,seed)
    if check_deadline:check_deadline()
    ordered,calibration=clipped_rank_weights(n,mean_degree,min_degree,max_degree)
    rng=np.random.Generator(np.random.PCG64(seed));weights=ordered[rng.permutation(n)];W=float(weights.sum())
    meta={'kind':'independent_pair_expected_degree_Bernoulli','n':n,'seed':seed,
          'parameter_weight_mean_target':mean_degree,'parameter_weight_mean':float(weights.mean()),
          'sum_parameter_weights':W,'calibration':calibration,
          'probability_definition':'p_uv=min(w_u*w_v/sum(w),1) for every u<v; no loops',
          'has_complete_recovery_labels':False,'strict_recovery_F1_eligible':False,
          'warning':'Weights are expected-degree parameters; removed diagonal and clipping affect actual degree expectations. Realized degrees are stochastic and not capped at max(weight).'}
    latent={'expected_degree_parameters':weights.tolist()};context={'latent':latent,'metadata':meta}
    try:edges,actual_expected,drawn=draw_pairs(n,rng,lambda u:np.minimum(weights[u]*weights[u+1:]/W,1.),check_deadline)
    except (DeadlineReached,GenerationError,KeyboardInterrupt) as exc:exc.context.update(context);raise
    stats,degrees=observed_stats(n,edges)
    meta.update(independent_pair_draws=drawn,actual_expected_edges=float(actual_expected.sum()/2),
                actual_expected_degree_mean=float(actual_expected.mean()),actual_expected_degree_max=float(actual_expected.max()))
    return {'graph':{'schema_version':1,'n':n,'edges':[list(e) for e in edges]},'latent':latent,'metadata':meta,
            'observed_stats':stats,'observed_degrees':degrees,'actual_expected_degrees':actual_expected}

def expand_protocol(protocol):
    alt=protocol['alternative'];null=protocol['degree_only']
    if alt['kind']!='overlapping_independent_pair_Bernoulli_SBM' or null['kind']!='independent_pair_expected_degree_Bernoulli':raise GenerationError('Unexpected registered generator kinds')
    if alt['community_count_policy']!='n/50' or alt['overlap_memberships']!=2:raise GenerationError('Unexpected planted membership policy')
    cases=[]
    for n,o,mu,seed in itertools.product(alt['n'],alt['overlap_fraction'],alt['global_expected_external_edge_fraction'],alt['graph_seeds']):
        if type(n) is not int or n%50:raise GenerationError('Official protocol requires n/50 integer, cores exactly50')
        cases.append({'case_id':f'pair_sbm_n{n}_o{round(o*100):02d}_mu{round(mu*100):02d}_s{seed}',
                      'generator_kind':alt['kind'],'n':n,'k':n//50,'overlap_fraction':o,'mu':mu,
                      'mean_degree':alt['expected_mean_degree'],'seed':seed,'information_panel':'oracle_K',
                      'strict_recovery_F1_eligible':True})
    for n,seed in itertools.product(null['n'],null['graph_seeds']):
        if type(n) is not int or n%50:raise GenerationError('Official null requires predeclared fixed n/50 capacity')
        cases.append({'case_id':f'degree_null_n{n}_s{seed}','generator_kind':null['kind'],'n':n,'fixed_k':n//50,
                      'mean_degree':null['expected_mean_degree'],'min_degree':null['minimum_expected_degree'],
                      'max_degree':null['expected_max_degree'],'seed':seed,'information_panel':'fixed_K_null_diagnostic',
                      'strict_recovery_F1_eligible':False})
    if len({c['case_id'] for c in cases})!=len(cases):raise GenerationError('Duplicate registered case_id')
    return cases

def save_latent(directory,latent,root):
    hashes={};paths={}
    if 'cover' in latent:
        p=directory/'evaluation_only/cover.json';write_json(p,latent['cover']);paths['truth']=portable(p,root)
        hashes['cover_sha256']=sha(p);hashes['truth_sha256']=hashes['cover_sha256']
        p=directory/'evaluation_only/membership_assignment.json'
        write_json(p,{k:latent[k] for k in ['core_membership','extra_membership']});hashes['membership_assignment_sha256']=sha(p)
    if 'expected_degree_parameters' in latent:
        p=directory/'generation_metadata/expected_degree_parameters.json';write_json(p,{'node_ids':'array index','weights':latent['expected_degree_parameters']})
        paths['degree_parameter_vector']=portable(p,root);hashes['degree_parameter_vector_sha256']=sha(p)
    return paths,hashes
def save_generated_artifacts(directory,generated,case,record,root):
    """Standard catalog integration, callable with small direct-function fixtures."""
    if case['strict_recovery_F1_eligible']!=('cover' in generated['latent']):
        raise GenerationError('Planted-label eligibility differs from latent artifacts')
    graph_path=directory/'graph.json';write_json(graph_path,generated['graph'])
    record.update(graph=portable(graph_path,root),graph_sha256=sha(graph_path),n=case['n'],m=len(generated['graph']['edges']),
                  observed_stats=generated['observed_stats'],metadata=generated['metadata'],status='GENERATED')
    paths,hashes=save_latent(directory,generated['latent'],root);record.update(paths);record.update(hashes)
    if not case['strict_recovery_F1_eligible']:
        for key in ['truth','cover_sha256','truth_sha256']:record.pop(key,None)
    write_json(directory/'generation_metadata/degree_vectors.json',{'observed_degrees':generated['observed_degrees'].tolist(),
               'actual_expected_degrees_from_pair_probabilities':generated['actual_expected_degrees'].tolist()})
    record['degree_vectors_sha256']=sha(directory/'generation_metadata/degree_vectors.json')
    record.setdefault('warnings',[]).append(generated['metadata']['warning'])
    return record
def save_catalogs(output,records):
    write_json(output/'catalog.json',records)
    write_json(output/'catalog_planted.json',[r for r in records if r['strict_recovery_F1_eligible']])
    write_json(output/'catalog_degree_only.json',[r for r in records if not r['strict_recovery_F1_eligible']])
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--split',choices=['secondary'],default='secondary')
    parser.add_argument('--validate-only',action='store_true',help='Schema/case plan only; never generate any graph')
    args=parser.parse_args();root=find_root();output=Path(args.output).resolve();protocol_path=Path(args.protocol).resolve()
    protocol=json.loads(protocol_path.read_text());cases=expand_protocol(protocol);budget=RoundBudget(root/'work/state.json')
    source_sha=sha(__file__);protocol_sha=sha(protocol_path)
    runtime={'numpy':np.__version__,'python':sys.version,'numpy_bit_generator':'PCG64','schema':SCHEMA,
             'generator_source':portable(__file__,root),'generator_source_sha256':source_sha,'protocol_sha256':protocol_sha,
             'actual_command_argv':[sys.executable]+sys.argv,'split':args.split,'budget':budget.metadata()}
    output.mkdir(parents=True,exist_ok=True)
    if args.validate_only:
        write_json(output/'protocol_validation.json',{'runtime':runtime,'cases':cases,'graph_generation_performed':False})
        print(json.dumps({'validated_cases':len(cases),'generated_graphs':0,'remaining_seconds':budget.remaining()}));return
    records=[]
    for case in cases:
        directory=output/'attempts'/case['case_id']/(protocol_sha[:12]+'_'+source_sha[:12])
        result_path=directory/'result.json'
        if result_path.exists():
            prior=json.loads(result_path.read_text())
            if prior['runtime']['protocol_sha256']!=protocol_sha or prior['runtime']['generator_source_sha256']!=source_sha:raise GenerationError('Existing attempt signature mismatch')
            if prior['runtime']['numpy']!=np.__version__ or prior['runtime']['python']!=sys.version:raise GenerationError('Resume dependency version mismatch; do not mix generator environments')
            for key in ['graph','truth','degree_parameter_vector']:
                if prior.get(key):
                    p=Path(prior[key]);p=p if p.is_absolute() else root/p
                    hk={'graph':'graph_sha256','truth':'cover_sha256','degree_parameter_vector':'degree_parameter_vector_sha256'}[key]
                    if sha(p)!=prior[hk]:raise GenerationError('Existing generated artifact changed: '+key)
            records.append(prior);continue  # Failed attempts also remain; never silently retry.
        directory.mkdir(parents=True,exist_ok=True)
        rec={'case_id':case['case_id'],'split':args.split,'generator_kind':case['generator_kind'],'seed':case['seed'],
             'requested_n':case['n'],'n':case['n'],'m':None,'config':case,'config_sha256':json_hash(case),'runtime':runtime,
             'attempt_started_utc':stamp(),'graph':None,'graph_sha256':None,
             'observed_stats':None,'warnings':[],'strict_recovery_F1_eligible':case['strict_recovery_F1_eligible'],
             'information_panel':case['information_panel']}
        write_json(directory/'config.json',case);write_json(directory/'command_and_runtime.json',runtime)
        begin=time.perf_counter();was_interrupted=False
        try:
            budget.check()
            if case['generator_kind']=='overlapping_independent_pair_Bernoulli_SBM':
                generated=generate_overlapping_sbm(case['n'],case['k'],case['overlap_fraction'],case['mu'],case['mean_degree'],case['seed'],budget.check)
                rec['oracle_k']=case['k']
            else:
                generated=generate_degree_only(case['n'],case['mean_degree'],case['seed'],case['min_degree'],case['max_degree'],budget.check)
                rec['predeclared_fixed_k']=case['fixed_k']
            save_generated_artifacts(directory,generated,case,rec,root)
        except (Exception,KeyboardInterrupt) as exc:
            was_interrupted=isinstance(exc,KeyboardInterrupt)
            context=getattr(exc,'context',{});rec.update(status='INTERRUPTED' if was_interrupted else 'DEADLINE_INTERRUPTED' if isinstance(exc,DeadlineReached) else 'GENERATION_ERROR',
                                                        error=repr(exc),traceback=traceback.format_exc(),metadata=context.get('metadata'))
            if context.get('latent'):
                paths,hashes=save_latent(directory,context['latent'],root);rec.update(paths);rec.update(hashes)
            if context.get('partial_graph'):
                p=directory/'partial_graph_NOT_COMPLETE.json';write_json(p,context['partial_graph'])
                rec.update(partial_graph=portable(p,root),partial_graph_sha256=sha(p),
                           partial_edge_count=len(context['partial_graph']['edges']),processed_source_rows=context.get('processed_source_rows'),
                           partial_drawn_pairs=context.get('drawn_pairs'))
            rec['warnings'].append('Failure retained; no seed replacement, probability clipping or retry. Partial graphs are not complete samples.')
        rec.update(attempt_finished_utc=stamp(),remaining_seconds_at_finish=budget.remaining(),
                   generation_attempt_elapsed_seconds=time.perf_counter()-begin)
        write_json(result_path,rec);records.append(rec)
        save_catalogs(output,records)
        if was_interrupted or rec['status']=='DEADLINE_INTERRUPTED':
            (output/'RESUME.md').write_text('# Secondary generation resume\n\nOriginal deadline: '+budget.deadline.isoformat()+
                '\n\nLast attempt: '+case['case_id']+' / '+rec['status']+
                '\n\nState is saved; failed/interrupted records are not silently retried. After inspecting the retained attempt, the same command resumes only unseen cases without changing the original deadline:\n\n```bash\n'+
                shlex.join([sys.executable]+sys.argv)+'\n```\n')
            break
    save_catalogs(output,records)
    write_json(output/'generation_manifest.json',{'runtime':runtime,'planned_cases':len(cases),'recorded_attempts':len(records),
        'unattempted_case_ids':[c['case_id'] for c in cases if c['case_id'] not in {r['case_id'] for r in records}],
        'status_counts':dict(collections.Counter(r['status'] for r in records)),
        'remaining_seconds_at_finish':budget.remaining(),'labels_are_offline_only':True,'null_strict_F1_eligible':False})
    print(json.dumps({'attempts':len(records),'statuses':dict(collections.Counter(r['status'] for r in records)),'remaining_seconds':budget.remaining()}))
    if any(r['status']!='GENERATED' for r in records):raise SystemExit(1)
if __name__=='__main__':main()
