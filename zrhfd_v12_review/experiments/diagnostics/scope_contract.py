"""Verify the outer diagnostic scope receipt without importing any solver."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[2]

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):digest.update(block)
    return digest.hexdigest()

def file_in_project(name):
    path=(ROOT/name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(ROOT):
        raise RuntimeError('Scope evidence must use project-relative paths')
    return path

def load_scope(folder,manifest):
    """Missing authorization permits dev reporting and denies test diagnosis."""
    path=folder/'SCOPE_RECEIPT.json';queries=manifest['frozen']['queries']
    if not path.exists():
        admission={q['diagnostic_query_id']:{'allowed':q['split']=='dev',
                    'reason':'DEV_SCOPE' if q['split']=='dev' else 'SCOPE_RECEIPT_NOT_AVAILABLE'} for q in queries}
        return {'test_diagnostics_allowed':False,'test_gate':{'status':'NOT RUN','reason':'No bound scope authorization'},
                'scope_origin':'ABSENT_FAIL_CLOSED'},admission,{}
    scope=json.loads(path.read_text())
    history=folder/'scope_history'/(sha(path)+'.json')
    if not history.exists() or history.read_bytes()!=path.read_bytes():
        raise RuntimeError('Current scope bytes lack their immutable history copy')
    if scope.get('schema_version')!=1 or type(scope.get('test_diagnostics_allowed')) is not bool:
        raise RuntimeError('Invalid scope receipt schema')
    if scope.get('diagnostic_manifest_sha256')!=sha(folder/'manifest.json') or scope.get('frozen_sha256')!=manifest['frozen_sha256']:
        raise RuntimeError('Scope receipt is bound to another diagnostic plan')
    if scope.get('upstream_manifests')!=manifest['frozen']['upstream_manifests']:
        raise RuntimeError('Scope upstream cohort differs')
    if scope.get('source_pin_validation',{}).get('status')!='PASS':
        raise RuntimeError('Scope did not verify the diagnostic source pins')
    required_sources={'experiments/diagnostics/gated_m4.py','experiments/diagnostics/scope_contract.py'}
    if not required_sources.issubset(scope.get('source_sha256',{})):
        raise RuntimeError('Scope omitted its admission and validation source identities')
    hashes={str(path.relative_to(ROOT)):sha(path),str(history.relative_to(ROOT)):sha(history)}
    for name,expected in manifest['frozen']['source_sha256'].items():
        if sha(file_in_project(name))!=expected:raise RuntimeError('Frozen diagnostic source changed')
    for mapping in (scope.get('source_sha256',{}),scope.get('test_gate',{}).get('evidence',{}).get('file_sha256',{})):
        for name,expected in mapping.items():
            if sha(file_in_project(name))!=expected:raise RuntimeError('Scope evidence bytes changed: '+name)
            hashes[name]=expected
    allowed_test=scope['test_diagnostics_allowed']
    if allowed_test and (scope.get('test_gate',{}).get('status')!='PASS' or not scope.get('test_gate',{}).get('evidence',{}).get('file_sha256')):
        raise RuntimeError('Test diagnosis lacks a verified PASS gate')
    if allowed_test:
        test_queries=[q for q in queries if q['split']=='test']
        test_runs={q['upstream_run'] for q in test_queries}
        if len(test_queries)!=432 or len(test_runs)!=1:raise RuntimeError('Test authorization requires the complete fixed cohort')
        run=next(iter(test_runs));summary_path=file_in_project(run+'/summary.json');primary_path=file_in_project(run+'/manifest.json')
        evidence=scope['test_gate']['evidence'];files=evidence['file_sha256']
        if files.get(run+'/summary.json')!=sha(summary_path) or files.get(run+'/manifest.json')!=sha(primary_path):
            raise RuntimeError('Test authorization omitted its real summary/manifest binding')
        summary=json.loads(summary_path.read_text());primary=json.loads(primary_path.read_text());gate=summary.get('G_E2',{})
        if gate.get('status')!='PASS' or gate.get('required')!=432 or gate.get('complete_test_query_triples')!=432:
            raise RuntimeError('Underlying test summary does not report a complete PASS')
        if gate.get('Leiden_margin_condition') is not True or gate.get('HFD_gain_condition') is not True:
            raise RuntimeError('Underlying test summary has not passed both conditions')
        if summary.get('run_manifest_sha256')!=sha(primary_path) or manifest['frozen']['upstream_manifests'][run]!=sha(primary_path) or primary.get('phase')!='main':
            raise RuntimeError('Underlying test summary belongs to another plan')
        origin=summary.get('cohort_origin')
        if gate.get('cohort_origin')!=origin:raise RuntimeError('Test gate origin differs from its summary')
        if origin=='ORIGINAL_FROZEN_COHORT':
            if sha(primary_path)!='caaf1ed4f65d2d51b1269856d1f944a59941e401a00cf99757775736b515150f':
                raise RuntimeError('Test authorization is not the original frozen cohort')
        elif origin=='FRESH_REPRODUCTION':
            binding=summary.get('reference_binding') or {}
            if binding.get('status')!='PASS' or binding.get('stage')!='M4_TEST_MAIN' or binding.get('cohort_origin')!=origin:
                raise RuntimeError('Fresh test authorization lacks its test binding')
            if not evidence.get('reference_binding_sha256') or gate.get('reference_binding_sha256')!=evidence['reference_binding_sha256']:
                raise RuntimeError('Fresh test binding hash differs from the scope gate')
        else:raise RuntimeError('Unknown test cohort origin')
    entries=scope.get('query_admission',[])
    admission={entry['diagnostic_query_id']:entry for entry in entries}
    if len(entries)!=len(admission) or set(admission)!={q['diagnostic_query_id'] for q in queries}:
        raise RuntimeError('Missing or duplicate scope admission identity')
    for q in queries:
        item=admission[q['diagnostic_query_id']]
        if any(item.get(key)!=q[key] for key in ('task','split','case_id','seed')):
            raise RuntimeError('Scope query identity differs')
        expected=q['split']=='dev' or (q['split']=='test' and allowed_test)
        if type(item.get('allowed')) is not bool or item['allowed']!=expected or not isinstance(item.get('reason'),str) or not item['reason']:
            raise RuntimeError('Invalid query scope decision')
    return scope,admission,hashes
