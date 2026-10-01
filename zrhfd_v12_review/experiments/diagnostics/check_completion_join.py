"""Small artificial integrity checks; no graph, solver, or raw experiment reads."""
from collections import Counter
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.diagnostics.m4_completion_join import validate_query_rows,validate_primary_identity,classify,summarize

def main():
    queries=[]
    for split,count in [('dev',336),('test',432)]:
        for i in range(count):
            queries.append({'diagnostic_query_id':f'{split}-{i}','task':f'task-{i}',
                'split':split,'case_id':f'case-{i//12}','seed':i,'community_index':i%4,'upstream_run':split})
    fields=('diagnostic_query_id','task','split','case_id','seed','community_index')
    rows=[{k:q[k] for k in fields} for q in queries]
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append({'name':name,'status':'PASS'})
    check('all_768_missing_outcomes_preserved',len(validate_query_rows(queries,rows))==768)
    for name,mutate in [
        ('diagnostic_duplicate',lambda rs:rs.__setitem__(1,rs[0].copy())),
        ('diagnostic_unplanned_id',lambda rs:rs[0].__setitem__('diagnostic_query_id','unknown')),
        ('diagnostic_seed_changed',lambda rs:rs[0].__setitem__('seed',999)),
        ('diagnostic_split_changed',lambda rs:rs[0].__setitem__('split','test')),
        ('diagnostic_community_changed',lambda rs:rs[0].__setitem__('community_index',3))]:
        candidate=[r.copy() for r in rows];mutate(candidate)
        try:validate_query_rows(queries,candidate)
        except RuntimeError:check(name,True)
        else:check(name,False)
    duplicate=[q.copy() for q in queries];duplicate[1]=duplicate[0].copy()
    try:validate_query_rows(duplicate,rows)
    except RuntimeError:check('planned_duplicate',True)
    else:check('planned_duplicate',False)
    primary={'status':'COMPLETED','completion_claim':'True','j_act':'2','exact_recovery':'False','failure_class':'H1'}
    diag={'diagnostic_status':'TIMEOUT','static_exact_available':True,'failure_class':'H2'}
    check('timeout_retains_bound_static_H2',classify(primary,diag)=='H2')
    for status,claim in [('TIMEOUT','True'),('COMPLETED','False')]:
        check('partial_not_completed_'+status+'_'+claim,classify(dict(primary,status=status,completion_claim=claim),diag)=='PRIMARY_NOT_COMPLETED')
    check('unactivated_class',classify(dict(primary,j_act=''),diag)=='UNACTIVATED')
    check('no_false_recovery_from_failed_diagnosis',classify(primary,dict(diag,diagnostic_status='INTEGRITY_FAIL'))=='H1')
    allrows=[{'split':q['split'],'F1':None,'primary_status':'NOT_RUN','diagnostic_status':'NOT_RUN',
              'recovery_class':'PRIMARY_NOT_COMPLETED','H2_objective_comparison':None} for q in queries]
    panels=summarize(allrows)
    check('all_planned_denominators',panels['dev']['planned']==336 and panels['test']['planned']==432)
    check('absent_quality_not_imputed',all(p['by_recovery_class']['PRIMARY_NOT_COMPLETED']['F1_mean'] is None for p in panels.values()))
    check('empty_quality_counts_zero',all(p['by_recovery_class']['PRIMARY_NOT_COMPLETED']['completed_quality_queries']==0 for p in panels.values()))
    q=dict(queries[0],raw_path='results/fixture/result.json',primary_protocol_sha256='fixture-hash')
    p={'case_id':q['case_id'],'seed':str(q['seed']),'protocol_sha256':'fixture-hash'}
    job={'task':q['task'],'method':'zrhfd','setting':'no_volume','result_path':q['raw_path'],
         'protocol_sha256':'fixture-hash','query':{k:q[k] for k in ('split','case_id','seed','community_index')}}
    validate_primary_identity(p,q,job);check('actual_CSV_schema_has_no_split',True)
    job['query']['split']='test'
    try:validate_primary_identity(p,q,job)
    except RuntimeError:check('wrong_job_split_rejected',True)
    else:check('wrong_job_split_rejected',False)
    root=Path(__file__).resolve().parents[2];source=root/'experiments/diagnostics/m4_completion_join.py'
    receipt={'status':'PASS','checks':checks,'check_count':len(checks),'fixture_only':True,
             'graph_loaded':False,'solver_executed':False,'real_experiment_read':False,
             'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    output=root/'reviews/m4_analysis/completion_join_checks.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'status':'PASS','checks':len(checks),'fixture_only':True}))

if __name__=='__main__':main()
