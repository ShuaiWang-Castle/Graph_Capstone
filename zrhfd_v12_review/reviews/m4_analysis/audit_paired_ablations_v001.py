"""Offline stdlib audit and paired development-ablation statistics.

The fixed 18 variants x 56 queries are joined to those same queries in the
already audited original main-dev cohort. This subset is not the registered
336-query region decision. No test quality is read, no solver/NumPy is imported,
no scientific gate is decided, and stage-separated costs remain descriptive.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
SELF='reviews/m4_analysis/audit_paired_ablations_v001.py'
ORDINARY_AUDITOR='reviews/m4_analysis/audit_actual_ordinary_v001.py'
ORDINARY_AUDITOR_SHA='d987e0f7d9f655adf80ce96f197022838025e94fc9cbf9f99d3d1f6882a7f80c'
MAIN_AUDIT='reviews/m4_analysis/actual_dev_v001/receipt.json'
MAIN_AUDIT_SHA='9a8142ffeca08caf84db0c53fbfb5196db379a73dd468c0b49570fd10b331a9a'
RUN='results/m4/dev_ablations_v12_002'
MANIFEST_SHA='87dd60d7acac6a92c5033e2ec271b0144faa0f706825fbe89c0290f916ed87f6'
MAIN='results/m4/dev_main_v12_002'
MAIN_SHA='ae8e1b57d465673c1ac14112e3e9ec13a1ba2b5166b0872d82c7a5d28ae8df3e'
VARIANTS=('R-cap-0.25','R-cap-0.5','R-cap-1','supp-jstar','supp-jstar+2','full','patience-2','ZR-mact','sqrt2-grid','fixed-grid','ZR-budgetM','ordering-bfs','ordering-random','multi-start','diffusion-TL-star','no-refinement','hull-best','conductance-sweep')
METRICS=('F1_difference','Z_difference','touched_over_output_difference','wrapper_seconds_difference','wrapper_seconds_ratio')
REPLICATES=10000
SEED=20261005


def load_helpers():
    path=ROOT/ORDINARY_AUDITOR
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=ORDINARY_AUDITOR_SHA:
        raise ValueError('Independent audited helper source differs')
    spec=importlib.util.spec_from_file_location('independent_ordinary_ablation_helpers',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def read_gzip(ev,name):
    path=ev.bind(name)
    with gzip.open(path,'rt') as stream:
        return json.loads(stream.read(),parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON '+value)))


def validate_started(ev,helpers,job,job_name):
    prefix=str(Path(job['result_path']).parent.parent/'logs'/job['task'])
    started=ev.read(prefix+'.started.json')
    require=helpers.require
    require(started['status']=='STARTED' and started['task']==job['task'] and started['job_sha256']==ev.files[job_name],'Started/request job identity differs')
    command=[str(ev.root/'.venv/bin/python'),'experiments/worker.py','--job',job_name]
    require(started['actual_argv']==command and started['cwd']==str(ev.root) and started['thread_environment']==helpers.THREADS,'Started command/thread identity differs')
    ev.bind(prefix+'.stdout.log');ev.bind(prefix+'.stderr.log')
    return prefix,command


def worker(ev,h,job,job_name,graph,main_audit=None):
    """Every planned job retains its status; only completed covers get quality."""
    require,compare=h.require,h.compare;q=job['query'];name=job['result_path'];path=ev.path(name);failure_path=path.with_suffix('.failure.json')
    record=read_gzip(ev,name) if path.exists() else {};failure=ev.read(str(failure_path.relative_to(ev.root))) if failure_path.exists() else {}
    status=failure.get('status',record.get('status','NOT_RUN'));completed=status=='COMPLETED' and record.get('completion_claim') is True
    row={'task':job['task'],'case_id':q['case_id'],'query_index':q['query_index'],'seed':q['seed'],'status':status,'completion_claim':completed,'raw_path':name if record else None,'raw_sha256':ev.files.get(name),'F1':None,'precision':None,'recall':None,'volume':None,'cut':None,'Z':None,'Z_exact':None,'phi':None,'components':None,'hull_F1':None,'touched_volume':None,'touched_over_output':None,'wrapper_seconds':None,'observed_not_completion_seconds':failure.get('wall_seconds_observed_not_completion',record.get('outer_wall_seconds'))}
    if record or failure or ev.path(str(Path(name).parent.parent/'logs'/job['task'])+'.started.json').exists():
        prefix,command=validate_started(ev,h,job,job_name)
        if failure:
            require(failure['task']==job['task'] and failure['job']==job_name and failure['command']==command and failure['completion_claim'] is False,'Failure terminal identity differs')
            require(failure['partial_result_present']==bool(record) and failure['stdout_path']==prefix+'.stdout.log' and failure['stderr_path']==prefix+'.stderr.log','Failure/log identity differs')
    checkpoint=ev.path(name+'.checkpoint.json')
    if checkpoint.exists():
        cp=ev.read(str(checkpoint.relative_to(ev.root)))
        require(cp['task']==job['task'] and cp['source_sha256']==job['source_sha256'] and cp['partial_not_convergence'] is True,'Checkpoint source identity differs')
    if not record:
        return row
    for key,value in {'task':job['task'],'method':job['method'],'setting':job['setting'],'seed':q['seed'],'configuration':job['configuration'],'protocol_sha256':job['protocol_sha256'],'source_sha256':job['source_sha256'],'implementation_exact_cut_backend':'prepared_region_workspace','measurement_role':'formal_cpu_serial','command':['.venv/bin/python','experiments/worker.py','--job',job_name],'input':{k:v for k,v in q.items() if k not in ('truth_vertices','communities')}}.items():
        require(record.get(key)==value,'Raw source/config/input identity differs: '+key)
    require(record['truth_in_method_path'] is False and record['oracle_volume'] is None,'Ablation/main dev must not use oracle volume')
    if main_audit is not None:
        require(main_audit['validated_files'].get(name)==ev.files[name],'Matched base raw differs from accepted independent audit')
    if not completed:
        return row
    result=record['result'];selected=graph.vertices(result['vertices']);truth=graph.vertices(q['truth_vertices']);primary=h.quality(selected,truth);stats=graph.stats(selected)
    for key,value in primary.items():compare(record['evaluation'][key],value,'Independent raw '+key)
    h.stats_match(record['output_stats'],stats,'Independent raw output stats');h.stats_match(record['evaluation']['truth_stats'],graph.stats(truth),'Independent truth stats')
    if 'stats' in result:h.stats_match(result['stats'],stats,'Independent result stats')
    require(record['components']==graph.components(selected),'Independent component count differs')
    require(record['output_contains_seed']==(q['seed'] in selected),'Output seed disclosure differs')
    hull=h.certificate_check(graph,result,selected,q['seed'])
    hull_f1=None
    if hull is not None:
        hull_quality=h.quality(hull,truth);hull_f1=hull_quality['F1']
        for key,value in hull_quality.items():compare(record['hull_best_evaluation'][key],value,'Independent primary hull '+key)
    touched=result.get('touched_vertices')
    touched_volume=sum(graph.degree[v] for v in graph.vertices(touched)) if isinstance(touched,list) else None
    compare(record.get('touched_volume'),touched_volume,'Independent touched degree-volume')
    row.update(primary);row.update({key:stats[key] for key in ('volume','cut','Z','Z_exact','phi')})
    row.update(components=record['components'],hull_F1=hull_f1,touched_volume=touched_volume,touched_over_output=touched_volume/stats['volume'] if touched_volume is not None and stats['volume'] else None,wrapper_seconds=record['outer_wall_seconds'])
    require(math.isfinite(row['wrapper_seconds']) and row['wrapper_seconds']>=0,'Invalid completed wrapper timer')
    return row


def percentile(values,q):
    values=sorted(values);position=(len(values)-1)*q;lower=math.floor(position);upper=math.ceil(position)
    return values[lower]+(values[upper]-values[lower])*(position-lower)


def bootstrap_pairs(rows):
    """Draw matched pairs together; do not impute missing outcomes as zero."""
    groups=defaultdict(list)
    for row in rows:
        if row['pair_completed']:groups[row['case_id']].append(row)
    ordered=[groups[k] for k in sorted(groups)];rng=random.Random(SEED)
    means={metric:[] for metric in METRICS};medians={metric:[] for metric in METRICS}
    if ordered:
        for _ in range(REPLICATES):
            sample=[]
            for _ in range(len(ordered)):
                group=ordered[rng.randrange(len(ordered))]
                sample.extend(group[rng.randrange(len(group))] for _ in range(len(group)))
            for metric in METRICS:
                values=[r[metric] for r in sample if r[metric] is not None]
                if values:means[metric].append(statistics.fmean(values));medians[metric].append(statistics.median(values))
    output={}
    for metric in METRICS:
        valid=[r for r in rows if r['pair_completed'] and r[metric] is not None]
        values=[r[metric] for r in valid]
        output[metric]={'paired_metric_queries':len(valid),'paired_metric_graphs':len({r['case_id'] for r in valid}),'mean':statistics.fmean(values) if values else None,'median':statistics.median(values) if values else None,'mean_percentile_95_CI':[percentile(means[metric],q) for q in (.025,.975)] if means[metric] else None,'median_percentile_95_CI':[percentile(medians[metric],q) for q in (.025,.975)] if medians[metric] else None,'successful_bootstrap_draws':len(means[metric]),'replicates':REPLICATES,'seed':SEED,'sampler':'stdlib random.Random MT19937; independent draw stream, not NumPy PCG64 interval reproduction','scope':'Conditional on completed matched pairs within frozen 56-query dev subset; missing outcomes remain in full denominator'}
    return output


def analyze():
    h=load_helpers();ev=h.Evidence(ROOT);require,compare=h.require,h.compare;started=time.perf_counter();errors=[];ablations=[];baselines=[];pairs=[]
    ev.bind(SELF);source_sha=ev.files[SELF];ev.bind(ORDINARY_AUDITOR,ORDINARY_AUDITOR_SHA)
    manifest=ev.read(RUN+'/manifest.json',MANIFEST_SHA);main=ev.read(MAIN+'/manifest.json',MAIN_SHA)
    main_audit=ev.read(MAIN_AUDIT,MAIN_AUDIT_SHA);h.verify_audit_receipt(ev.path(MAIN_AUDIT),root=ROOT,run_name=MAIN,verify_files=False)
    require(main_audit['auditor_source_sha256']==ORDINARY_AUDITOR_SHA and main_audit['completed']==4032,'Base independent cohort audit differs')
    reference=ev.read(h.REFERENCE,h.REFERENCE_SHA);base_config=next(t['configuration'] for t in reference['first_query_templates'] if t['split']=='dev' and t['method']=='zrhfd')
    snapshot=ev.read(h.SNAPSHOT+'/receipt.json',h.SNAPSHOT_RECEIPT_SHA)
    require(manifest['phase']=='ablations' and len(manifest['jobs'])==1008 and len(set(manifest['jobs']))==1008,'Frozen ablation census differs')
    require(manifest['source_sha256']==main['source_sha256']==snapshot['source_sha256'] and len(manifest['source_sha256'])==27,'Frozen 27-source scope differs')
    require(manifest['catalog_sha256']==main['catalog_sha256'] and manifest['protocol_sha256']==main['protocol_sha256'] and manifest['resources']==main['resources'] and manifest['implementation']==main['implementation'],'Ablation/main protocol/input/implementation differs')
    for name,digest in manifest['source_sha256'].items():ev.bind(name,digest);ev.bind(h.SNAPSHOT+'/'+name,digest)
    for name,digest in manifest['runtime_sha256'].items():ev.bind(name,digest);ev.bind(h.SNAPSHOT+'/'+name,digest)
    require(manifest['runtime_sha256']==main['runtime_sha256'] and manifest['dependency_versions_sha256']==main['dependency_versions_sha256'],'Runtime/dependency lock differs')
    ev.bind('provenance/dependency_versions.txt',manifest['dependency_versions_sha256'])
    ev.bind(h.SNAPSHOT+'/provenance/dependency_versions.txt',manifest['dependency_versions_sha256'])
    tree=ast.parse(ev.path('experiments/ablations.py').read_text())
    declared=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NAMES' for t in n.targets))
    require(tuple(declared)==VARIANTS,'Registered variant list differs')
    catalog=ev.read('data/dev/catalog_v12.json',manifest['catalog_sha256']);inventory={}
    for case in catalog['cases']:
        for pathkey,hashkey in (('graph_path','graph_sha256'),('truth_path','truth_sha256'),('queries_path','queries_sha256')):ev.bind(case[pathkey],case[hashkey])
        communities=ev.read(case['truth_path'])['communities'];queries=ev.read(case['queries_path'])['queries']
        for qi,q in enumerate(queries[:2]):inventory[(case['case_id'],qi)]={**case,'query_index':qi,'seed':q['seed'],'community_index':q['community_index'],'truth_vertices':communities[q['community_index']],'communities':communities}
    require(len(catalog['cases'])==28 and len(inventory)==56,'Fixed first-two-query subset differs')
    summary=ev.read(RUN+'/summary.json');csv_path=ev.bind(RUN+'/query_results.csv');ev.bind(RUN+'/quality_cost_summary.csv')
    require(summary['run_manifest_sha256']==MANIFEST_SHA and summary['cohort_origin']=='ORIGINAL_FROZEN_COHORT','Ablation summary identity differs')
    for name,digest in summary['derived_view_sha256'].items():ev.bind(RUN+'/'+name,digest)
    with csv_path.open(newline='') as stream:csv_rows=list(csv.DictReader(stream))
    require(len(csv_rows)==1008 and len({r['task'] for r in csv_rows})==1008,'Derived ablation CSV task census differs')
    csv_by_task={r['task']:r for r in csv_rows};base_rows={};seen=set();graph=None;last_graph=None;raw_hashes={}
    for key,q in inventory.items():
        task=f"{q['case_id']}_q{q['query_index']:02d}_main";name=MAIN+'/jobs/'+task+'.json';job=ev.read(name)
        require(main_audit['validated_files'].get(name)==ev.files[name],'Matched base job differs from accepted audit')
        require(job['query']==q and job['configuration']==base_config,'Matched base query/config differs')
        if last_graph!=q['graph_path']:graph=h.IndependentGraph(ev.read(q['graph_path'],q['graph_sha256']));last_graph=q['graph_path']
        row=worker(ev,h,job,name,graph,main_audit);require(row['completion_claim'],'Previously complete base is now incomplete')
        baselines.append(row);base_rows[key]=row
    for name in manifest['jobs']:
        job=ev.read(name);q=job['query'];key=(q['case_id'],q['query_index']);variant=job['configuration']['variant'];task=job['task']
        row={'task':task,'case_id':q['case_id'],'query_index':q['query_index'],'seed':q['seed'],'variant':variant,'status':'AUDIT_ERROR','completion_claim':False}
        try:
            require(key in inventory and q==inventory[key] and variant in VARIANTS and (key,variant) not in seen,'Frozen ablation query/variant identity differs');seen.add((key,variant))
            expected={'task':f"{q['case_id']}_q{q['query_index']:02d}_{variant}",'method':'zrhfd_ablation','setting':'no_volume','configuration':{**base_config,'variant':variant},'query':inventory[key],'implementation_exact_cut_backend':'prepared_region_workspace','result_path':RUN+'/raw/'+task+'.json.gz','source_sha256':manifest['source_sha256'],'protocol_sha256':manifest['protocol_sha256'],'measurement_role':'formal_cpu_serial'}
            require(job==expected and Path(name).stem==task,'Ablation source/config/job path differs')
            if last_graph!=q['graph_path']:graph=h.IndependentGraph(ev.read(q['graph_path'],q['graph_sha256']));last_graph=q['graph_path']
            row=worker(ev,h,job,name,graph);row['variant']=variant
            csvrow=csv_by_task[task]
            for field,value in {'method':'zrhfd_ablation','setting':'no_volume','variant':variant,'task':task,'case_id':q['case_id'],'query_index':q['query_index'],'seed':q['seed'],'status':row['status'],'completion_claim':row['completion_claim'],'protocol_sha256':manifest['protocol_sha256'],'implementation_exact_cut_backend':'prepared_region_workspace','raw_path':row['raw_path']}.items():compare(csvrow.get(field),value,'Ablation CSV identity '+field)
            # Quality in this independent view is always blank for noncompletion.
            # A partial worker's observed raw quality is not recomputed or used.
            if row['completion_claim']:
                for field,key2 in [('F1','F1'),('precision','precision'),('recall','recall'),('Z_out','Z'),('Z_out_exact','Z_exact'),('phi_out','phi'),('volume_out','volume'),('components','components'),('hull_best_F1','hull_F1'),('outer_wall_seconds','wrapper_seconds'),('touched_volume','touched_volume'),('touched_over_output_volume','touched_over_output')]:compare(csvrow.get(field),row[key2],'Independent ablation CSV '+field)
            else:
                compare(csvrow.get('outer_wall_seconds'),None,'Noncompletion outer timer');compare(csvrow.get('method_seconds'),None,'Noncompletion method timer')
            if row['raw_path']:raw_hashes[row['raw_path']]=ev.files[row['raw_path']]
            fail=ev.path(job['result_path']).with_suffix('.failure.json')
            if fail.exists():raw_hashes[str(fail.relative_to(ev.root))]=ev.files[str(fail.relative_to(ev.root))]
        except Exception:errors.append({'task':task,'traceback':traceback.format_exc()})
        ablations.append(row)
    if errors:
        failure=ValueError('Independent task checks failed; no paired inference is authorized')
        failure.task_errors=errors
        raise failure
    require(len(seen)==1008 and set(csv_by_task)=={r['task'] for r in ablations},'Full 18x56 task identity census did not close')
    require(summary['raw_sha256']==raw_hashes,'Ablation summary raw/failure hash map differs')
    require(summary['G_E2']['status']=='NOT RUN','Dev ablations cannot decide G-E2')
    for variant in VARIANTS:
        group=[r for r in ablations if r['variant']==variant];panel=summary['panels'][variant];done=[r for r in group if r['completion_claim']]
        require(len(group)==56 and panel['planned']==56 and panel['statuses']==dict(Counter(r['status'] for r in group)),'Variant full planned/failure denominator differs')
        for field,key in [('F1','F1'),('precision','precision'),('recall','recall'),('outer_wall_seconds','wrapper_seconds'),('touched_over_output_volume','touched_over_output')]:
            h.metric_check(panel['completed_only'].get(field),[{**r,field:r.get(key)} for r in done],field,variant+'.'+field)
        for row in group:
            base=base_rows[(row['case_id'],row['query_index'])];complete=base['completion_claim'] and row['completion_claim']
            pair={'variant':variant,'case_id':row['case_id'],'query_index':row['query_index'],'seed':row['seed'],'main_task':base['task'],'ablation_task':row['task'],'main_status':base['status'],'ablation_status':row['status'],'main_completion_claim':base['completion_claim'],'ablation_completion_claim':row['completion_claim'],'pair_completed':complete,'main_F1':base['F1'] if complete else None,'ablation_F1':row.get('F1') if complete else None,'main_Z':base['Z'] if complete else None,'ablation_Z':row.get('Z') if complete else None,'main_touched_over_output':base['touched_over_output'] if complete else None,'ablation_touched_over_output':row.get('touched_over_output') if complete else None,'main_wrapper_seconds':base['wrapper_seconds'] if complete else None,'ablation_wrapper_seconds':row.get('wrapper_seconds') if complete else None,'Z_difference_exact':None,**{metric:None for metric in METRICS}}
            if complete:
                pair['F1_difference']=row['F1']-base['F1']
                if row['Z_exact'] is not None and base['Z_exact'] is not None:
                    exact=Fraction(row['Z_exact'])-Fraction(base['Z_exact']);pair['Z_difference_exact']=str(exact);pair['Z_difference']=float(exact)
                if row['touched_over_output'] is not None and base['touched_over_output'] is not None:pair['touched_over_output_difference']=row['touched_over_output']-base['touched_over_output']
                pair['wrapper_seconds_difference']=row['wrapper_seconds']-base['wrapper_seconds']
                pair['wrapper_seconds_ratio']=row['wrapper_seconds']/base['wrapper_seconds'] if base['wrapper_seconds']>0 else None
            pairs.append(pair)
    paired={}
    for variant in VARIANTS:
        group=[r for r in pairs if r['variant']==variant]
        paired[variant]={'planned_pairs':56,'completed_pairs':sum(r['pair_completed'] for r in group),'status_pair_denominators':dict(Counter(r['main_status']+' / '+r['ablation_status'] for r in group)),'metrics':bootstrap_pairs(group)}
        print(json.dumps({'stage':'paired_bootstrap','variant':variant,'replicates':REPLICATES,'completed_pairs':paired[variant]['completed_pairs']}),flush=True)
    ev.recheck()
    return {'schema_version':1,'status':'PASS_INDEPENDENT_AUDIT','cohort_origin':'ORIGINAL_FROZEN_DEV_ABLATIONS','manifest_sha256':MANIFEST_SHA,'main_manifest_sha256':MAIN_SHA,'main_independent_audit_sha256':MAIN_AUDIT_SHA,'source_sha256':source_sha,'created_utc':datetime.now(timezone.utc).isoformat(),'analysis_wall_seconds':time.perf_counter()-started,'planned_ablation_jobs':1008,'planned_queries':56,'planned_graphs':28,'variants':list(VARIANTS),'completed_ablation_jobs':sum(r['completion_claim'] for r in ablations),'all_ablation_queries_completed':all(r['completion_claim'] for r in ablations),'statuses':dict(Counter(r['status'] for r in ablations)),'baseline_records':baselines,'ablation_records':ablations,'paired_records':pairs,'paired_statistics':paired,'validated_files':ev.files,'errors':errors,'paired_sampler':{'replicates':REPLICATES,'seed':SEED,'engine':'stdlib random.Random MT19937','same_draws_as_original_numpy_bootstrap':False,'confidence':.95,'unit':'graph_then_paired_queries','missing_policy':'Retain56 pairs per variant; infer only completed pairs, no zero or quality imputation'},'scope':{'test_read':False,'mechanism_diagnostics_generated':False,'Leiden_counterfactual_generated':False,'scientific_gate_decided':False,'registered_336_query_region_decision_replaced':False,'paired_costs':'descriptive only; variants and base measured in different serial phases, not an independent acceleration claim','touched':'degree-volume of declared touched vertices, not total implementation I/O'},'algorithms_executed':False,'measurement_raw_derived_production_files_modified':False,'bootstrap_is_new_independent_paired_analysis':True}


def write_csv(path,rows):
    keys=sorted({k for row in rows for k in row})
    with path.open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,help='New project-relative directory under reviews/m4_analysis')
    args=parser.parse_args();name=Path(args.output)
    if name.is_absolute() or '..' in name.parts or not (ROOT/name).resolve().is_relative_to(ROOT/'reviews/m4_analysis'):raise ValueError('Output must stay within reviews/m4_analysis')
    folder=ROOT/name
    if folder.exists():raise ValueError('Existing independent output is immutable; choose a new suffix')
    folder.mkdir(parents=True)
    source_start=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        result=analyze()
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=source_start:raise ValueError('Executed source changed during analysis')
        outputs={}
        for filename,key in [('baseline_query_results.csv','baseline_records'),('ablation_query_results.csv','ablation_records'),('paired_query_results.csv','paired_records')]:
            write_csv(folder/filename,result[key]);outputs[filename]=hashlib.sha256((folder/filename).read_bytes()).hexdigest()
        statistics_rows=[]
        for variant,panel in result['paired_statistics'].items():
            for metric,value in panel['metrics'].items():
                statistics_rows.append({'variant':variant,'metric':metric,'planned_pairs':panel['planned_pairs'],'completed_pairs':panel['completed_pairs'],'paired_metric_queries':value['paired_metric_queries'],'paired_metric_graphs':value['paired_metric_graphs'],'mean':value['mean'],'median':value['median'],'mean_95_CI_low':value['mean_percentile_95_CI'][0] if value['mean_percentile_95_CI'] else None,'mean_95_CI_high':value['mean_percentile_95_CI'][1] if value['mean_percentile_95_CI'] else None,'median_95_CI_low':value['median_percentile_95_CI'][0] if value['median_percentile_95_CI'] else None,'median_95_CI_high':value['median_percentile_95_CI'][1] if value['median_percentile_95_CI'] else None,'replicates':REPLICATES,'seed':SEED,'sampler':'MT19937_independent','cost_claim':'descriptive_across_serial_phases','status_pair_denominators':json.dumps(panel['status_pair_denominators'],sort_keys=True)})
        write_csv(folder/'paired_statistics.csv',statistics_rows);outputs['paired_statistics.csv']=hashlib.sha256((folder/'paired_statistics.csv').read_bytes()).hexdigest();result['output_csv_sha256']=outputs
    except Exception as exc:
        result={'schema_version':1,'status':'FAIL','source_sha256':source_start,'created_utc':datetime.now(timezone.utc).isoformat(),'errors':getattr(exc,'task_errors',[])+[{'traceback':traceback.format_exc()}],'actual_statistics_status':'NO_VALIDATED_PAIRED_RESULT_CLAIM','algorithms_executed':False,'production_files_modified':False}
    result['actual_command']=[sys.executable,*sys.argv]
    result['receipt_payload_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    with (folder/'receipt.json').open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'status':result['status'],'receipt':str(name/'receipt.json'),'source_sha256':source_start,'algorithms_executed':False}))
    return 0 if result['status']=='PASS_INDEPENDENT_AUDIT' else 1


if __name__=='__main__':
    raise SystemExit(main())
