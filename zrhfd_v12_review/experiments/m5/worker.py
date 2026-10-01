"""One method/query, with progress saved before each approximate diffusion."""
from pathlib import Path
from fractions import Fraction
import argparse
import json
import hashlib
import math
import os
import sys
import time
import traceback
import numpy as np
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.m5.inputs import config, load_topology, target_vertices, metrics, immutable_json, canonical_bytes


def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,set,np.ndarray)):return [clean(v) for v in value]
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,Fraction):return str(value)
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def method_settings(task, frozen):
    dataset=task['dataset'];c=frozen
    key=dataset if dataset in c['datasets'] else 'hyper_synthetic'
    baseline=dict(c['common_baseline'],budget_seconds=c['budgets']['wall_seconds_per_method_query'])
    if task['method'].startswith('hfd_'):baseline.update(c['hfd'])
    elif task['method'].startswith('tlhfd_'):
        baseline.update(c['tlhfd'],iterations=c['datasets'][key]['tl_iterations'],fraction_grid=c['datasets'][key]['tl_fraction_grid'])
    elif task['method'].startswith('clique_acl_'):baseline.update(c['clique_acl'])
    if task['toy']:
        baseline.update(masses=[6.],iterations=6,fraction_grid=[.25],alpha_grid=[.15],max_updates=5000)
    return baseline


