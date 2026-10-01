"""Outer admission control for unchanged M4 offline diagnostic workers.

Frozen §5 permits test diagnostics only after G-E2 passes.  This helper keeps
the original 768-query manifest and nine worker pins.  It never loads topology
or truth: a PASS is independently checked against existing evaluation records.
Default invocation records the gate/admission decision without running workers.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import fcntl
import gzip
import hashlib
import importlib
import json
import math
import os
import signal
import statistics
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_TEST_SHA = 'caaf1ed4f65d2d51b1269856d1f944a59941e401a00cf99757775736b515150f'
PARENT_SOURCES = (
    'experiments/diagnostics/graph_query.py', 'experiments/diagnostics/m4_query.py',
    'experiments/diagnostics/m4_worker.py', 'experiments/diagnostics/run_m4.py',
    'experiments/diagnostics/storage.py', 'zrhfd/__init__.py', 'zrhfd/graph.py',
    'zrhfd/diffusion.py', 'provenance/dependency_versions.txt')
METHODS = {('zrhfd', 'no_volume'), ('hfd', 'no_volume'), ('leiden', 'global')}
ROLE = 'Offline diagnostic admission only; no algorithm, parameter, or quality selection change'


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def portable(root, name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts: raise ValueError('Nonportable project path')
    resolved = (root/path).resolve()
    if not resolved.is_relative_to(root.resolve()): raise ValueError('Path escapes workspace')
    return resolved


def stamp():
    return datetime.now(timezone.utc).isoformat()


def publish(path, data):
    """Atomic immutable publication; retain a failed partial write."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data: raise RuntimeError('Immutable artifact differs: '+str(path))
        return
    temp = path.parent/('.'+path.name+'.partial-'+str(uuid.uuid4()))
    with temp.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.link(temp, path); temp.unlink()


def validate_descriptor(q,job,primary,actual_sha):
    if q['job_sha256']!=actual_sha:raise ValueError('Descriptor job SHA differs')
    if job['task']!=q['task'] or job['method']!='zrhfd' or job['setting']!='no_volume':
        raise ValueError('Descriptor is not this no-volume main task')
    if job['configuration'].get('variant','main')!='main' or job['result_path']!=q['raw_path']:
        raise ValueError('Descriptor main variant/raw differs')
    if job['source_sha256']!=primary['source_sha256'] or job['protocol_sha256']!=primary['protocol_sha256'] or q['primary_protocol_sha256']!=job['protocol_sha256']:
        raise ValueError('Descriptor source/protocol differs')
    for key in ('split','case_id','seed','community_index','graph_path','graph_sha256','truth_path','truth_sha256'):
        if q[key]!=job['query'][key]:raise ValueError('Descriptor/job query identity differs: '+key)


