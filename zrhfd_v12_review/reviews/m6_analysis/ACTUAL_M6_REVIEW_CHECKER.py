"""Actual independent stdlib M6 review; fixed q00 per graph, no resampling.

No Graph/NumPy/pipeline/production evaluation import. All99 aggregate rows come
from the already-completed independent audit; eight completed fixed q00 covers
are evaluated anew from sets, while the ninth remains its original timeout.
"""
from collections import Counter,defaultdict
from fractions import Fraction
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import math
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
 return h.hexdigest()


def read(path):return json.loads(Path(path).read_text())


def close(a,b):return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9)


def stats(rows):
 f=[r['F1'] for r in rows];hot=[r['method_hot_wall_seconds'] for r in rows]
 classes=Counter('exact' if r['F1']==1 else r['failure_class'] for r in rows)
 return {'completed':len(rows),'F1_mean':statistics.fmean(f),'F1_median':statistics.median(f),
         'hull_F1_mean':statistics.fmean(r['hull_best_F1'] for r in rows),
         'hull_F1_median':statistics.median(r['hull_best_F1'] for r in rows),
         'F1_below_point5':sum(r['F1']<.5 for r in rows),'classes':dict(classes),
         'covered_count':sum(r['covered'] for r in rows),'hot_mean':statistics.fmean(hot),
         'hot_median':statistics.median(hot),'parent_median':statistics.median(r['parent_process_wall_seconds'] for r in rows),
         'touched_over_output_median':statistics.median(r['touched_over_output_volume'] for r in rows),
         'target_size_outliers':sum(r['target_size_outlier'] for r in rows),'planned':36}


def ols(rows,field,adjusted):
 x=[math.log(r['n']) for r in rows];y=[math.log(r[field]) for r in rows]
 mx,my=statistics.fmean(x),statistics.fmean(y)
 xx=sum((v-mx)**2 for v in x);xy=sum((a-mx)*(b-my) for a,b in zip(x,y))
 if not adjusted:b=xy/xx;return {'intercept':my-b*mx,'logn_slope':b,'logtruthvol_slope':None}
 z=[math.log(r['median_target_volume']) for r in rows];mz=statistics.fmean(z)
 zz=sum((v-mz)**2 for v in z);xz=sum((a-mx)*(b-mz) for a,b in zip(x,z));zy=sum((a-mz)*(b-my) for a,b in zip(z,y))
 determinant=xx*zz-xz*xz
 b=(xy*zz-zy*xz)/determinant;c=(zy*xx-xy*xz)/determinant
 return {'intercept':my-b*mx-c*mz,'logn_slope':b,'logtruthvol_slope':c}


