"""Tiny receipt-contract fixture; no actual Graph/raw/NumPy/algorithm reads."""
from pathlib import Path
import importlib.util, tempfile, json, hashlib, csv
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'experiments/m6_analysis/audit.py'
spec=importlib.util.spec_from_file_location('independent_m6_audit',SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,sort_keys=True)+'\n')
def fixture(root):
 run=root/'results/m6_prepared';run.mkdir(parents=True)
 config={'implementation_version':m.VERSION}
 pins={}
 for name in m.SOURCES:
  p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}\n' if name==m.CONFIG else 'artificial source; no execution\n');pins[name]=m.sha(p)
 save(root/m.CONFIG,config);pins[m.CONFIG]=m.sha(root/m.CONFIG)
 auditor=root/'experiments/m6_analysis/audit.py';auditor.parent.mkdir(parents=True,exist_ok=True);auditor.write_bytes(SOURCE.read_bytes())
 schedule=[{'query_id':f'artificial_case{i//12}_q{i%12:02d}','case_id':f'artificial_case{i//12}','n':[10000,100000,1000000][i//36],'generation_seed':i//12,'seed':i} for i in range(108)]
 rows=[dict(q,status='completed' if i==0 else 'timeout' if i==1 else 'NOT_RUN',attempt_count=1 if i<2 else 0) for i,q in enumerate(schedule)]
 for i in range(2):rows[i]['raw_directory']=f'results/m6_prepared/queries/{rows[i]["query_id"]}/attempt_000'
 rows[0].update(F1=.5,hull_best_F1=.75,covered=True,failure_class='H2')
 manifest={'source_sha256':pins,'configuration':config,'config_sha256':m.sha(root/m.CONFIG),'implementation_version':m.VERSION,'source_state':'SOURCE_FROZEN','legacy_measurements_imported':False,'dependency_fingerprint':{},'schedule':schedule}
 save(run/'manifest.json',manifest)
 summary={'completed_queries':1,'status_counts':{'completed':1,'timeout':1,'NOT_RUN':106}}
 save(run/'summary.json',summary)
 fields=sorted(set().union(*(r.keys() for r in rows)))
 with (run/'query_summary.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 files={str((run/name).relative_to(root)):m.sha(run/name) for name in ['manifest.json','summary.json','query_summary.csv']}
 files.update(pins)
 attempts=[]
 for i in range(2):
  row=rows[i];hashes={}
  for name in ['request.json','terminal.json']+(['result.json'] if i==0 else []):
   target=root/row['raw_directory']/name;save(target,{'artificial':True});hashes[name]=m.sha(target);files[str(target.relative_to(root))]=m.sha(target)
  attempts.append({'query_id':row['query_id'],'directory':row['raw_directory'],'status':row['status'],'artifact_sha256':hashes})
 receipt={'schema_version':1,'status':'PASS','cohort_origin':'ORIGINAL_FROZEN_COHORT','run_path':'results/m6_prepared','implementation_version':m.VERSION,'scheduled_queries':108,'completed_queries':1,'all_queries_completed':False,'status_counts':summary['status_counts'],'query_records':rows,'completed_quality_checks':[{'query_id':rows[0]['query_id'],'attempt':rows[0]['raw_directory'],'F1':.5,'hull_F1':.75,'C_subset_R':True,'failure_class':'H2'}],'validated_files_sha256':files,'algorithm_or_numpy_imported':False,'measurement_sources_inputs_raw_or_timers_modified':False,'source_sha256':pins,'config_sha256':manifest['config_sha256'],'dependency_fingerprint':{},'attempt_records':attempts,'manifest_sha256':m.sha(run/'manifest.json'),'summary_sha256':m.sha(run/'summary.json'),'query_csv_sha256':m.sha(run/'query_summary.csv'),'auditor_source_sha256':m.sha(auditor)}
 return receipt
results=[]
with tempfile.TemporaryDirectory(prefix='m6_receipt_independent_') as td:
 root=Path(td).resolve();receipt=fixture(root);p=root/'results/m6_analysis/receipt.json'
 def attempt(label,value,should_accept):
  value['receipt_payload_sha256']=m.object_sha({k:v for k,v in value.items() if k!='receipt_payload_sha256'});save(p,value)
  try:m.verify_audit_receipt(p); accepted=True;error=None
  except Exception as e:accepted=False;error=repr(e)
  results.append({'label':label,'accepted':accepted,'expected_accepted':should_accept,'pass':accepted==should_accept,'error':error})
 attempt('valid_tiny_contract',json.loads(json.dumps(receipt)),True)
 bad=json.loads(json.dumps(receipt));bad['completed_quality_checks'][0]['query_id']=receipt['query_records'][1]['query_id'];attempt('quality_record_bound_to_timeout_query',bad,False)
 bad=json.loads(json.dumps(receipt));bad['query_records'][1]['F1']=1.;attempt('timeout_record_claims_F1_not_in_CSV',bad,False)
 bad=json.loads(json.dumps(receipt));bad['query_records'][0]['F1']=1.;attempt('receipt_F1_disagrees_with_bound_CSV',bad,False)
 bad=json.loads(json.dumps(receipt));bad['completed_quality_checks'][0]['F1']=1.;attempt('independent_quality_disagrees_with_completed_row',bad,False)
value={'auditor_source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'fixtures':results,'actual_raw_or_graph_read':False,'numpy_or_algorithm_imported':False,'initial_control_fixture_adjustment':'Single-case tiny plan rejected by newly added 3-scale/9-case census; corrected artificial plan before counting tests.'}
output=Path(__file__).with_name('independent_receipt_fixture_results.json');output.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2))
