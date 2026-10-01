"""Artificial object/temporary-file tests only; never use actual M4 raw/data."""
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gated_test_module',ROOT/'experiments/diagnostics/gated_m4.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


def fixture():
    jobs={};raw={};rows=[];queries=[];hashes={}
    sources={f'tiny/source{i}.py':str(i) for i in range(27)}
    for i in range(432):
        case='case'+str(i//12);query=i%12;seed=i
        for label in range(12):
            method,setting=[('zrhfd','no_volume'),('hfd','no_volume'),('leiden','global')][label] if label<3 else ('dummy'+str(label),'no_volume')
            task=f'{case}_q{query:02d}_label{label}';path='tiny/jobs/'+task+'.json';rp='tiny/raw/'+task+'.json.gz'
            q={'split':'test','case_id':case,'query_index':query,'seed':seed,'community_index':0,
               'graph_path':'tiny/graph','graph_sha256':'g','truth_path':'tiny/truth','truth_sha256':'t',
               'queries_path':'tiny/queries','queries_sha256':'q'}
            job={'task':task,'method':method,'setting':setting,'query':q,'configuration':{},'result_path':rp,'protocol_sha256':'p','source_sha256':sources}
            jobs[path]=job;hashes[path]='job'+task;hashes[rp]='raw'+task
            row={'task':task,'case_id':case,'query_index':str(query),'seed':str(seed),'method':method,'setting':setting,
                 'protocol_sha256':'p','variant':'main' if label==0 else '', 'status':'COMPLETED','completion_claim':'True',
                 'F1':str([.8,.65,.82][label]) if label<3 else '.1','truth_phi':'.45','raw_path':rp,'error_path':''}
            rows.append(row)
            if label<3:
                raw[rp]={'task':task,'method':method,'setting':setting,'seed':seed,'status':'COMPLETED','completion_claim':True,
                         'result':{},'configuration':{},'source_sha256':sources,'protocol_sha256':'p','truth_in_method_path':False,
                         'oracle_volume':None,'input':{k:q[k] for k in ('graph_path','graph_sha256','truth_path','truth_sha256','queries_path','queries_sha256','community_index')},
                         'evaluation':{'F1':[.8,.65,.82][label],'truth_stats':{'phi':.45}}}
            if label==0:
                queries.append({'diagnostic_query_id':'test__'+task,'task':task,'split':'test','upstream_run':'tiny/test',
                                'case_id':case,'seed':seed,'community_index':0,'graph_path':'tiny/graph','graph_sha256':'g',
                                'truth_path':'tiny/truth','truth_sha256':'t','job_path':path,'job_sha256':hashes[path],
                                'raw_path':rp,'primary_protocol_sha256':'p'})
    summary={'G_E2':{'status':'PASS','required':432,'complete_test_query_triples':432,'Leiden_margin_condition':True,
                     'HFD_gain_condition':True,'truth_phi_le_point5_queries':432,'truth_phi_point4_to_point5_queries':432,
                     'main_median_low':.8,'leiden_median_low':.82,'main_median_high':.8,'hfd_no_volume_median_high':.65},
             'raw_sha256':{n:h for n,h in hashes.items() if n in raw}}
    manifest={'jobs':list(jobs),'source_sha256':sources,'protocol_sha256':'p'}
    return queries,manifest,summary,rows,jobs,raw,hashes


def verify(f):
    q,m,s,r,j,a,h=f
    return gate.verify_triples(q,m,s,r,j.__getitem__,a.__getitem__,h.__getitem__,lambda p:False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='reviews/diagnostics_scope/tiny_v001.json');args=parser.parse_args()
    start=time.perf_counter();checks=[];violations=[]
    def expect(name,fn,accepted):
        try:fn();actual=True;error=None
        except Exception as e:actual=False;error=repr(e)
        checks.append({'name':name,'expected_accepted':accepted,'accepted':actual,'error':error})
        if actual!=accepted:violations.append(name)
    base=fixture();expect('full432_artificial_control',lambda:verify(base),True)
    def mutation(name,apply):
        f=copy.deepcopy(base);apply(f);expect(name,lambda:verify(f),False)
    mutation('incomplete432',lambda f:f[2]['G_E2'].update(complete_test_query_triples=431))
    mutation('condition_not_bool',lambda f:f[2]['G_E2'].update(HFD_gain_condition=1))
    mutation('CSV_F1_disagrees_raw',lambda f:f[3][0].update(F1='.7'))
    mutation('raw_not_completed',lambda f:f[5][f[3][0]['raw_path']].update(status='TIMEOUT'))
    mutation('raw_completion_not_bool',lambda f:f[5][f[3][0]['raw_path']].update(completion_claim=1))
    mutation('raw_wrong_task',lambda f:f[5][f[3][0]['raw_path']].update(task='another'))
    mutation('raw_SHA_changed',lambda f:f[6].update({f[3][0]['raw_path']:'changed'}))
    mutation('source_job_vs_manifest',lambda f:f[4][f[1]['jobs'][0]].update(source_sha256={'other':'sha'}))
    mutation('CSV_incomplete',lambda f:f[3][0].update(status='TIMEOUT',completion_claim='False'))
    mutation('CSV_nan',lambda f:f[3][0].update(F1='NaN'))
    mutation('CSV_phi_out_of_range',lambda f:f[3][0].update(truth_phi='1.1'))
    mutation('CSV_wrong_seed',lambda f:f[3][1].update(seed='-1'))
    mutation('duplicate_CSV_task',lambda f:f[3].append(copy.deepcopy(f[3][0])))
    mutation('foreign_diagnostic_main',lambda f:f[0][0].update(task='wrong'))
    mutation('summary_median_drift',lambda f:f[2]['G_E2'].update(main_median_high=.9))
    mutation('raw_truth_phi_drift',lambda f:f[5][f[3][0]['raw_path']]['evaluation']['truth_stats'].update(phi=.4))
    mutation('oracle_contamination',lambda f:f[5][f[3][0]['raw_path']].update(truth_in_method_path=True))
    def tamper(f):
        for row in f[3]:
            if row['method']=='zrhfd':row['F1']='.1';f[5][row['raw_path']]['evaluation']['F1']=.1
    mutation('CSV_and_raw_updated_but_median_FAIL',tamper)
    # A non-PASS summary returns before any CSV, raw, job, graph or truth loader.
    for status in ['FAIL','NOT RUN','MISSING','pass']:
        def blocked(status=status):
            with patch.object(gate,'read',return_value={'G_E2':{'status':status}}),patch.object(gate,'digest',return_value='sha'):
                result,allowed=gate.evaluate_gate(Path('/tiny'),{},'test')
                assert not allowed and result['status']==status
        expect('blocked_summary_'+status,blocked,True)
    def missing():
        with patch.object(gate,'read',side_effect=FileNotFoundError('tiny')),patch.object(gate,'digest',side_effect=AssertionError('should not hash')):
            result,allowed=gate.evaluate_gate(Path('/tiny'),{},'test');assert not allowed and result['status']=='BLOCKED_UNVERIFIED'
    expect('missing_summary_fails_closed',missing,True)
    def wrong_summary():
        objects=[{'G_E2':{'status':'PASS'},'run_manifest_sha256':'dev'}, {'phase':'main'}]
        with patch.object(gate,'read',side_effect=objects),patch.object(gate,'digest',return_value='test'):
            result,allowed=gate.evaluate_gate(Path('/tiny'),{'frozen':{'upstream_manifests':{'test':'test'}}},'test')
            assert not allowed and 'not bound' in result['reason']
    expect('dev_wrong_summary_not_admitted',wrong_summary,True)
    # Nine-source checks use fake hash lookups and full synthetic plan identity.
    def source_check(bad=False):
        queries=[];jobs={};primary={}
        sources={f'sources/f{i}':'pin' for i in range(27)}
        for i in range(768):
            split='dev' if i<336 else 'test';path=split+f'/jobs/t{i}.json'
            q={'diagnostic_query_id':f'q{i}','task':f't{i}','split':split,'upstream_run':split,
               'case_id':str(i),'seed':i,'community_index':0,'job_path':path,'job_sha256':'pin',
               'raw_path':split+f'/raw/t{i}.json.gz','primary_protocol_sha256':'pin',
               'graph_path':'graph','graph_sha256':'pin','truth_path':'truth','truth_sha256':'pin'}
            queries.append(q);jobs[path]={'task':q['task'],'method':'zrhfd','setting':'no_volume','configuration':{},
                                        'result_path':q['raw_path'],'protocol_sha256':'pin','source_sha256':sources,'query':q}
        for split,count in [('dev',4032),('test',5184)]:
            paths=[q['job_path'] for q in queries if q['split']==split]
            primary[split]={'phase':'main','jobs':paths+[split+f'/jobs/unused{i}.json' for i in range(count-len(paths))],
                            'source_sha256':sources,'protocol_sha256':'pin'}
        frozen={'queries':queries,'source_sha256':{name:'pin' for name in gate.PARENT_SOURCES},'upstream_manifests':{'dev':'pin','test':'pin'}}
        m={'frozen':frozen,'frozen_sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        def load(p):
            name=str(p.relative_to('/tiny'))
            return primary[name.split('/')[0]] if name.endswith('/manifest.json') else jobs[name]
        with patch.object(gate,'read',side_effect=load),patch.object(gate,'digest',side_effect=lambda p:'wrong' if bad and str(p).endswith('graph_query.py') else 'pin'):
            assert gate.validate_plan(m,Path('/tiny'))=='test'
    expect('nine_source_control',source_check,True);expect('nine_source_mismatch',lambda:source_check(True),False)
    def spoof_dev():
        q,m,s,r,j,a,h=base;descriptor=copy.deepcopy(q[0]);descriptor['split']='dev'
        job=j[descriptor['job_path']]
        gate.validate_descriptor(descriptor,job,m,h[descriptor['job_path']])
    expect('test_descriptor_spoofed_as_dev',spoof_dev,False)
    def outer_changed():
        with patch.object(gate,'digest',return_value='new'):
            gate.make_scope(Path('/tiny'),Path('/tiny/run'),{'frozen':{'source_sha256':{}}},{},False,[],
                            {'experiments/diagnostics/gated_m4.py':'executed_old'})
    expect('outer_source_changed_during_gate',outer_changed,False)
    # Temporary tiny workspace tests real immutable publication and injected runner.
    with tempfile.TemporaryDirectory(prefix='zrhfd_scope_fixture_') as temporary:
        root=Path(temporary);folder=root/'results/diagnostics/tiny';folder.mkdir(parents=True)
        source=root/'experiments/diagnostics/gated_m4.py';source.parent.mkdir(parents=True);source.write_text('tiny source')
        scope={'source_sha256':{'experiments/diagnostics/gated_m4.py':gate.digest(source)},'test_diagnostics_allowed':False,
               'test_gate':{'status':'FAIL'},'query_admission':[]}
        sha=gate.save_scope(folder,scope);old=sha
        scope2=copy.deepcopy(scope);scope2['test_gate']['status']='NOT RUN';sha2=gate.save_scope(folder,scope2)
        expect('scope_history_retains_prior_decision',lambda:(_ for _ in ()).throw(AssertionError()) if not (folder/'scope_history'/(old+'.json')).exists() or old==sha2 else None,True)
        called=[];inventory_seen=[]
        def inventory(q):
            inventory_seen.extend(q)
            return [dict(row,inventory_status='ELIGIBLE_COMPLETED_MAIN',raw_sha256='tiny') for row in q]
        def execute(directory,row,manifest,run):
            called.append(row['split']);directory.mkdir(parents=True);gate.publish(directory/'receipt.json',gate.canonical({'status':'COMPLETED'}));return {'status':'COMPLETED'}
        runner=SimpleNamespace(inventory=inventory,execute_one=execute,recover_abandoned=lambda *a:None)
        planned=[{'diagnostic_query_id':'dev1','task':'d','split':'dev'},{'diagnostic_query_id':'test1','task':'t','split':'test'}]
        result=gate.run_selected(root,folder,{'frozen':{'queries':planned}},scope2,sha2,runner)
        expect('blocked_test_never_inventory_or_execute',lambda:None if called==['dev'] and [q['split'] for q in inventory_seen]==['dev'] and result['admitted_planned_queries']==1 else (_ for _ in ()).throw(AssertionError()),True)
        # Real flock acquired twice on tiny fixture; no process observer is used.
        ps=SimpleNamespace(pid_exists=lambda p:False,Process=lambda p:SimpleNamespace(create_time=lambda:1.0))
        def lease_collision():
            with gate.serial_lease(folder,ps):
                try:
                    with gate.serial_lease(folder,ps):pass
                except RuntimeError:return
                raise AssertionError('Second controller accepted')
        expect('workspace_lease_collision',lease_collision,True)
    tree=ast.parse((ROOT/'experiments/diagnostics/gated_m4.py').read_text())
    banned=[]
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or '']
            banned.extend(n for n in names if n.startswith(('numpy','scipy','zrhfd','experiments.diagnostics.run_m4')))
    expect('stdlib_module_no_solver_imports',lambda:None if not banned else (_ for _ in ()).throw(AssertionError(banned)),True)
    target=(ROOT/args.output).resolve()
    if not target.is_relative_to(ROOT/'reviews/diagnostics_scope'):raise ValueError('Fixture output outside review boundary')
    receipt={'schema_version':1,'status':'PASS' if not violations else 'FAIL','checks':checks,'check_count':len(checks),
             'violations':violations,'source_sha256':{'experiments/diagnostics/gated_m4.py':gate.digest(ROOT/'experiments/diagnostics/gated_m4.py'),
                                                     'experiments/diagnostics/check_gated_m4.py':gate.digest(Path(__file__))},
             'actual_graph_or_truth_loaded':False,'actual_M4_raw_read':False,'numpy_imported_by_helper':False,
             'diagnostic_workers_started':False,'artificial_paired_queries':432,'synthetic_plan_tasks':5184,
             'fixture_wall_seconds':time.perf_counter()-start,'actual_gate_verification':'NOT_RUN','actual_diagnostics':'NOT_RUN'}
    gate.publish(target,gate.canonical(receipt));print(json.dumps({'status':receipt['status'],'checks':len(checks),'violations':violations}))
    if violations:raise SystemExit(1)


if __name__=='__main__':main()