def validate_plan(manifest, root, verified_files=None):
    frozen = manifest['frozen']
    semantic = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if manifest['frozen_sha256'] != semantic: raise ValueError('Diagnostic frozen payload SHA differs')
    queries = frozen['queries']
    if len(queries) != 768 or Counter(q['split'] for q in queries) != {'dev': 336, 'test': 432}:
        raise ValueError('Requires all 768 planned main identities (336 dev, 432 test)')
    if len({q['diagnostic_query_id'] for q in queries}) != 768:
        raise ValueError('Duplicate diagnostic query identity')
    if len({(q['upstream_run'], q['task']) for q in queries}) != 768:
        raise ValueError('Duplicate upstream query identity')
    if set(frozen['source_sha256']) != set(PARENT_SOURCES): raise ValueError('Parent nine-source set differs')
    for name, expected in frozen['source_sha256'].items():
        if digest(portable(root, name)) != expected: raise ValueError('Parent source SHA differs: '+name)
    if set(frozen['upstream_manifests']) != {q['upstream_run'] for q in queries}:
        raise ValueError('Upstream manifest set differs')
    upstream={}
    verified={} if verified_files is None else verified_files
    for name,expected in frozen['source_sha256'].items():verified[name]=expected
    for run, expected in frozen['upstream_manifests'].items():
        name=run+'/manifest.json'
        if digest(portable(root, name)) != expected:
            raise ValueError('Upstream manifest SHA differs: '+run)
        verified[name]=expected;primary=read(portable(root,name));upstream[run]=primary
        splits={q['split'] for q in queries if q['upstream_run']==run}
        if len(splits)!=1 or primary.get('phase')!='main':raise ValueError('Mixed or non-main upstream split')
        split=next(iter(splits));required=4032 if split=='dev' else 5184
        if len(primary['jobs'])!=required or len(set(primary['jobs']))!=required:raise ValueError('Incomplete upstream main task plan')
        if len(primary.get('source_sha256',{}))!=27:raise ValueError('Upstream source count differs')
        for source,sha in primary['source_sha256'].items():
            if digest(portable(root,source))!=sha:raise ValueError('Upstream source SHA differs: '+source)
            verified[source]=sha
    for q in queries:
        primary=upstream[q['upstream_run']]
        if q['job_path'] not in primary['jobs']:raise ValueError('Diagnostic job is outside its bound upstream plan')
        path=portable(root,q['job_path']);actual=digest(path)
        validate_descriptor(q,read(path),primary,actual);verified[q['job_path']]=actual
    test_runs = {q['upstream_run'] for q in queries if q['split'] == 'test'}
    if len(test_runs) != 1: raise ValueError('Requires one bound test upstream')
    return next(iter(test_runs))


def number(value, label):
    if isinstance(value, bool): raise ValueError('Boolean numeric '+label)
    try: value = float(value)
    except (TypeError, ValueError): raise ValueError('Missing/invalid numeric '+label)
    if not math.isfinite(value) or not 0 <= value <= 1: raise ValueError('Out-of-range '+label)
    return value