def main():
 started=time.perf_counter();cpu=time.process_time();self_sha=sha(Path(__file__))
 receipt_path=ROOT/'results/m6_analysis/prepared_audit/receipt.json';audit=read(receipt_path)
 source=ROOT/'experiments/m6_analysis/audit.py';spec=importlib.util.spec_from_file_location('independent_receipt_validator',source)
 validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
 verified=validator.verify_audit_receipt(receipt_path,verify_files=False)
 assert verified['status']=='PASS' and not verified['files_reverified_now']
 run=ROOT/'results/m6_prepared';manifest=read(run/'manifest.json');summary=read(run/'summary.json')
 assert sha(run/'manifest.json')==audit['manifest_sha256']==summary['manifest_sha256']
 assert sha(run/'summary.json')==audit['summary_sha256'];assert sha(run/'query_summary.csv')==audit['query_csv_sha256']
 for name,expected in manifest['source_sha256'].items():assert sha(ROOT/name)==expected==audit['source_sha256'][name]
 csv_rows=list(csv.DictReader((run/'query_summary.csv').open()));records=audit['query_records'];lookup={r['query_id']:r for r in records}
 assert len(csv_rows)==len(records)==len(lookup)==108 and len({r['query_id'] for r in csv_rows})==108
 for row in csv_rows:
  original=lookup[row['query_id']]
  for key,value in row.items():assert value==('' if original.get(key) is None else str(original[key])),(row['query_id'],key)
 assert Counter(r['status'] for r in records)==Counter({'completed':99,'timeout':8,'error':1})
 assert Counter(r['n'] for r in records)==Counter({10000:36,100000:36,1000000:36})
 assert sorted(Counter(r['case_id'] for r in records).values())==[12]*9
 completed=[r for r in records if r['status']=='completed'];failures=[r for r in records if r['status']!='completed']
 quality_checks={r['query_id']:r for r in audit['completed_quality_checks']}
 assert set(quality_checks)=={r['query_id'] for r in completed}
 for row in completed:
  c=quality_checks[row['query_id']]
  assert (row['F1'],row['hull_best_F1'],row['covered'],row['failure_class'])==(c['F1'],c['hull_F1'],c['C_subset_R'],c['failure_class'])
  assert all(math.isfinite(row[key]) for key in ('F1','hull_best_F1','method_hot_wall_seconds','parent_process_wall_seconds','touched_over_output_volume'))
 for row in failures:
  assert all(key not in row for key in ('F1','hull_best_F1','covered','failure_class','method_hot_wall_seconds','touched_over_output_volume'))
 for n in (10000,100000,1000000):assert dict(Counter(r['status'] for r in records if r['n']==n))==summary['status_counts_by_n'][str(n)]
 by_n={str(n):stats([r for r in completed if r['n']==n]) for n in (10000,100000,1000000)}
 ratio=statistics.median(r['touched_over_output_volume'] for r in completed)
 exact_ratios=[Fraction(str(r['touched_volume']))/Fraction(str(r['output_volume'])) for r in completed]
 for row,value in zip(completed,exact_ratios):assert close(float(value),row['touched_over_output_volume'])
 above20=sum(value>20 for value in exact_ratios)
 assert above20==sum(r['touched_over_output_volume']>20 for r in completed)==58 and above20>108/2
 assert ratio==summary['median_touched_over_output_volume_completed_only'] and ratio>20
 assert summary['all_queries_completed'] is False and summary['ratio_median_le_20'] is False
 assert summary['gate_assessment']=='NOT_ESTABLISHED_INCOMPLETE_COHORT'
 graph_data=[]
 for case in sorted({r['case_id'] for r in records}):
  rows=[r for r in completed if r['case_id']==case]
  graph_data.append({'case_id':case,'n':rows[0]['n'],'completed_queries':len(rows),
          **{'median_'+key:statistics.median(r[key] for r in rows) for key in ('method_hot_wall_seconds','parent_process_wall_seconds','target_volume','touched_volume','touched_over_output_volume')}})
 assert graph_data==summary['graph_summaries']
 fit_checks={}
 for field in ('method_hot_wall_seconds','parent_process_wall_seconds','touched_volume'):
  for adjusted in (False,True):
   key=field+('_logtruthvol_adjusted' if adjusted else '_raw_logn');fit=ols(graph_data,'median_'+field,adjusted);published=summary['fits'][key]
   for name,value in fit.items():assert value is None and published[name] is None or value is not None and close(value,published[name])
   assert published['status']=='DESCRIPTIVE_COMPLETED_ONLY' and published['graph_count']==9 and published['bootstrap_valid_replicates']==2000
   fit_checks[key]={'independent_centered_OLS':fit,'published_bootstrap_95_ci':published['graph_cluster_bootstrap_95_ci'],
                    'independent_bootstrap_recomputed':False,'role':'Completed-only descriptive estimate; CI uses frozen published procedure'}
 # Nested/subset timers must not be added as mutually exclusive costs.
 cost=[]
 phase_keys=('source_verification_seconds','imports_seconds','numba_compile_or_cache_seconds','toy_pipeline_warmup_seconds',
             'input_load_seconds','method_hot_wall_seconds','raw_method_serialization_seconds','offline_evaluation_seconds')
 for row in completed:
  hot=row['method_hot_wall_seconds'];parent=row['parent_process_wall_seconds'];worker=row['worker_to_result_seconds']
  assert parent>=worker>=hot>=row['pipeline_internal_seconds']
  phases=sum(row[k] for k in phase_keys);assert worker+1e-6>=phases
  work=sum(row[k] for k in ('prepared_topology_seconds','prepared_cut_assembly_seconds','prepared_cut_native_subprocess_seconds','prepared_cut_objective_validation_seconds'))
  assert hot+1e-6>=work
  cost.append({'query_id':row['query_id'],'parent_minus_hot_seconds':parent-hot,'parent_minus_worker_pre_finalserialization_seconds':parent-worker,
               'worker_minus_disjoint_phase_seconds':worker-phases,'prepared_workspace_phase_fraction_of_hot':work/hot,
               'native_cut_fraction_of_hot':row['prepared_cut_native_subprocess_seconds']/hot})
 # Fixed q00 selection. The timeout is retained, without selecting another seed.
 schedule={q['query_id']:q for q in manifest['schedule']};attempts={a['query_id']:a for a in audit['attempt_records']}
 fixed=[r for r in records if r['query_id'].endswith('_q00')];assert len(fixed)==9
 sample=[];sample_hashes={};noncompleted=[]
 for row in fixed:
  directory=ROOT/row['raw_directory'];entry=attempts[row['query_id']];q=schedule[row['query_id']]
  for name in ('request.json','terminal.json'):
   expected=entry['artifact_sha256'][name];actual=sha(directory/name);assert actual==expected
   sample_hashes[str((directory/name).relative_to(ROOT))]=actual
  req=read(directory/'request.json');terminal=read(directory/'terminal.json')
  assert req['query']==q and req['query_id']==row['query_id'] and req['source_sha256']==manifest['source_sha256']
  assert req['method_config']==manifest['configuration']['method_config'] and req['manifest_sha256']==audit['manifest_sha256']
  assert terminal['request_sha256']==sha(directory/'request.json') and terminal['status']==row['status']
  if row['status']!='completed':
   sample.append({'query_id':row['query_id'],'status':row['status'],'sample_reselected':False,'quality_recomputed':False,
                  'reason':'Fixed q00 timed out; no formal cover/quality and no replacement','stage':row['last_checkpoint_stage']});continue
  result_path=directory/'result.json';actual=sha(result_path)
  assert actual==entry['artifact_sha256']['result.json']==terminal['result_sha256'];sample_hashes[str(result_path.relative_to(ROOT))]=actual
  result=read(result_path);assert result['status']=='completed' and terminal['returncode']==0
  assert result['request_sha256']==sha(directory/'request.json') and result['input']==q
  output=result['raw_output'];S=set(output['vertices']);R=set(output['region_vertices']);H=set(output['certificate']['hull_best'])
  assert q['seed'] in S and q['seed'] in R and S<=R and H<=R
  truth_path=ROOT/q['offline_only']['truth_path'];actual=sha(truth_path)
  assert actual==q['offline_only']['truth_sha256']==audit['validated_files_sha256'][str(truth_path.relative_to(ROOT))]
  sample_hashes[str(truth_path.relative_to(ROOT))]=actual
  communities=read(truth_path)['communities'];C=set(communities[q['offline_only']['community_index']])
  def quality(T):
   overlap=len(T&C)
   return {'F1_exact':str(Fraction(2*overlap,len(T)+len(C))),'F1':2*overlap/(len(T)+len(C)),
           'precision':overlap/len(T) if T else 0.,'recall':overlap/len(C),'symmetric_difference':len(T^C)}
  own=quality(S);hull=quality(H);covered=C<=R;failure=None if S==C else 'H2' if covered else 'H1'
  for field in ('F1','precision','recall','symmetric_difference'):
   assert own[field]==result['offline_only']['quality'][field];assert hull[field]==result['offline_only']['hull_best_quality'][field]
  assert own['F1']==row['F1']==quality_checks[row['query_id']]['F1']
  assert hull['F1']==row['hull_best_F1']==quality_checks[row['query_id']]['hull_F1']
  assert covered==row['covered']==quality_checks[row['query_id']]['C_subset_R'] and failure==row['failure_class']
  sample.append({'query_id':row['query_id'],'status':'completed','sample_reselected':False,'quality_recomputed':True,
                 'output_quality':own,'hull_quality':hull,'C_subset_R':covered,'failure_class':failure,
                 'output_size':len(S),'truth_size':len(C),'region_size':len(R),'seed_and_region_inclusion_checked':True})
  del result,output,communities,S,R,H,C
 for row in failures:
  directory=ROOT/row['raw_directory'];terminal=read(directory/'terminal.json');expected=attempts[row['query_id']]['artifact_sha256']
  assert sha(directory/'terminal.json')==expected['terminal.json'];assert terminal['status']==row['status']
  assert terminal['returncode']!=0 and not (directory/'result.json').exists()
  assert not (directory/'method_result.json').exists()
  noncompleted.append({'query_id':row['query_id'],'n':row['n'],'status':row['status'],'last_stage':row['last_checkpoint_stage'],
     'observed_parent_not_completed_seconds':row['parent_process_wall_seconds'],'runtime_censored_OS_budget_flag':row['runtime_censored'],
     'formal_result_exists':False,'method_result_exists':False,'quality_claim':False,
     'error_message':read(directory/'error.json').get('exception') if (directory/'error.json').exists() else None})
 provenance_path=ROOT/'figures/m6/prepared_v001/provenance.json';fig=read(provenance_path)
 for field,value in (('receipt_sha256',sha(receipt_path)),('scheduled_queries',108),('completed_queries',99)):
  assert fig['integrity_audit'][field]==value
 assert fig['summary_sha256']==audit['summary_sha256'] and fig['query_csv_sha256']==audit['query_csv_sha256']
 assert fig['manifest_sha256']==audit['manifest_sha256'] and fig['status_counts']==audit['status_counts']
 assert fig['full_cohort_completed'] is False and fig['legacy_measurements_imported'] is False
 for name,expected in fig['figure_sha256'].items():assert sha(provenance_path.parent/name)==expected
 assert sha(ROOT/'experiments/plot_m6.py')==fig['plot_source_sha256']
 report= (ROOT/'REPORT.md').read_text()
 assert '99完成、8超时、1' in report and '23.789474' in report and '不能宣布完整次线性' in report
 assert sha(Path(__file__))==self_sha
 outcome={'schema_version':1,'status':'ACCEPT_ACTUAL_RECORDS_AND_CENSORING_WITH_LIMITATIONS','scientific_GATE_G_E3':'FAIL: locality median requirement excluded by58 observed ratios>20 of108 planned; runtime sublinearity remains NOT_ESTABLISHED',
   'locality_threshold_negative_evidence':{'observed_completed_ratios_above20':above20,'observed_completed':99,'planned_queries':108,'unobserved_ratios':9,
       'more_than_half_of_planned_queries_already_above20':True,'unseen_values_imputed':False,
       'scope':'Any eventual values for9unknown queries cannot make108-query median<=20. Existing automatic incomplete-cohort summary remains unchanged; no runtime sublinearity conclusion.'},
   'cohort':{'scheduled':108,'completed':99,'timeout':8,'error':1,'by_n':by_n},'completed_overall':stats(completed)|{'planned':108},
   'completed_only_ratio_median':ratio,'graph_medias_recomputed':graph_data,'fit_checks':fit_checks,
   'cost_checks':{'completed_rows_checked':99,'all_parent_worker_hot_ordered':True,'all_disjoint_worker_phases_bounded':True,
                 'all_workspace_phase_sums_bounded_by_hot':True,'parent_minus_hot_median':statistics.median(r['parent_minus_hot_seconds'] for r in cost),
                 'native_cut_fraction_of_hot_median':statistics.median(r['native_cut_fraction_of_hot'] for r in cost),'per_query':cost,
                 'semantics':'Hot includes prepared adapter/full pipeline/progress I/O; workspace and diffusion timers are nested subsets. Parent includes startup/import/warmup/input/offline evaluation/final serialization/poll overhead. Controller barrier/storage elapsed is not query completion cost.'},
   'fixed_q00_samples':sample,'fixed_q00_planned':9,'fixed_q00_quality_recomputed':sum(s['quality_recomputed'] for s in sample),
   'fixed_q00_timeout_retained':1,'sample_actual_files_sha256':sample_hashes,'noncompleted_rows':noncompleted,
   'source16_reverified_now':True,'audit_metadata_reverified':verified,'whole99_file_inventory_rehashed_again':False,
   'input_CSR_array_hashes':'Root/M0 full actual audit verified; not rehashed again here. Selected raw/request/truth byte hashes independently rechecked.',
   'figure_provenance_and_all12_bytes_verified':True,'figures_visually_rechecked_here':False,
   'inputs_sha256':{'audit_receipt':sha(receipt_path),'manifest':sha(run/'manifest.json'),'summary':sha(run/'summary.json'),
                  'query_csv':sha(run/'query_summary.csv'),'figure_provenance':sha(provenance_path),'REPORT':sha(ROOT/'REPORT.md'),
                  'review_checker':self_sha},'actual_command':[sys.executable,*sys.argv],
   'review_cpu_seconds_before_serialization':time.process_time()-cpu,'review_wall_seconds_before_serialization':time.perf_counter()-started,
   'production_evaluation_called':False,'Graph_NumPy_algorithms_imported':False,'pipeline_invocations':0,
   'limitations':['Completion is budget execution, not convergence/global recovery.','Regional certificate/gap does not imply recovery.',
                  'Three graphs per scale and fixed regimes; incomplete graph medians use only completed queries.',
                  'Bootstrap intervals source/procedure checked; no second bootstrap resampling here.',
                  'Q00 set-quality recomputation covers8completed examples plus1fixed timeout, not99 new truth recomputations.',
                  'Active-set exception probe remains NOT_RUN; numerical failure is not a frozen-theory counterexample.']}
 target=ROOT/'reviews/m6_analysis/ACTUAL_M6_REVIEW.json'
 with target.open('x') as stream:json.dump(outcome,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
 print(json.dumps({'status':outcome['status'],'completed':99,'q00_recomputed':8,'fixed_timeout':1,'ratio':ratio,
                   'wall':outcome['review_wall_seconds_before_serialization'],'CPU':outcome['review_cpu_seconds_before_serialization']}))


if __name__=='__main__':main()
