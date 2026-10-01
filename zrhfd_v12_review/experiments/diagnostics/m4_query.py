"""M4 adapter for the unchanged M2 diagnostic API; no method reruns or tuning."""
from contextlib import contextmanager
from fractions import Fraction as F
import hashlib
import importlib.metadata
import json
import math
import time
import uuid
import numpy as np
from experiments.diagnostics import graph_query as api
from experiments.diagnostics.storage import PROJECT,sha,write_json,write_scores

POLICY={'coverage_relative_tolerance':1e-4,'max_bisections':20,'max_bracket_extensions':20,'diffusion_tolerance':1e-12,'diffusion_max_updates':100000,'accepted_scaled_kkt_residual':1e-7,'store_full_recomputed_scores':True,'all_completed_main_queries':True,'quality_filter':None,'method_parameters_modified':False,'test_use':'posthoc description of all fixed completed main outputs, including successes; no tuning or result selection'}


class SupportObserver:
    """Persistent same-objective supports plus pre/post-solve checkpoints.

    The solver receives only graph, seed, mass and frozen numeric parameters.
    Truth enters the external coverage predicate, never its objective or the
    original pipeline. Adaptive masses here are offline root-finding probes.
    """
    def __init__(self,g,seed,sigma,cache_directory,progress):
        self.g=g;self.seed=seed;self.sigma=sigma;self.progress=progress;self.original=api.support_at
        signature={'graph_topology_sha256':api.graph_key(g),'seed':seed,'sigma_hex':float(sigma).hex(),'solver_source_sha256':sha(PROJECT/'zrhfd/diffusion.py'),'graph_source_sha256':sha(PROJECT/'zrhfd/graph.py'),'solver_parameters':{k:POLICY[k] for k in ['diffusion_tolerance','diffusion_max_updates','accepted_scaled_kkt_residual']},'dependency_versions':{p:importlib.metadata.version(p) for p in ['numpy','scipy','numba','llvmlite']}}
        signature_sha=hashlib.sha256(json.dumps(signature,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.directory=cache_directory/signature_sha;self.directory.mkdir(parents=True,exist_ok=True);write_json(self.directory/'signature.json',signature)
        self.references=[];self.new_cpu_seconds=0.;self.new_wall_seconds=0.
    def __call__(self,g,seed,mass,sigma=1e-4,full_score=False):
        if g is not self.g or seed!=self.seed or sigma!=self.sigma:raise RuntimeError('Offline observer query mismatch')
        mass_hex=float(mass).hex();name=hashlib.sha256(mass_hex.encode()).hexdigest();path=self.directory/(name+'.json')
        wall=time.perf_counter();cpu=time.process_time();self.progress('support_probe_started',mass=float(mass),mass_hex=mass_hex,sigma=sigma,truth_in_solver=False)
        if path.exists():
            disk=json.loads(path.read_text())
            if disk['mass_hex']!=mass_hex or disk['mass']!=float(mass):raise RuntimeError('Persistent support mass mismatch')
            row={k:v for k,v in disk.items() if k not in ['score_file','score_file_sha256']};row['scores']=None;row['source']='persistent_independent_recompute_same_quadratic_objective'
            if not math.isfinite(row['telemetry']['scaled_kkt_residual']) or row['telemetry']['scaled_kkt_residual']>POLICY['accepted_scaled_kkt_residual'] or row['telemetry']['queue_pending']:raise RuntimeError('Persistent diagnostic support lacks required convergence')
            if any(not 0<=u<g.n for u in row['support']):raise ValueError('Persistent support vertex outside input')
            if full_score and disk.get('score_file'):
                file=PROJECT/disk['score_file']
                if sha(file)!=disk['score_file_sha256']:raise RuntimeError('Persistent raw score changed')
                row['scores']=np.load(file,allow_pickle=False)
            cached=True
        else:
            row,cached=self.original(g,seed,mass,sigma,full_score)
            # Inferred immutable primary supports remain attributed to that raw
            # record; only genuine independent solves enter the shared cache.
            if row['source']=='independent_recompute_same_quadratic_objective':
                if not np.isfinite(row['scores']).all() or not math.isfinite(row['telemetry']['scaled_kkt_residual']):raise FloatingPointError('Nonfinite diagnostic score/KKT')
                score_file=self.directory/(name+'.measurement_'+str(uuid.uuid4())+'.npy');write_scores(score_file,row['scores'])
                stored={k:v for k,v in row.items() if k!='scores'}
                stored.update(mass_hex=mass_hex,score_file=str(score_file.relative_to(PROJECT)),score_file_sha256=sha(score_file),score_float64_sha256=hashlib.sha256(np.asarray(row['scores'],dtype='<f8').tobytes()).hexdigest(),solver_cpu_seconds=time.process_time()-cpu,solver_wall_seconds=time.perf_counter()-wall,measurement_role='independent offline diagnostic only; no headline method time')
                write_json(path,stored);self.new_cpu_seconds+=stored['solver_cpu_seconds'];self.new_wall_seconds+=stored['solver_wall_seconds']
        residual=row['telemetry'].get('scaled_kkt_residual')
        if not isinstance(residual,(int,float)) or not math.isfinite(residual) or residual>POLICY['accepted_scaled_kkt_residual'] or row['telemetry'].get('queue_pending') is None or row['telemetry']['queue_pending']:raise RuntimeError('Observed diagnostic support lacks required convergence')
        reference={'mass':float(mass),'mass_hex':mass_hex,'support':list(map(int,row['support'])),'support_volume':api.volume(g,row['support']),'source':row['source'],'cached':cached,'scaled_kkt_residual':row['telemetry'].get('scaled_kkt_residual'),'solver_backend':row['telemetry'].get('solver_backend'),'cache_file':str(path.relative_to(PROJECT)) if path.exists() else None,'cache_file_sha256':sha(path) if path.exists() else None,'probe_cpu_seconds':time.process_time()-cpu,'probe_wall_seconds':time.perf_counter()-wall}
        previous=list(self.references);self.references.append(reference);self.progress('support_probe_finished',**reference,truth_in_solver=False)
        U=set(reference['support'])
        for prior in previous:
            V=set(prior['support'])
            if prior['mass']<mass and not V<=U or prior['mass']>mass and not U<=V:raise RuntimeError('Observed float64 supports violate mass ordering; coverage bracket is incomplete')
        return row,cached
    @contextmanager
    def installed(self):
        api.support_at=self
        try:yield self
        finally:api.support_at=self.original


def static_diagnosis(g,seed,communities,target_index,pipeline_result,split):
    if not g.integer_weights:raise ValueError('Exact M4 gap diagnostics require integer-weight input')
    if not 0<=target_index<len(communities) or seed not in communities[target_index]:raise ValueError('Fixed target index/seed mismatch')
    original=api.coverage_mass
    api.coverage_mass=lambda *args,**kwargs:{'status':'NOT_STARTED_OFFLINE_COVERAGE_PROBES'}
    try:diagnosis=api.diagnose_graph_query(g,seed,communities,target_index,pipeline_result)
    finally:api.coverage_mass=original
    diagnosis['base_api_scope']=diagnosis['scope'];diagnosis['scope']='offline '+split+' description of frozen main output; no pipeline rerun, parameter selection or test tuning'
    gap=F(diagnosis['Z_output_exact'])-F(diagnosis['Z_truth_exact']);difference=len(diagnosis['symmetric_difference'])
    activation={'activated':pipeline_result.get('j_act') is not None,'j_act':pipeline_result.get('j_act'),'j_star':pipeline_result.get('j_star'),'m_act':pipeline_result.get('m_act'),'stop_reason':pipeline_result.get('stop_reason'),'recorded_diffusion_stages':len(pipeline_result.get('diffusion_trace',[])),'scope':'immutable primary trace only; no new early-stop causal claim'}
    mechanism='UNACTIVATED' if pipeline_result.get('j_act') is None else diagnosis.get('failure_class')
    diagnosis.update(symmetric_difference_size=difference,Z_output_minus_truth_exact=str(gap),Z_output_minus_truth=float(gap),Z_gap_per_symmetric_difference_exact=str(gap/difference) if difference else None,Z_gap_per_symmetric_difference=float(gap/difference) if difference else None,truth_stats=g.stats(communities[target_index]),split=split,method_parameters_modified=False,primary_activation=activation,failure_mechanism=mechanism)
    return diagnosis


def coverage_observations(mc,seed_degree,pipeline_result):
    covered=[row for row in mc.get('bracket_trace',[]) if row['covered']]
    recorded=[row for row in covered if row['role']=='recorded_grid_bracket']
    extract=lambda row:{'mass':row['mass'],'outside_truth_volume':row['outside_truth_volume'],'support_volume':row['support_volume'],'support_size':row['support_size'],'role':row['role'],'source':row['source'],'scaled_kkt_residual':row['scaled_kkt_residual']}
    extra={'first_observed_coverage':extract(covered[0]) if covered else None,'first_recorded_grid_coverage':extract(recorded[0]) if recorded else None,'final_bisection_upper_coverage':{'mass':mc['m_c_upper'],'outside_truth_volume':mc['outside_truth_volume_first_covered_upper'],'support_size':mc['support_size_first_covered_upper']} if 'm_c_upper' in mc else None,'first_coverage_note':'first observed/recorded-grid supports are distinct from the final refined bisection upper endpoint; only the latter is the reported approximate m_c bracket'}
    if 'm_c_upper' in mc:
        extra['m_c_over_3ds']=mc['m_c_upper']/(3*seed_degree) if seed_degree else None
        extra['m_c_over_m_act']=mc['m_c_upper']/pipeline_result['m_act'] if pipeline_result.get('m_act') else None
    return extra


def complete_diagnosis(g,seed,communities,target_index,pipeline_result,split,cache_directory,progress):
    wall=time.perf_counter();cpu=time.process_time();diagnosis=static_diagnosis(g,seed,communities,target_index,pipeline_result,split)
    progress('static_exact_diagnostics_finished',diagnosis=diagnosis)
    observer=SupportObserver(g,seed,pipeline_result.get('config',{}).get('sigma',1e-4),cache_directory,progress)
    with observer.installed():mc=api.coverage_mass(g,seed,set(communities[target_index]),pipeline_result)
    mc.update(coverage_observations(mc,float(g.degree[seed]),pipeline_result));mc['relative_tolerance_met']=mc.get('relative_bracket_width',float('inf'))<=POLICY['coverage_relative_tolerance'] if mc['status']=='NUMERIC_COVERAGE_BRACKET' else None;diagnosis['coverage_mass']=mc
    total_wall=time.perf_counter()-wall;diagnosis.update(base_static_diagnosis_seconds=diagnosis['diagnosis_seconds'],diagnosis_seconds=total_wall,diagnosis_wall_seconds=total_wall,diagnosis_cpu_seconds=time.process_time()-cpu,support_observation_references=observer.references,new_solver_cpu_seconds=observer.new_cpu_seconds,new_solver_wall_seconds=observer.new_wall_seconds,diagnostic_policy=POLICY)
    return diagnosis