def verify_triples(queries, manifest, summary, rows, load_job, load_raw, sha_file, exists):
    """Pure-object checker, also used by injected artificial fixtures.

    load_raw returns already-recorded evaluation JSON, not a new truth evaluation.
    Neither this checker nor its production loaders read Graph/truth vertices.
    """
    gate = summary['G_E2']
    if gate.get('status') != 'PASS': raise ValueError('Gate is not strictly PASS')
    if gate.get('required') != 432 or gate.get('complete_test_query_triples') != 432:
        raise ValueError('PASS lacks a full 432-triple declaration')
    if gate.get('Leiden_margin_condition') is not True or gate.get('HFD_gain_condition') is not True:
        raise ValueError('PASS conditions are not strict booleans')
    tasks = manifest['jobs']; jobs = {}; participants = {}
    if len(tasks) != 5184 or len(set(tasks)) != 5184: raise ValueError('Test main plan must retain all 5184 tasks')
    for path in tasks:
        job = load_job(path)
        if job['task'] in jobs: raise ValueError('Duplicate planned task')
        if Path(path).stem != job['task']: raise ValueError('Job path/task differs')
        if job['query']['split'] != 'test': raise ValueError('Non-test job in test plan')
        if job['source_sha256'] != manifest['source_sha256'] or job['protocol_sha256'] != manifest['protocol_sha256']:
            raise ValueError('Job frozen source/protocol differs from primary manifest')
        jobs[job['task']] = (path, job)
        if (job['method'], job['setting']) in METHODS:
            if job['method'] == 'zrhfd' and job['configuration'].get('variant', 'main') != 'main':
                continue
            q = job['query']; key = (q['case_id'], int(q['query_index']))
            group = participants.setdefault(key, {})
            method = (job['method'], job['setting'])
            if method in group: raise ValueError('Duplicate method in query triple')
            group[method] = job['task']
    table = {row['task']: row for row in rows}
    if len(table) != len(rows) or set(table) != set(jobs): raise ValueError('CSV task set differs from full plan')
    if len(participants) != 432 or any(set(g) != METHODS for g in participants.values()):
        raise ValueError('Not exactly 432 unique three-method queries')
    planned_main = {q['task']: q for q in queries if q['split'] == 'test'}
    main_tasks = {group[('zrhfd', 'no_volume')] for group in participants.values()}
    if set(planned_main) != main_tasks: raise ValueError('PASS uses another main diagnostic cohort')
    evidence_jobs = {}; evidence_raw = {}; triples = []
    for key, group in sorted(participants.items()):
        seeds = set(); values = {}
        for method, task in group.items():
            path, job = jobs[task]; row = table[task]; q = job['query']
            seeds.add(int(q['seed']))
            if (row.get('method'), row.get('setting')) != method or row.get('case_id') != q['case_id']:
                raise ValueError('CSV method/case identity differs')
            if int(row['seed']) != q['seed'] or int(row['query_index']) != q['query_index']:
                raise ValueError('CSV seed/query identity differs')
            if row.get('protocol_sha256') != job['protocol_sha256']:
                raise ValueError('CSV protocol identity differs')
            if method[0] == 'zrhfd' and row.get('variant') != 'main': raise ValueError('Not main variant')
            if row.get('status') != 'COMPLETED' or row.get('completion_claim') != 'True':
                raise ValueError('Incomplete participating query')
            f1 = number(row.get('F1'), 'F1'); phi = number(row.get('truth_phi'), 'truth_phi')
            raw_path = job['result_path']
            if row.get('raw_path') != raw_path or row.get('error_path') not in ('', None):
                raise ValueError('CSV raw/error binding differs')
            if exists(str(Path(raw_path).with_suffix('.failure.json'))): raise ValueError('Participating outer failure exists')
            raw_sha = sha_file(raw_path)
            if summary.get('raw_sha256', {}).get(raw_path) != raw_sha: raise ValueError('Participating raw SHA differs')
            raw = load_raw(raw_path)
            if raw.get('status') != 'COMPLETED' or raw.get('completion_claim') is not True or not isinstance(raw.get('result'), dict):
                raise ValueError('Raw is not a completed method result')
            if any(raw.get(k) != job[k] for k in ('task', 'method', 'setting')) or raw.get('seed') != q['seed']:
                raise ValueError('Raw query identity differs')
            if raw.get('truth_in_method_path') is not False or raw.get('oracle_volume') is not None:
                raise ValueError('Participating method is not non-oracle')
            if raw.get('source_sha256') != job['source_sha256'] or raw.get('protocol_sha256') != job['protocol_sha256']:
                raise ValueError('Raw source/protocol binding differs')
            if raw.get('configuration') != job['configuration']: raise ValueError('Raw configuration differs')
            for field in ('graph_path', 'graph_sha256', 'truth_path', 'truth_sha256', 'queries_path', 'queries_sha256', 'community_index'):
                if raw.get('input', {}).get(field) != q[field]: raise ValueError('Raw input metadata differs: '+field)
            ev = raw.get('evaluation', {})
            if number(ev.get('F1'), 'raw F1') != f1 or number(ev.get('truth_stats', {}).get('phi'), 'raw truth_phi') != phi:
                raise ValueError('CSV quality differs from bound existing raw evaluation')
            if sha_file(raw_path) != raw_sha: raise ValueError('Raw changed while decoded evaluation was checked')
            if method[0] == 'zrhfd':
                d = planned_main[task]
                if any(d.get(k) != q[k] for k in ('case_id', 'seed', 'community_index', 'graph_path', 'graph_sha256', 'truth_path', 'truth_sha256')):
                    raise ValueError('Diagnostic main identity differs')
                if d['job_path'] != path or d['raw_path'] != raw_path or d['job_sha256'] != sha_file(path) or d['primary_protocol_sha256'] != job['protocol_sha256']:
                    raise ValueError('Diagnostic job/raw/protocol binding differs')
            values[method] = (f1, phi); evidence_jobs[path] = sha_file(path); evidence_raw[raw_path] = raw_sha
        if len(seeds) != 1 or len({v[1] for v in values.values()}) != 1:
            raise ValueError('Triple seed or truth_phi differs')
        triples.append({'case_id': key[0], 'query_index': key[1], 'seed': next(iter(seeds)),
                        'tasks': {a+'_'+b: t for (a,b),t in group.items()},
                        'truth_phi': values[('zrhfd','no_volume')][1],
                        'main_F1': values[('zrhfd','no_volume')][0], 'hfd_F1': values[('hfd','no_volume')][0],
                        'leiden_F1': values[('leiden','global')][0]})
    low = [t for t in triples if t['truth_phi'] <= .5]
    high = [t for t in low if t['truth_phi'] >= .4]
    if not low or not high: raise ValueError('Empty gate stratum')
    med = lambda data, key: statistics.median(t[key] for t in data)
    computed = {'complete_test_query_triples': 432, 'required': 432,
                'truth_phi_le_point5_queries': len(low), 'truth_phi_point4_to_point5_queries': len(high),
                'main_median_low': med(low, 'main_F1'), 'leiden_median_low': med(low, 'leiden_F1'),
                'main_median_high': med(high, 'main_F1'), 'hfd_no_volume_median_high': med(high, 'hfd_F1')}
    first = computed['main_median_low'] >= computed['leiden_median_low']-.03
    second = computed['main_median_high'] >= computed['hfd_no_volume_median_high']+.10
    if not first or not second: raise ValueError('Claimed PASS fails independently recomputed median condition')
    for key, value in computed.items():
        if gate.get(key) != value: raise ValueError('Claimed gate value differs: '+key)
    return {'recomputed_gate': dict(computed, Leiden_margin_condition=first, HFD_gain_condition=second),
            'paired_query_identities': triples, 'participating_job_sha256': evidence_jobs,
            'participating_raw_sha256': evidence_raw,
            'quality_source': 'Existing offline raw evaluation only; no graph/truth reload or method solve'}


