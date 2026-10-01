"""Independent stdlib audit of the two frozen ordinary v12-002 main cohorts.

Offline only. This module never imports Graph/evaluate, a solver, NumPy, or
Matplotlib, and never repeats bootstrap or changes a measurement. Test audits
recompute primary quality and graph-only certificate consistency; they do not
create truth-region coverage/rho/H1/H2 or other gated mechanism diagnostics.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import statistics
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
SELF = 'reviews/m4_analysis/audit_actual_ordinary_v001.py'
SNAPSHOT = 'provenance/source_snapshots/formal_ordinary_v12_002'
SNAPSHOT_RECEIPT_SHA = '35aff994c5d7fc355e13194c7d5f9cb6ea9e1a7e281a76d33bb9144e648ec074'
REFERENCE = 'reviews/m4_analysis/PREPARED_COMMANDS_v001.json'
REFERENCE_SHA = 'a0e1885b6a194ea523f78b3c26432dd373edb6b72b1b97183d1eb3fb2707f10e'
COHORTS = {
    'results/m4/dev_main_v12_002': ('ae8e1b57d465673c1ac14112e3e9ec13a1ba2b5166b0872d82c7a5d28ae8df3e', 'dev', 4032, 336, 28, 'data/dev/catalog_v12.json'),
    'results/m4/test_main_v12_002': ('caaf1ed4f65d2d51b1269856d1f944a59941e401a00cf99757775736b515150f', 'test', 5184, 432, 36, 'data/test/calibrated_lfr/catalog.json'),
}
THREADS = {k: '1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS')}
THREADS['PYTHONHASHSEED'] = '0'
QUALITY_FIELDS = ('F1','precision','recall','Z_out','Z_out_exact','phi_out','volume_out','size_out','components','hull_best_F1')
METRICS = ('F1','precision','recall','outer_wall_seconds','touched_over_output_volume','gap','F1_difference_from_Leiden')
PHI_EDGES = (.05,.15,.25,.35,.45,.55,.65)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(data):
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: '+value)
    return json.loads(data, parse_constant=invalid)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False, allow_nan=False).encode()


def compare(actual, expected, label):
    if expected is None:
        require(actual in (None, ''), label+': expected blank/null')
    elif isinstance(expected, bool):
        require(actual == expected or actual in (str(expected), str(expected).lower()), label+': boolean differs')
    elif isinstance(expected, (int,float)) and not isinstance(expected, bool):
        require(actual not in (None, '') and not isinstance(actual,bool), label+': missing numeric value')
        number = float(actual)
        require(math.isfinite(number) and math.isclose(number,float(expected),rel_tol=2e-12,abs_tol=2e-12), label+': numeric value differs')
    else:
        require(actual == expected, label+': value differs')


class Evidence:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.files = {}
    def path(self, name):
        p = Path(name)
        require(not p.is_absolute() and '..' not in p.parts, 'Nonportable evidence path: '+str(name))
        full = self.root/p
        require(full.resolve().is_relative_to(self.root), 'Evidence escaped project: '+str(name))
        return full
    def bind(self, name, expected=None):
        p = self.path(name)
        require(p.is_file(), 'Missing evidence: '+str(name))
        value = sha(p)
        if expected is not None:
            require(value == expected, 'Evidence SHA differs: '+str(name))
        old = self.files.setdefault(str(name), value)
        require(old == value, 'Evidence changed during audit: '+str(name))
        return p
    def read(self, name, expected=None):
        return strict_json(self.bind(name,expected).read_text())
    def recheck(self):
        for name, expected in self.files.items():
            require(sha(self.path(name)) == expected, 'Evidence changed by audit end: '+name)


class IndependentGraph:
    """Undirected parallel-edge aggregation, degrees and cuts using integers."""
    def __init__(self, data):
        self.n = data['n']
        require(type(self.n) is int and self.n > 0, 'Invalid graph order')
        combined = defaultdict(Fraction)
        for edge in data['edges']:
            require(len(edge) in (2,3), 'Invalid edge arity')
            u,v = edge[:2]
            require(type(u) is int and type(v) is int and 0<=u<self.n and 0<=v<self.n and u!=v, 'Invalid endpoint/self-loop')
            weight = Fraction(str(edge[2])) if len(edge)==3 else Fraction(1)
            require(weight > 0, 'Nonpositive edge weight')
            combined[tuple(sorted((u,v)))] += weight
        require(all(w.denominator==1 for w in combined.values()), 'Fixed main cohort requires integer aggregated adjacency')
        self.edges = [(u,v,int(w)) for (u,v),w in sorted(combined.items())]
        self.adj = [dict() for _ in range(self.n)]
        self.degree = [0]*self.n
        for u,v,w in self.edges:
            self.adj[u][v]=w;self.adj[v][u]=w
            self.degree[u]+=w;self.degree[v]+=w
        self.total = sum(self.degree)
        require(self.total>0, 'Zero-volume graph')
        h=hashlib.sha256()
        for u,v,w in self.edges:
            h.update((str(u)+','+str(v)+'\n').encode())
        self.native_csv_sha = h.hexdigest()
    def vertices(self, values):
        require(isinstance(values,list) and all(type(v) is int and 0<=v<self.n for v in values), 'Invalid vertex list')
        require(len(values)==len(set(values)), 'Duplicate output/region/hull vertices')
        return set(values)
    def stats(self, selected):
        selected=set(selected)
        volume=sum(self.degree[v] for v in selected)
        cut=sum(w for u in selected for v,w in self.adj[u].items() if v not in selected)
        z=Fraction(cut*self.total+volume*volume,self.total*volume) if volume else None
        denom=min(volume,self.total-volume)
        return {'volume':volume,'cut':cut,'Z':float(z) if z is not None else None,'Z_exact':str(z) if z is not None else None,'phi':cut/denom if denom>0 else None,'phi_v':cut/volume if volume else None,'size':len(selected)}
    def components(self, selected):
        remaining=set(selected);count=0
        while remaining:
            count+=1;stack=[remaining.pop()]
            while stack:
                for v in self.adj[stack.pop()]:
                    if v in remaining:
                        remaining.remove(v);stack.append(v)
        return count


def quality(selected, truth):
    tp=len(selected & truth)
    return {'F1':float(Fraction(2*tp,len(selected)+len(truth))) if selected or truth else 0.,
            'precision':float(Fraction(tp,len(selected))) if selected else 0.,
            'recall':float(Fraction(tp,len(truth))) if truth else 0.}


def stats_match(actual, expected, label):
    require(isinstance(actual,dict), label+': missing stats dictionary')
    for key,value in expected.items():
        if key == 'Z_exact':
            require(actual.get(key)==value, label+': exact rational Z differs')
        elif key in ('volume','cut','size'):
            require(actual.get(key)==value, label+': integer '+key+' differs')
        else:
            compare(actual.get(key),value,label+'.'+key)


def certificate_check(graph, result, selected, seed):
    """Existing primary certificate arithmetic/feasible points only, no solver."""
    cert=result.get('certificate')
    if cert is None:
        return None
    region=graph.vertices(result['region_vertices'])
    require(seed in selected and seed in region, 'Seeded main output/region lost its seed')
    require(selected<=region, 'Returned output escaped its recorded region')
    compare(result['region_volume'],graph.stats(region)['volume'],'region_volume')
    points=[]
    for point in cert['hull_vertices']:
        vertices=graph.vertices(point['vertices'])
        require(seed in vertices and vertices<=region, 'Seeded certificate hull point is infeasible')
        stats=graph.stats(vertices)
        require(point['volume']==stats['volume'] and point['cut']==stats['cut'], 'Certificate hull point exact volume/cut differs')
        require(stats['Z_exact'] is not None, 'Zero-volume certificate point')
        points.append((Fraction(stats['Z_exact']), vertices))
    hull=graph.vertices(cert['hull_best']);best_stats=graph.stats(hull)
    require(hull<=region and any(hull==s for _,s in points), 'Hull best is not a recorded feasible hull point')
    require(Fraction(cert['hull_best_Z_exact'])==Fraction(best_stats['Z_exact']), 'Hull best exact objective differs')
    require(Fraction(best_stats['Z_exact'])==min(z for z,_ in points), 'Hull best is not the least recorded objective')
    # These are checks of existing primary values; no new test label diagnosis.
    compare(cert.get('gap'),graph.stats(selected)['Z']-cert['LB_R'],'certificate.gap')
    require(cert['LB_R']<=best_stats['Z']+2e-12, 'Recorded lower bound exceeds feasible hull objective')
    if 'LB_R_upper' in cert:
        require(cert['LB_R']<=cert['LB_R_upper'], 'Reversed certificate interval')
    return hull


def phi_bin(value):
    for index,(left,right) in enumerate(zip(PHI_EDGES,PHI_EDGES[1:])):
        if left<=value<right:
            return str((index+1)/10)
    return None


def metric_check(observed, rows, field, label):
    valid=[r for r in rows if r.get(field) is not None and math.isfinite(r[field])]
    if not valid:
        require(observed is None,label+': expected empty completed metric')
        return
    require(isinstance(observed,dict),label+': missing completed metric')
    compare(observed['queries'],len(valid),label+'.queries')
    compare(observed['graphs'],len({r['case_id'] for r in valid}),label+'.graphs')
    compare(observed['mean'],statistics.fmean(r[field] for r in valid),label+'.mean')
    compare(observed['median'],statistics.median(r[field] for r in valid),label+'.median')
    require(observed['replicates']==10000 and observed['seed']==20261005,label+': bootstrap specification differs')
    for key in ('mean_percentile_95_CI','median_percentile_95_CI'):
        interval=observed[key]
        require(len(interval)==2 and all(math.isfinite(v) for v in interval) and interval[0]<=interval[1],label+': malformed existing CI')


def native_evidence(ev, artifact, graph, acquisition, completed):
    if not artifact:
        return
    folder=ev.path(artifact)
    if not folder.exists():
        return
    for path in sorted(folder.glob('native_*/execution.json')):
        name=str(path.relative_to(ev.root));record=ev.read(name)
        require(record['driver_sha256']==ev.files['zrhfd/baselines/native_driver.jl'],'Native driver identity differs')
        require(record['input_edge_csv_sha256']==graph.native_csv_sha,'Native conversion input hash differs')
        source=record['sources']
        matching=[r for r in acquisition['repositories'].values() if r['url']==source['repository'] and r['commit']==source['commit']]
        require(len(matching)==1,'Native author commit identity differs')
        for file,digest in source['files'].items():
            require(matching[0]['tracked_worktree_file_sha256'][file]==digest,'Author file receipt differs')
            ev.bind(matching[0]['path']+'/'+file,digest)
        require(record['environment_overrides'].get('JULIA_NUM_THREADS')=='1' and record['environment_overrides'].get('OPENBLAS_NUM_THREADS')=='1','Native thread policy differs')
        for kind in ('stdout','stderr'):
            p=ev.bind(record[kind+'_path'])
            if kind+'_sha256' in record:
                require(sha(p)==record[kind+'_sha256'],'Native '+kind+' hash differs')
        if completed:
            require(record['status']=='COMPLETED' and record['returncode']==0,'Completed worker has unfinished native execution')


def csv_projection(job, record, failure, graph, truth_stats, status, completed, independently):
    q=job['query'];a=record.get('result') or {};evaluation=record.get('evaluation') or {};stats=record.get('output_stats') or a.get('stats') or {}
    cert=a.get('certificate') or {};meta=a.get('metadata') or {};workspace=a.get('exact_cut_workspace',[])
    row={'task':job['task'],'case_id':q['case_id'],'query_index':q['query_index'],'n':graph.n,'seed':q['seed'],'method':job['method'],'setting':job['setting'],
         'variant':'main' if job['method']=='zrhfd' else None,'status':status,'completion_claim':completed,
         'Z_truth':truth_stats['Z'],'truth_phi':truth_stats['phi'],'truth_volume':truth_stats['volume'],
         'outer_wall_seconds':record.get('outer_wall_seconds') if completed else None,
         'observed_not_completion_seconds':failure.get('wall_seconds_observed_not_completion',record.get('outer_wall_seconds')),
         'input_load_seconds':record.get('input_load_seconds'),'method_seconds':a.get('runtime_seconds') if completed else None,
         'observed_method_seconds_not_completion':a.get('runtime_seconds'),'native_kernel_seconds':meta.get('kernel_seconds_total'),
         'peak_rss_bytes':record.get('peak_rss_bytes_sampled_process_and_children',failure.get('peak_rss_bytes')),
         'touched_volume':record.get('touched_volume',a.get('touched_volume')),
         'touched_definition':meta.get('touched_definition','diffusion support union region' if job['method']=='zrhfd' else None),
         'j_act':a.get('j_act'),'j_star':a.get('j_star'),'m_act':a.get('m_act'),'region_volume':a.get('region_volume'),
         'LB_R':cert.get('LB_R'),'gap':cert.get('gap'),'certificate_status':cert.get('certificate_status',cert.get('status')),
         'gap_bound':cert.get('gap_bound_telemetry',cert.get('gap_bound')),'gap_bound_exact':cert.get('gap_bound_exact'),
         'diffusion_seconds':sum(t.get('runtime_seconds',0) for t in a.get('diffusion_trace',[])),
         'mm_seconds':sum(t.get('telemetry',{}).get('runtime_seconds',0) for t in a.get('mm_trace',[])),
         'certificate_cut_execution_and_validation_seconds':sum(t.get('telemetry',{}).get('runtime_seconds',0) for t in cert.get('oracle_trace',[])),
         'implementation_exact_cut_backend':job['implementation_exact_cut_backend'],'mass_count':len(a.get('mass_sequence',meta.get('mass_grid',[]))),
         'mm_steps':len(a.get('mm_trace',[])),'raw_path':None,'error_path':None,'protocol_sha256':job['protocol_sha256']}
    for field,source in [('exact_cut_workspace_preparation_seconds','preparation_seconds'),('exact_cut_capacity_assembly_seconds','assembly_seconds'),('exact_cut_native_subprocess_seconds','native_subprocess_seconds'),('exact_cut_return_validation_seconds','objective_validation_seconds'),('exact_cut_calls','calls')]:
        row[field]=sum(w[source] for w in workspace)
    # Existing primary telemetry is mapped, not freshly label-diagnosed.
    for key in ('truth_covered','failure_class','rho_hat','outside_volume_ratio','symmetric_difference','exact_recovery'):
        row[key]=evaluation.get(key)
    row.update({field:None for field in QUALITY_FIELDS})
    if completed:
        row.update(independently)
    row['touched_over_output_volume']=row['touched_volume']/row['volume_out'] if row['touched_volume'] is not None and row['volume_out'] else None
    return row


def audit(root, run_name):
    started=time.perf_counter();ev=Evidence(root);rows=[];quality_checks=[];errors=[];status_counts=Counter()
    require(run_name in COHORTS,'Only the two original frozen v12-002 main cohorts are accepted')
    expected_sha,split,planned,queries_expected,cases_expected,catalog_path=COHORTS[run_name]
    require(Path(__file__).resolve()==ev.path(SELF).resolve(),'Auditor is not the requested project source')
    audit_source_sha=sha(ev.bind(SELF))
    try:
        manifest=ev.read(run_name+'/manifest.json',expected_sha)
        snapshot=ev.read(SNAPSHOT+'/receipt.json',SNAPSHOT_RECEIPT_SHA)
        reference=ev.read(REFERENCE,REFERENCE_SHA)
        require(manifest['phase']=='main' and manifest['source_sha256']==snapshot['source_sha256'] and len(manifest['source_sha256'])==27,'Frozen 27-source scope differs')
        require(manifest['runtime_sha256']==snapshot['runtime_sha256'],'Frozen runtime scope differs')
        require(manifest['implementation']['version']=='formal-ordinary-v12-002' and manifest['implementation']['exact_cut_backend']=='prepared_region_workspace','Wrong implementation cohort')
        require(len(manifest['jobs'])==planned and len(set(manifest['jobs']))==planned,'Frozen job census differs')
        require(manifest['resources']['memory_limit_bytes']==12000000000 and manifest['resources']['local_method_query_seconds']==600,'Frozen resources differ')
        for name,digest in manifest['source_sha256'].items():
            ev.bind(name,digest);ev.bind(SNAPSHOT+'/'+name,digest)
        for name,digest in manifest['runtime_sha256'].items():
            ev.bind(name,digest);ev.bind(SNAPSHOT+'/'+name,digest)
        ev.bind('provenance/dependency_versions.txt',manifest['dependency_versions_sha256'])
        ev.bind(SNAPSHOT+'/provenance/dependency_versions.txt',manifest['dependency_versions_sha256'])
        dependency_versions={}
        for line in ev.path('provenance/dependency_versions.txt').read_text().splitlines():
            if not line or line.startswith('#'):continue
            require('==' in line,'Nonexact dependency specification')
            package,expected=line.split('==',1);actual=importlib.metadata.version(package)
            require(actual==expected,'Installed dependency version differs: '+package)
            dependency_versions[package]=actual
        acquisition=ev.read('provenance/baselines/acquisition.json')
        catalog=ev.read(catalog_path,manifest['catalog_sha256'])
        cases={c['case_id']:c for c in catalog['cases']}
        require(len(cases)==cases_expected,'Catalog graph census differs')
        template={t['summary_panel']:t for t in reference['first_query_templates'] if t['split']==split}
        require(len(template)==12,'Reference configuration templates differ')
        inventory={};case_graph={}
        for case in cases.values():
            for pathkey,hashkey in (('graph_path','graph_sha256'),('truth_path','truth_sha256'),('queries_path','queries_sha256')):
                ev.bind(case[pathkey],case[hashkey])
            truth=ev.read(case['truth_path'])['communities'];query_list=ev.read(case['queries_path'])['queries']
            require(len(query_list)==case['query_count'],'Case query count differs')
            for qi,q in enumerate(query_list):
                inventory[(case['case_id'],qi)]={**case,'query_index':qi,'seed':q['seed'],'community_index':q['community_index'],'truth_vertices':truth[q['community_index']],'communities':truth}
        require(len(inventory)==queries_expected,'Frozen query census differs')
        summary=ev.read(run_name+'/summary.json');csv_path=ev.bind(run_name+'/query_results.csv');table_path=ev.bind(run_name+'/quality_cost_summary.csv')
        require(summary['run_manifest_sha256']==expected_sha and summary['cohort_origin']=='ORIGINAL_FROZEN_COHORT','Derived summary cohort differs')
        require(summary['derived_view_sha256']['query_results.csv']==sha(csv_path) and summary['derived_view_sha256']['quality_cost_summary.csv']==sha(table_path),'Derived CSV hash differs')
        with csv_path.open(newline='') as stream:csv_rows=list(csv.DictReader(stream))
        require(len(csv_rows)==planned and len({r['task'] for r in csv_rows})==planned,'CSV census differs')
        csv_by_task={r['task']:r for r in csv_rows};seen=set();raw_hashes={};last_graph_path=None;graph=None
        for job_name in manifest['jobs']:
            task=Path(job_name).stem;status='UNKNOWN';completed=False;row={'task':task,'status':status,'completion_claim':False,**{key:None for key in QUALITY_FIELDS}}
            try:
                job=ev.read(job_name);q=job['query'];key=(q['case_id'],q['query_index']);panel=job['method']+'_'+job['setting']
                require(panel in template and key in inventory and q==inventory[key],'Job query/method does not match fixed inventory')
                require((key,panel) not in seen,'Duplicate query/method setting');seen.add((key,panel))
                cfg=dict(template[panel]['configuration'])
                if 'artifact_directory' in cfg:cfg['artifact_directory']=run_name+'/artifacts/'+task
                expected_job={'task':task,'method':template[panel]['method'],'setting':template[panel]['setting'],'configuration':cfg,'query':inventory[key],'implementation_exact_cut_backend':'prepared_region_workspace','result_path':run_name+'/raw/'+task+'.json.gz','source_sha256':manifest['source_sha256'],'protocol_sha256':manifest['protocol_sha256'],'measurement_role':'formal_cpu_serial'}
                require(job==expected_job,'Job configuration/source/request differs from fixed template')
                if last_graph_path!=q['graph_path']:
                    graph=IndependentGraph(ev.read(q['graph_path'],q['graph_sha256']));last_graph_path=q['graph_path']
                truth=graph.vertices(q['truth_vertices']);truth_stats=graph.stats(truth)
                dest=ev.path(job['result_path']);failure_path=dest.with_suffix('.failure.json');checkpoint=ev.path(job['result_path']+'.checkpoint.json')
                raw={};control={};raw_name=job['result_path'];failure_name=str(failure_path.relative_to(ev.root))
                if dest.exists():
                    ev.bind(raw_name)
                    with gzip.open(dest,'rt') as stream:raw=strict_json(stream.read())
                    raw_hashes[raw_name]=ev.files[raw_name]
                if failure_path.exists():
                    control=ev.read(failure_name);raw_hashes[failure_name]=ev.files[failure_name]
                status=control.get('status',raw.get('status','NOT_RUN'))
                completed=status=='COMPLETED' and raw.get('completion_claim') is True
                if checkpoint.exists():
                    cp=ev.read(str(checkpoint.relative_to(ev.root)))
                    require(cp['task']==task and cp['source_sha256']==manifest['source_sha256'] and cp['partial_not_convergence'] is True,'Checkpoint identity differs')
                log_prefix=run_name+'/logs/'+task;started_name=log_prefix+'.started.json'
                if raw or control or ev.path(started_name).exists():
                    request=ev.read(started_name)
                    require(request['task']==task and request['status']=='STARTED' and request['job_sha256']==ev.files[job_name],'Started/request job binding differs')
                    expected_command=[str(ev.root/'.venv/bin/python'),'experiments/worker.py','--job',job_name]
                    require(request['actual_argv']==expected_command and request['cwd']==str(ev.root) and request['thread_environment']==THREADS,'Started command/runtime thread identity differs')
                    ev.bind(log_prefix+'.stdout.log');ev.bind(log_prefix+'.stderr.log')
                if control:
                    require(control['task']==task and control['job']==job_name and control['completion_claim'] is False,'Failure terminal identity differs')
                    require(control['command']==expected_command and control['partial_result_present']==bool(raw),'Failure command/result presence differs')
                    require(control['stdout_path']==log_prefix+'.stdout.log' and control['stderr_path']==log_prefix+'.stderr.log','Failure log identity differs')
                if raw:
                    for field,value in {'task':task,'method':job['method'],'setting':job['setting'],'seed':q['seed'],'configuration':cfg,'protocol_sha256':manifest['protocol_sha256'],'source_sha256':manifest['source_sha256'],'implementation_exact_cut_backend':'prepared_region_workspace','measurement_role':'formal_cpu_serial','command':['.venv/bin/python','experiments/worker.py','--job',job_name],'input':{k:v for k,v in q.items() if k not in ('truth_vertices','communities')}}.items():
                        require(raw.get(field)==value,'Worker raw identity/config differs: '+field)
                    require(raw['truth_in_method_path']==(job['setting']=='oracle'),'Oracle/no-volume input disclosure differs')
                    compare(raw.get('oracle_volume'),truth_stats['volume'] if job['setting']=='oracle' else None,'oracle_volume')
                independent={};hull=None
                if completed:
                    require(raw.get('result') is not None,'Completed raw lacks actual cover')
                    a=raw['result'];selected=graph.vertices(a['vertices']);stats=graph.stats(selected);primary=quality(selected,truth)
                    for field,value in primary.items():compare(raw['evaluation'][field],value,'raw.evaluation.'+field)
                    stats_match(raw['output_stats'],stats,'raw.output_stats');stats_match(raw['evaluation']['truth_stats'],truth_stats,'raw.truth_stats')
                    if 'stats' in a:stats_match(a['stats'],stats,'raw.result.stats')
                    components=graph.components(selected);require(raw['components']==components,'Raw component count differs')
                    require(raw['output_contains_seed']==(q['seed'] in selected),'Raw seed membership differs')
                    hull=certificate_check(graph,a,selected,q['seed'])
                    hull_f1=None
                    if hull is not None:
                        hull_primary=quality(hull,truth);hull_f1=hull_primary['F1']
                        for field,value in hull_primary.items():compare(raw['hull_best_evaluation'][field],value,'raw.hull_best.'+field)
                    touched=a.get('touched_vertices')
                    if isinstance(touched,list):compare(raw['touched_volume'],sum(graph.degree[v] for v in graph.vertices(touched)),'raw.touched_volume')
                    independent={**primary,'Z_out':stats['Z'],'Z_out_exact':stats['Z_exact'],'phi_out':stats['phi'],'volume_out':stats['volume'],'size_out':stats['size'],'components':components,'hull_best_F1':hull_f1}
                    quality_checks.append({'task':task,'F1':primary['F1'],'precision':primary['precision'],'recall':primary['recall'],'stats':stats,'components':components,'hull_best_F1':hull_f1})
                native_evidence(ev,cfg.get('artifact_directory'),graph,acquisition,completed)
                row=csv_projection(job,raw,control,graph,truth_stats,status,completed,independent)
                row['raw_path']=raw_name if raw else None;row['error_path']=failure_name if control else None
                csv_row=csv_by_task[task]
                for field,value in row.items():compare(csv_row.get(field),value,'CSV.'+task+'.'+field)
                rows.append(row);status_counts[status]+=1
            except Exception:
                row.update(status=status,completion_claim=completed)
                rows.append(row);status_counts[status]+=1
                errors.append({'task':task,'status':status,'traceback':traceback.format_exc()})
        require(len(seen)==planned and len(csv_by_task)==planned,'Complete query/method identity census did not close')
        groups=defaultdict(list)
        lookup={(r.get('case_id'),r.get('query_index'),r.get('method'),r.get('setting')):r for r in rows}
        for row in rows:
            if 'method' not in row:continue
            leiden=lookup.get((row['case_id'],row['query_index'],'leiden','global'))
            difference=row['F1']-leiden['F1'] if row['completion_claim'] and leiden and leiden['completion_claim'] else None
            row['F1_difference_from_Leiden']=difference
            compare(csv_by_task[row['task']].get('F1_difference_from_Leiden'),difference,'CSV matched-Leiden difference')
            groups[row['method']+'_'+row['setting']].append(row)
        require(set(groups)==set(template)==set(summary['panels']),'Twelve summary method panels differ')
        with table_path.open(newline='') as stream:table=list(csv.DictReader(stream))
        require(len(table)==12 and len({r['method_setting'] for r in table})==12,'Quality-cost table setting census differs')
        table_by_panel={r['method_setting']:r for r in table}
        for panel,group in groups.items():
            require(len(group)==queries_expected,'Panel planned denominator differs')
            done=[r for r in group if r['completion_claim']];observed=summary['panels'][panel]
            require(observed['planned']==len(group) and observed['statuses']==dict(Counter(r['status'] for r in group)),'Summary full denominator/status differs')
            for field in METRICS:metric_check(observed['completed_only'].get(field),done,field,panel+'.'+field)
            for center in ('0.1','0.2','0.3','0.4','0.5','0.6'):
                chosen=[r for r in group if phi_bin(r['truth_phi'])==center];stratum=observed['by_measured_truth_phi'][center]
                require(stratum['planned']==len(chosen) and stratum['statuses']==dict(Counter(r['status'] for r in chosen)),'Summary truth-phi planned denominator differs')
                metric_check(stratum['completed_F1'],[r for r in chosen if r['completion_claim']],'F1',panel+'.phi'+center)
            require(observed['truth_phi_outside_displayed_bins_queries']==sum(phi_bin(r['truth_phi']) is None for r in group),'Outside truth-phi denominator differs')
            tr=table_by_panel[panel]
            compare(tr['planned'],len(group),'quality-cost planned');compare(tr['completed'],len(done),'quality-cost completed')
            require(strict_json(tr['status_counts'])==dict(Counter(r['status'] for r in group)),'Quality-cost status denominator differs')
            for field,prefix in (('F1','F1'),('outer_wall_seconds','wall')):
                values=[r[field] for r in done if r.get(field) is not None]
                suffix='_completed_only' if field=='outer_wall_seconds' else ''
                compare(tr[prefix+'_mean'+suffix],statistics.fmean(values) if values else None,'quality-cost '+field+' mean')
                compare(tr[prefix+'_median'+suffix],statistics.median(values) if values else None,'quality-cost '+field+' median')
        require(summary['raw_sha256']==raw_hashes,'Summary complete raw/failure hash mapping differs')
        if split=='dev':require(summary['G_E2']['status']=='NOT RUN','Dev cannot evaluate G-E2')
        # Test gate identity/status is preserved; this audit does not perform gate
        # decisions or unlock mechanism diagnostics.
        ev.recheck()
    except Exception:
        errors.append({'task':None,'traceback':traceback.format_exc()})
    return {'schema_version':1,'status':'PASS' if not errors else 'FAIL','cohort_origin':'ORIGINAL_FROZEN_COHORT','run':run_name,'split':split,'manifest_sha256':expected_sha,'auditor_source_sha256':audit_source_sha,'auditor_source_path':SELF,'created_utc':utc(),'audit_wall_seconds':time.perf_counter()-started,'planned':planned,'query_count':queries_expected,'case_count':cases_expected,'completed':sum(r.get('completion_claim') is True for r in rows),'statuses':dict(status_counts),'query_records':rows,'completed_quality_checks':quality_checks,'errors':errors,'validated_files':ev.files,'installed_dependency_versions':locals().get('dependency_versions',{}),'bootstrap_recomputed':False,'algorithms_executed':False,'measurement_or_raw_modified':False,'test_mechanism_diagnostics_generated':False,'quality_scope':'completed requested budgets only; no convergence claim','certificate_scope':'recorded feasible hull points/exact graph arithmetic and existing primary gap only; no new cuts or optimality proof','ci_scope':'existing CI schema/specification checked; CI endpoints not independently resampled'}


def verify_audit_receipt(receipt_path, root=ROOT, run_name=None, verify_files=True):
    receipt=strict_json(Path(receipt_path).read_text());seal=receipt.pop('receipt_payload_sha256')
    require(hashlib.sha256(canonical(receipt)).hexdigest()==seal,'Audit receipt payload seal differs')
    require(receipt['status']=='PASS' and not receipt['errors'],'Independent audit did not pass')
    name=receipt['run'];require(name in COHORTS and (run_name is None or run_name==name),'Audit run identity differs')
    expected,split,planned,queries,cases,_=COHORTS[name]
    require(receipt['manifest_sha256']==expected and receipt['planned']==planned and receipt['split']==split,'Audit fixed cohort identity differs')
    records=receipt['query_records'];require(len(records)==planned and len({r['task'] for r in records})==planned,'Audit record census differs')
    done={r['task']:r for r in records if r['completion_claim']};checks=receipt['completed_quality_checks']
    require(receipt['completed']==len(done) and len(checks)==len(done) and {r['task'] for r in checks}==set(done),'Audit completed quality identity set differs')
    for row in records:
        if not row['completion_claim']:
            require(all(row.get(k) is None for k in QUALITY_FIELDS) and row.get('outer_wall_seconds') is None and row.get('method_seconds') is None,'Noncompleted audit row contains completion quality/time')
    for quality_record in checks:
        row=done[quality_record['task']]
        for key in ('F1','precision','recall','components','hull_best_F1'):compare(quality_record[key],row[key],'Audit independent quality binding')
    require(receipt['auditor_source_path']==SELF and receipt['validated_files'].get(SELF)==receipt['auditor_source_sha256'],'Audit executed source binding differs')
    if verify_files:
        ev=Evidence(root)
        for path,digest in receipt['validated_files'].items():ev.bind(path,digest)
    return {'status':'PASS','cohort_origin':'ORIGINAL_FROZEN_COHORT','run':name,'planned':planned,'completed':len(done),'receipt_sha256':sha(receipt_path),'auditor_source_sha256':receipt['auditor_source_sha256']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',required=True,choices=tuple(COHORTS))
    ap.add_argument('--output',required=True,help='New project-relative receipt path within reviews/m4_analysis')
    args=ap.parse_args();output=Path(args.output)
    require(not output.is_absolute() and '..' not in output.parts,'Expected portable audit output path')
    target=ROOT/output
    require(target.resolve().is_relative_to(ROOT/'reviews/m4_analysis'),'Audit writes restricted to reviews/m4_analysis')
    require(not target.exists(),'Existing audit receipt is immutable; use a new output path')
    receipt=audit(ROOT,args.run)
    receipt['actual_command']=[sys.executable,*sys.argv]
    receipt['receipt_payload_sha256']=hashlib.sha256(canonical(receipt)).hexdigest()
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'status':receipt['status'],'planned':receipt['planned'],'completed':receipt['completed'],'errors':len(receipt['errors']),'receipt':args.output,'receipt_sha256':sha(target),'audit_wall_seconds':receipt['audit_wall_seconds']}))
    return 0 if receipt['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
