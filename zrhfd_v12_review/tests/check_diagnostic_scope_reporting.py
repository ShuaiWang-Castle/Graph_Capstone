"""Artificial receipt/AST checks; no graph, solver, or research result reads."""
import ast,copy,hashlib,importlib.util,json,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def functions(path,names):
    tree=ast.parse(path.read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    context={};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),context);return context

def main():
    checks=[]
    summary=functions(ROOT/'experiments/diagnostics/summarize_m4.py',{'apply_scope'})
    join=functions(ROOT/'experiments/diagnostics/m4_completion_join.py',{'classify'})
    primary={'status':'COMPLETED','completion_claim':'True','j_act':'2','exact_recovery':'False','failure_class':'H1'}
    for label in ('H1','H2','RECOVERED'):
        if join['classify'](primary,{'diagnostic_scope_allowed':False,'failure_class':label})!='DIAGNOSTIC_SCOPE_NOT_AUTHORIZED':raise AssertionError('Test fallback was not blocked')
        checks.append('blocked_primary_fallback_'+label)
    row={'diagnostic_query_id':'test_q','task':'q','split':'test','case_id':'c','seed':1,'community_index':0,'attempt_count':0,
         'static_exact_available':False,'diagnostic_status':'NOT_RUN'}
    pooled={'dev':[],'test':[1]};issues=[]
    out=summary['apply_scope']([row],pooled,{'test_q':{'allowed':False,'reason':'G_E2_FAIL'}},issues)[0]
    assert out['diagnostic_status']=='NOT_RUN_G_E2_NOT_PASS' and not out['static_exact_available'] and pooled['test']==[] and not issues
    checks.append('blocked_row_retained_without_truth_or_margins')
    before=dict(row,attempt_count=1,static_exact_available=True,failure_class='H2',C_subset_R=True)
    out=summary['apply_scope']([before],{'dev':[],'test':[1]},{'test_q':{'allowed':False,'reason':'G_E2_FAIL'}},issues)[0]
    assert out['diagnostic_status']=='RETAINED_OUT_OF_SCOPE' and out['out_of_scope_retained_diagnostic_fields']['failure_class']=='H2' and issues
    checks.append('unauthorized_existing_evidence_preserved_not_aggregated')
    spec=importlib.util.spec_from_file_location('scope_contract',ROOT/'experiments/diagnostics/scope_contract.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='zrhfd_scope_') as location:
        base=Path(location).resolve();module.ROOT=base;folder=base/'results/diagnostics/toy';folder.mkdir(parents=True)
        queries=[dict(row,diagnostic_query_id='dev_q',split='dev'),row]
        names=['experiments/diagnostics/gated_m4.py','experiments/diagnostics/scope_contract.py','original.py']
        for name in names:
            file=base/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('artificial source\n')
        pins={name:digest(base/name) for name in names}
        manifest={'frozen':{'queries':queries,'source_sha256':{'original.py':pins['original.py']},'upstream_manifests':{'dev':'dev_hash','test':'test_hash'}},'frozen_sha256':'toy_frozen_hash'}
        (folder/'manifest.json').write_text(json.dumps(manifest))
        absent,admission,_=module.load_scope(folder,manifest)
        assert admission['dev_q']['allowed'] and not admission['test_q']['allowed']
        checks.append('missing_scope_denies_test_allows_dev_reporting')
        scope={'schema_version':1,'diagnostic_manifest_sha256':digest(folder/'manifest.json'),'frozen_sha256':manifest['frozen_sha256'],
               'upstream_manifests':manifest['frozen']['upstream_manifests'],'source_pin_validation':{'status':'PASS'},'source_sha256':pins,
               'test_diagnostics_allowed':False,'test_gate':{'status':'FAIL','evidence':{}},
               'query_admission':[dict(q,allowed=q['split']=='dev',reason='DEV_SCOPE' if q['split']=='dev' else 'G_E2_FAIL') for q in queries]}
        receipt=folder/'SCOPE_RECEIPT.json'
        def call(value):
            receipt.write_text(json.dumps(value));history=folder/'scope_history';history.mkdir(exist_ok=True)
            (history/(digest(receipt)+'.json')).write_bytes(receipt.read_bytes())
            return module.load_scope(folder,manifest)
        call(scope);checks.append('bound_false_gate_receipt_accepted')
        for label,mutate in (
          ('wrong_manifest',lambda x:x.update(diagnostic_manifest_sha256='bad')),
          ('wrong_upstream',lambda x:x.update(upstream_manifests={})),
          ('omitted_outer_source',lambda x:x['source_sha256'].pop(names[0])),
          ('wrong_source_hash',lambda x:x['source_sha256'].update({'original.py':'bad'})),
          ('duplicate_query',lambda x:x['query_admission'].append(x['query_admission'][0])),
          ('missing_query',lambda x:x['query_admission'].pop()),
          ('wrong_query_seed',lambda x:x['query_admission'][0].update(seed=99)),
          ('wrong_test_permission',lambda x:x['query_admission'][1].update(allowed=True)),
          ('nonboolean_permission',lambda x:x['query_admission'][0].update(allowed='True')),
          ('pass_without_evidence',lambda x:x.update(test_diagnostics_allowed=True,test_gate={'status':'PASS','evidence':{}}))):
            altered=copy.deepcopy(scope);mutate(altered)
            try:call(altered)
            except RuntimeError:checks.append(label+'_rejected')
            else:raise AssertionError(label+' was accepted')
    report={'status':'PASS','checks':checks,'check_count':len(checks),'scope':'artificial receipt and AST functions only; no scientific gate outcome',
            'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'experiments/diagnostics/scope_contract.py',ROOT/'experiments/diagnostics/summarize_m4.py',ROOT/'experiments/diagnostics/m4_completion_join.py']}}
    target=ROOT/'reviews/diagnostics_scope/reporting_fixture_results.json';target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise RuntimeError('Keep prior fixture receipt; choose a new version before rerunning')
    target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'PASS','checks':len(checks)}))

if __name__=='__main__':main()