def evaluate_gate(root, manifest, test_run, reference_binding=None, binding_verifier=None):
    """All uncertainty fails closed; a blocked gate does not read test CSV/raw."""
    evidence = {'file_sha256':{}}; summary_path = portable(root, test_run)/'summary.json'
    try:
        summary = read(summary_path); evidence['summary_sha256'] = digest(summary_path)
        evidence['file_sha256'][str(summary_path.relative_to(root))] = evidence['summary_sha256']
        status = summary.get('G_E2', {}).get('status', 'MISSING')
        if status != 'PASS':
            return {'status': status, 'reason': 'G_E2 is not strictly PASS; frozen §5 limits diagnostics to dev', 'evidence': evidence}, False
        directory = portable(root, test_run); primary_path = directory/'manifest.json'; primary = read(primary_path)
        primary_sha = digest(primary_path); evidence['manifest_sha256'] = primary_sha
        evidence['file_sha256'][str(primary_path.relative_to(root))] = primary_sha
        if summary.get('run_manifest_sha256') != primary_sha or manifest['frozen']['upstream_manifests'].get(test_run) != primary_sha:
            raise ValueError('PASS summary is not bound to this test manifest')
        if primary.get('phase') != 'main': raise ValueError('Not a main test phase')
        if len(primary.get('source_sha256',{})) != 27: raise ValueError('Primary frozen source count is not 27')
        for name, expected in primary['source_sha256'].items():
            if digest(portable(root,name)) != expected: raise ValueError('Primary frozen source SHA differs: '+name)
            evidence['file_sha256'][name] = expected
        for name,expected in primary.get('runtime_sha256',{}).items():
            if digest(portable(root,name)) != expected: raise ValueError('Primary runtime SHA differs')
            evidence['file_sha256'][name] = expected
        for name,key in [('experiments/protocol_v12.yaml','protocol_sha256'),('provenance/dependency_versions.txt','dependency_versions_sha256')]:
            if digest(portable(root,name)) != primary[key]: raise ValueError('Primary protocol/dependency SHA differs')
            evidence['file_sha256'][name] = primary[key]
        if reference_binding is None:
            if primary_sha != ORIGINAL_TEST_SHA: raise ValueError('Not the original frozen test manifest')
            origin = 'ORIGINAL_FROZEN_COHORT'
        else:
            if binding_verifier is None:
                sys.path.insert(0, str(root))
                binding_verifier = importlib.import_module('experiments.reproduction.cohort_binding').verify_m4_reference_binding
            binding_path = portable(root, reference_binding)
            binding = binding_verifier(binding_path, run_path=directory, verify_files=True)
            if binding.get('status') != 'PASS' or binding.get('cohort_origin') != 'FRESH_REPRODUCTION' or binding.get('stage') != 'M4_TEST_MAIN' or binding.get('files_reverified_now') is not True:
                raise ValueError('Fresh full-file test binding did not pass')
            binding_sha = digest(binding_path)
            if summary.get('G_E2', {}).get('reference_binding_sha256') != binding_sha:
                raise ValueError('Summary fresh binding SHA differs')
            if summary.get('reference_binding') != binding: raise ValueError('Summary fresh binding differs')
            evidence['reference_binding_sha256'] = binding_sha; origin = 'FRESH_REPRODUCTION'
            evidence['file_sha256'][reference_binding] = binding_sha
            verifier_name = 'experiments/reproduction/cohort_binding.py'
            evidence['file_sha256'][verifier_name] = digest(portable(root,verifier_name))
        if summary.get('cohort_origin') != origin or summary['G_E2'].get('cohort_origin') != origin:
            raise ValueError('Gate origin differs')
        csv_path = directory/'query_results.csv'; csv_sha = digest(csv_path)
        if summary.get('derived_view_sha256', {}).get('query_results.csv') != csv_sha:
            raise ValueError('PASS query CSV SHA differs')
        evidence['query_csv_sha256'] = csv_sha
        evidence['file_sha256'][str(csv_path.relative_to(root))] = csv_sha
        with csv_path.open(newline='') as stream: rows = list(csv.DictReader(stream))
        def load_raw(name):
            with gzip.open(portable(root, name), 'rt') as stream: return json.load(stream)
        evidence.update(verify_triples(manifest['frozen']['queries'], primary, summary, rows,
                       lambda n: read(portable(root,n)), load_raw,
                       lambda n: digest(portable(root,n)), lambda n: portable(root,n).exists()))
        evidence['file_sha256'].update(evidence['participating_job_sha256'])
        evidence['file_sha256'].update(evidence['participating_raw_sha256'])
        for name, expected in evidence['file_sha256'].items():
            if digest(portable(root,name)) != expected: raise ValueError('Gate inputs changed during verification')
        return {'status':'PASS', 'reason':'Full bound test cohort and both median conditions independently verified', 'evidence':evidence}, True
    except Exception as error:
        return {'status':'BLOCKED_UNVERIFIED', 'reason':type(error).__name__+': '+str(error), 'evidence':evidence}, False