def execute(task, directory, frozen=None, backend='pure_python'):
    started=time.perf_counter();c=frozen or config();directory=Path(directory)
    progress=directory/'progress';progress.mkdir(parents=True,exist_ok=True)
    events=[]
    def event(kind, **detail):
        item={'event':kind,'elapsed_seconds':time.perf_counter()-started,**clean(detail)}
        immutable_json(progress/f'{len(events):05d}.json',item);events.append(item)
        print(json.dumps(item,sort_keys=True),flush=True)
    event('worker_started',method=task['method'],query_id=task['query']['query_id'])
    out=None;status='FAILED';exception=None
    try:
        topology_started=time.perf_counter();h,data=load_topology(task);load_seconds=time.perf_counter()-topology_started
        event('topology_loaded',n=h.n,hyperedges=len(h.edges),volume=h.total,input_seconds=load_seconds)
        seed=task['query']['seed_zero_based'];remaining=lambda:max(.001,c['budgets']['wall_seconds_per_method_query']-(time.perf_counter()-started)-.2)
        artifact_directory=str(directory.relative_to(PROJECT)/'native_logs')
        if task['method'] in ['zr_hfd','zh_prov']:
            from zrhfd.hyper import run,Config
            from zrhfd.hyper.diffusion import solve_hypergraph,HyperScores
            from zrhfd.baselines.hfd import solve_hyper
            settings={k:v for k,v in c['zr'].items() if k in Config.__dataclass_fields__}
            settings['objective']='ZH' if task['method']=='zr_hfd' else 'ZH-prov'
            if task['toy']:settings['diffusion_backend']='cvxpy'
            calls=0
            def diffusion(h,seed,mass,**kwargs):
                nonlocal calls
                current=calls;calls+=1;event('diffusion_started',call=current,mass=float(mass),backend=settings['diffusion_backend'])
                if settings['diffusion_backend']=='cvxpy':score,telemetry=solve_hypergraph(h,seed,mass,**kwargs)
                else:
                    raw,telemetry=solve_hyper(h,seed,mass,**kwargs,iterations=c['zr']['native_iterations'],budget_seconds=remaining(),artifact_directory=artifact_directory)
                    if telemetry.get('status')!='COMPLETED':
                        event('diffusion_partial',call=current,telemetry=telemetry)
                        raise TimeoutError('Native diffusion not completed; retained partial telemetry without scoring as converged')
                    raw=np.maximum(np.asarray(raw,dtype=float),0);threshold=kwargs['support_tolerance']*max(1,float(raw.max()));raw[raw<=threshold]=0
                    score=raw.view(HyperScores);score.support=np.flatnonzero(raw>0)
                    telemetry=dict(telemetry,mass=float(mass),support_size=len(score.support),support_volume=float(h.volume(score.support)),precision_mode='author_finite_iteration_approximate',locality_claim=False,support_threshold=threshold)
                event('diffusion_finished',call=current,telemetry=telemetry,support=list(map(int,score.support)))
                # Native telemetry declares full scans; pipeline union is mathematical support only.
                return score,telemetry
            out=run(h,seed,Config(**settings),diffusion=diffusion)
            out['execution_cost_definition']={'global_topology_loaded':True,'global_native_diffusion_scans':not task['toy'],'native_full_vertex_scans_per_call':h.n if not task['toy'] else 0,'native_process_count':calls if not task['toy'] else 0,'native_global_input_conversion_count':calls if not task['toy'] else 0,'native_kernel_seconds_total':sum(t.get('kernel_seconds',0) or 0 for t in out['diffusion_trace']) if not task['toy'] else None,'reported_touched_volume_is_support_union':'support-union telemetry does not certify implementation locality','source_file_conversion_in_native_calls':not task['toy'],'batching_difference':'adaptive ZR starts a fresh author Julia process and reconverts the full hypergraph for each mass; HFD baseline batches its fixed mass grid in one process; outer/runtime costs retain this difference'}
            interval_settings=c.get('interval_certificate',{})
            if interval_settings.get('enabled',False):
                from zrhfd.hyper.interval_certificate import enclose_lower_bound
                enclosure_started=time.perf_counter();numeric=out['certificate'];original_file=directory/'numeric_certificate_before_interval.json'
                immutable_json(original_file,clean(numeric))
                enclosed=enclose_lower_bound(h,numeric,settings['objective'],absolute_tolerance=Fraction(interval_settings['absolute_tolerance_exact']),max_nodes=interval_settings['max_nodes'],wall_seconds=interval_settings['wall_seconds'])
                certificate=dict(numeric,LB_numeric=numeric['LB_R'],LB_numeric_gap=numeric.get('gap'),LB_numeric_status=numeric['certificate_status'],LB_numeric_evaluation=numeric['LB_evaluation'],LB_numeric_file=str(original_file.relative_to(PROJECT)),LB_numeric_file_sha256=hashlib.sha256(original_file.read_bytes()).hexdigest(),interval_enclosure=enclosed)
                if enclosed.get('rigorous_arithmetic',False):
                    selected=Fraction(out['selected_Z_exact']);lower=Fraction(enclosed['lower_exact'])
                    if lower>selected:raise RuntimeError('Rational regional lower bound exceeds exact selected objective')
                    certificate.update(LB_R=enclosed['lower_float'],LB_R_upper=enclosed['upper_float'],LB_R_lower_exact=enclosed['lower_exact'],LB_R_upper_exact=enclosed['upper_exact'],LB_R_width_exact=enclosed['width_exact'],LB_R_target_precision_met=enclosed['stop_reason'] in ['target_width','singleton_domain'],LB_evaluation='Fraction enclosure on exact seeded hull; outward-rounded reported endpoints; see original numerical certificate and interval status',certificate_status='EXACT_HULL_WITH_RATIONAL_NUMERIC_ENCLOSURE',gap=float(selected)-enclosed['lower_float'],gap_using_rational_lower_exact=str(selected-lower))
                else:
                    certificate.update(LB_R_target_precision_met=False,interval_status='UNVERIFIED_OR_UNAVAILABLE; original float LB retained and is not labelled rigorous')
                out['certificate']=certificate;out['runtime_seconds_original_pipeline']=out['runtime_seconds'];out['interval_enclosure_stage_seconds']=time.perf_counter()-enclosure_started;out['runtime_seconds']+=out['interval_enclosure_stage_seconds']
                event('interval_certificate_finished',status=enclosed['status'],width_exact=enclosed.get('width_exact'),target_precision_met=certificate['LB_R_target_precision_met'])
            status='COMPLETED'
        else:
            from zrhfd.baselines.hypergraph import run_hfd,run_tlhfd,run_acl
            methods={'hfd':run_hfd,'tlhfd':run_tlhfd,'clique_acl':run_acl}
            prefix=task['method'].removesuffix('_no_volume').removesuffix('_oracle')
            if prefix=='tlhfd' and backend=='numba':
                from zrhfd.baselines.hyper_tlhfd_numba import run_tlhfd
                methods['tlhfd']=run_tlhfd
            settings=method_settings(task,c);settings.update(budget_seconds=remaining(),artifact_directory=artifact_directory,backend=backend)
            # Truth is read here only for an explicitly named oracle method.
            oracle=float(h.volume(target_vertices(data,task['query']))) if task['method'].endswith('_oracle') else None
            event('algorithm_started',oracle_volume_injected=oracle is not None,config=settings)
            def checkpoint(payload):
                # Callback sees method output only; no target vertices or quality labels.
                event('baseline_progress',payload=payload,truth_used=False)
            out=methods[prefix](h,seed,settings,oracle_volume=oracle,progress=checkpoint)
            metadata=out.get('metadata',{});status=metadata.get('status','COMPLETED')
            if metadata.get('stop') in ['TIMEOUT','query_budget'] or any(t.get('stop') in ['time_budget','max_updates'] for t in metadata.get('trials',[])):
                status='PARTIAL_TIMEOUT' if any(t.get('stop')=='time_budget' for t in metadata.get('trials',[])) or metadata.get('stop') in ['TIMEOUT','query_budget'] else 'PARTIAL_UPDATE_BUDGET'
        if not math.isfinite(float(out['runtime_seconds'])) or out['runtime_seconds']<0:raise FloatingPointError('Nonfinite/negative algorithm runtime')
        if task['method'] in ['zr_hfd','zh_prov'] and any(not math.isfinite(float(out['certificate'][key])) for key in ['LB_R','gap']):
            raise FloatingPointError('Nonfinite numerical certificate; do not sanitize into a claimed completed result')
        contains_seed=seed in out['vertices']
        out['contains_seed']=contains_seed
        if task['method'].startswith('hfd_'):
            out['native_author_seed_omission']=not contains_seed
            out['seed_policy']='original author output retained; omission reported without relabelling source execution as a failure'
        elif not contains_seed:raise RuntimeError('Declared seeded primary/TL/ACL output omitted seed')
        evaluation=metrics(h,out['vertices'],target_vertices(data,task['query']))
        event('offline_evaluation_finished',execution_status=status)
        result={'schema_version':1,'task':task,'status':status,'output':clean(out),'offline_metrics':evaluation,'input_load_seconds':load_seconds,'worker_wall_seconds':time.perf_counter()-started,'formal_measurement':not task['toy'],'truth_contract':'vol(C) injected only in *_oracle; all other truth use is post-output evaluation','scope':'all_or_nothing; general cardinality gate unresolved'}
    except Exception as error:
        status='PARTIAL_TIMEOUT' if isinstance(error,TimeoutError) else 'FAILED';exception={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()}
        print(exception['traceback'],file=sys.stderr,flush=True)
        event('exception',status=status,exception=exception)
        result={'schema_version':1,'task':task,'status':status,'exception':exception,'partial_output':clean(out),'worker_wall_seconds':time.perf_counter()-started,'formal_measurement':not task['toy']}
    immutable_json(directory/'worker_result.json',clean(result))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);args=parser.parse_args()
    request=json.loads(Path(args.request).read_text())
    execute(request['task'],Path(args.request).parent,request['configuration'],request['tl_backend'])


if __name__=='__main__':main()