def make_scope(root, folder, manifest, gate, allowed, command, initial_source_sha256=None):
    source = dict(manifest['frozen']['source_sha256'])
    source['experiments/diagnostics/gated_m4.py'] = digest(root/'experiments/diagnostics/gated_m4.py')
    source['experiments/diagnostics/scope_contract.py'] = digest(root/'experiments/diagnostics/scope_contract.py')
    if initial_source_sha256 is not None and any(source.get(name)!=expected for name,expected in initial_source_sha256.items()):
        raise RuntimeError('Outer helper changed during gate verification; preserve evidence and rerun under one source')
    rows = []
    for q in manifest['frozen']['queries']:
        admit = q['split']=='dev' or allowed
        rows.append({k:q[k] for k in ('diagnostic_query_id','task','split','upstream_run','case_id','seed')} |
                    {'allowed':admit,'reason':'DEV_ALLOWED' if q['split']=='dev' else ('G_E2_PASS' if allowed else 'NOT_RUN_G_E2_NOT_PASS')})
    return {'schema_version':1, 'test_diagnostics_allowed':bool(allowed), 'test_gate':gate,
            'diagnostic_manifest_sha256':digest(folder/'manifest.json'), 'frozen_sha256':manifest['frozen_sha256'],
            'source_sha256':source, 'source_pin_validation':{'status':'PASS','parent_source_count':9},
            'upstream_manifests':manifest['frozen']['upstream_manifests'], 'actual_command':command,
            'generated_utc':stamp(), 'scope_role':ROLE, 'query_admission':rows,
            'planned_queries':768, 'allowed_queries':336+432*bool(allowed),
            'completion_claim':False, 'algorithm_parameters_modified':False,
            'protocol_correction':'Enforce frozen §5 before any new test truth diagnostics; preserve original manifest/raw',
            'preparation_is_not_scientific_acceptance':True}


def save_scope(folder, scope):
    path = folder/'SCOPE_RECEIPT.json'; history = folder/'scope_history'
    if path.exists():
        old = path.read_bytes(); publish(history/(hashlib.sha256(old).hexdigest()+'.json'), old)
    data = canonical(scope); sha = hashlib.sha256(data).hexdigest()
    publish(history/(sha+'.json'), data)
    temporary = folder/('.SCOPE_RECEIPT.json.partial-'+str(uuid.uuid4()))
    with temporary.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
    return sha


def verify_sources(root, scope):
    for name, expected in scope['source_sha256'].items():
        if digest(portable(root,name)) != expected: raise RuntimeError('Source changed: '+name)


def run_selected(root, folder, manifest, scope, scope_sha, runner, limit=None, retry=False):
    """Reuse unchanged inventory/attempt recovery/watchdog, after split admission."""
    selected = [q for q in manifest['frozen']['queries'] if q['split']=='dev' or scope['test_diagnostics_allowed']]
    rows = runner.inventory(selected); attempted = 0
    for row in rows:
        if row['inventory_status'] != 'ELIGIBLE_COMPLETED_MAIN': continue
        verify_sources(root,scope)
        if digest(folder/'SCOPE_RECEIPT.json') != scope_sha: raise RuntimeError('Scope decision changed during execution')
        if row['split']=='test':
            inputs=scope['test_gate']['evidence']['file_sha256']
            test_run=row['upstream_run']
            for name in (test_run+'/manifest.json',test_run+'/summary.json',test_run+'/query_results.csv'):
                if digest(portable(root,name))!=inputs[name]:raise RuntimeError('Bound PASS view changed before test worker admission')
        query_folder = folder/'queries'/row['diagnostic_query_id']; attempts = sorted(query_folder.glob('attempt_*'))
        for attempt in attempts:
            if not (attempt/'receipt.json').exists(): runner.recover_abandoned(attempt,row['diagnostic_query_id'])
        finished = [read(p/'receipt.json') for p in attempts]
        if finished and (finished[-1]['status']=='COMPLETED' or finished[-1]['status'] not in ['ABANDONED_PREVIOUS_DIAGNOSTIC','INTERRUPTED'] and not retry): continue
        if limit is not None and attempted >= limit: break
        attempt = query_folder/f'attempt_{len(attempts):03d}'
        authorization = {'schema_version':1,'scope_receipt_sha256':scope_sha,
                         'scope_history_path':str((folder/'scope_history'/(scope_sha+'.json')).relative_to(root)),
                         'diagnostic_query_id':row['diagnostic_query_id'],'split':row['split'],
                         'attempt_path':str(attempt.relative_to(root)), 'source_raw_sha256':row['raw_sha256'],
                         'source_sha256':scope['source_sha256'],'admitted_before_worker_start':True}
        auth_path = folder/'scope_authorizations'/row['diagnostic_query_id']/(attempt.name+'.json')
        publish(auth_path,canonical(authorization))
        receipt = runner.execute_one(attempt,row,manifest,folder); attempted += 1
        publish(auth_path.with_suffix('.outcome.json'),canonical({'scope_receipt_sha256':scope_sha,
                'attempt_path':authorization['attempt_path'],'terminal_receipt_sha256':digest(attempt/'receipt.json'),
                'status':receipt['status'],'new_diagnostic_completion_claim':receipt['status']=='COMPLETED'}))
    return {'attempted_queries':attempted,'admitted_planned_queries':len(selected),'test_diagnostics_allowed':scope['test_diagnostics_allowed']}


@contextmanager
def serial_lease(folder, psutil_module=None):
    """Own controller lease plus compatibility with the unchanged runner lock."""
    if psutil_module is None: psutil_module = importlib.import_module('psutil')
    lease = folder/'gated_serial.lock'; compatible = folder/'serial.lock'
    with lease.open('a+') as stream:
        try: fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another gated diagnostic controller holds this workspace')
        if compatible.exists():
            old = compatible.read_bytes(); pid = int(old)
            if pid <= 0 or psutil_module.pid_exists(pid): raise RuntimeError('Diagnostic controller lock is live or invalid')
            if compatible.read_bytes() != old: raise RuntimeError('Diagnostic lock changed')
            compatible.unlink()
        fd = os.open(compatible,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            os.write(fd,str(os.getpid()).encode()); os.fsync(fd)
            controller = {'pid':os.getpid(),'create_time':psutil_module.Process(os.getpid()).create_time(),
                          'cwd':str(ROOT),'actual_command':[sys.executable,*sys.argv]}
            publish(folder/'scope_controllers'/(str(controller['pid'])+'_'+str(controller['create_time'])+'.json'),canonical(controller))
            yield
        finally:
            os.close(fd)
            if compatible.exists() and compatible.read_text()==str(os.getpid()): compatible.unlink()
            fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',default='results/diagnostics/m4_main_v12_001')
    parser.add_argument('--reference-binding'); parser.add_argument('--execute',action='store_true')
    parser.add_argument('--limit',type=int); parser.add_argument('--retry-incomplete',action='store_true')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0: parser.error('Negative limit')
    if Path(__file__).resolve()!=ROOT/'experiments/diagnostics/gated_m4.py':raise RuntimeError('Noncanonical gate helper path')
    initial_sources={name:digest(ROOT/name) for name in ('experiments/diagnostics/gated_m4.py','experiments/diagnostics/scope_contract.py')}
    folder = portable(ROOT,args.run)
    if not folder.is_relative_to(ROOT/'results/diagnostics'): parser.error('Run outside diagnostic scope')
    manifest = read(folder/'manifest.json'); plan_files={};test_run = validate_plan(manifest,ROOT,plan_files)
    with serial_lease(folder):
        gate,allowed = evaluate_gate(ROOT,manifest,test_run,args.reference_binding)
        gate['evidence']['file_sha256'].update(plan_files)
        scope = make_scope(ROOT,folder,manifest,gate,allowed,[sys.executable,*sys.argv],initial_sources)
        scope['existing_test_attempts_retained']=[str(p.relative_to(ROOT)) for q in manifest['frozen']['queries'] if q['split']=='test'
                                                for p in sorted((folder/'queries'/q['diagnostic_query_id']).glob('attempt_*'))]
        scope_sha = save_scope(folder,scope)
        print(json.dumps({'test_gate':gate['status'],'test_diagnostics_allowed':allowed,'scope_receipt_sha256':scope_sha,'planned_queries':768,'allowed_queries':scope['allowed_queries'],'execute':args.execute}),flush=True)
        if not args.execute: return
        sys.path.insert(0,str(ROOT)); runner = importlib.import_module('experiments.diagnostics.run_m4')
        if runner.sources() != manifest['frozen']['source_sha256']: raise RuntimeError('Parent runner source set changed')
        def interrupt(signum,frame): raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,interrupt)
        outcome = run_selected(ROOT,folder,manifest,scope,scope_sha,runner,args.limit,args.retry_incomplete)
        verify_sources(ROOT,scope)
        publish(folder/'scope_executions'/(scope_sha+'.json'),canonical(outcome|{'scope_receipt_sha256':scope_sha,'finished_utc':stamp()}))
        print(json.dumps(outcome),flush=True)


if __name__=='__main__': main()
