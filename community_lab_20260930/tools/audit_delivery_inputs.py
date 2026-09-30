#!/usr/bin/env python3
"""Read-only closeout inventory; no inference, label scoring or raw rewriting."""
from pathlib import Path
import collections,csv,datetime,hashlib,json,sys
from portable_replay import validate_index
ROOT=Path(__file__).resolve().parents[1]
def load(relative):return json.loads((ROOT/relative).read_text())
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def main():
 index=load('provenance/replay_index.json');validate_index(index,ROOT)
 rows=[];errors=[];models=0;covers=0
 for group in index['groups']:
  for row in group['rows']:
   references=row['references'];raw=load(references['result']);folder=(ROOT/references['result']).parent;issues=[]
   for name in ['spec.json','stdout.log','stderr.log','result.json']:
    if not (folder/name).is_file():issues.append('missing '+name)
   for field in ['command','graph_sha256','config_sha256','source_hashes','pipeline_seconds','peak_tree_rss_bytes','returncode','budget_seconds']:
    if field not in raw:issues.append('missing raw '+field)
   if not raw.get('command') or not raw.get('source_hashes'):issues.append('missing actual command or source bindings')
   if raw.get('status')!=row['measurement_status']:issues.append('status mismatch')
   if raw.get('status')=='COMPLETED' and not references.get('prediction'):issues.append('completed without prediction')
   is_nocd='nocd' in row['method']
   checkpoint_files=list((folder/'checkpoints').glob('*.json'))
   covers+=len(checkpoint_files)
   if is_nocd:
    models+=1
    for name in ['best_model.pt','initial_embedding.npy','best_embedding.npy','checkpoint.json']:
     if not (folder/name).is_file():issues.append('missing NOCD '+name)
    if not checkpoint_files:issues.append('no saved cover checkpoints')
   if issues:errors.append({'job_id':row['job_id'],'issues':issues})
   rows.append({'group':group['name'],'job_id':row['job_id'],'case_id':row['case_id'],'status':row['measurement_status'],'replay_eligibility':row['replay_eligibility'],'raw_result':references['result'],'retained_saved_cover_checkpoints':len(checkpoint_files),'retained_nocd_model':is_nocd,'artifact_status':'FAIL' if issues else 'PASS'})
 manifests=['work/setup/infrastructure_audit/final_baseline_artifacts/INPUT_SHA256_MANIFEST.json','work/setup/candidate_final_artifact_audit/actual_20260930T0859Z/C1_FINAL_ARTIFACT_AUDIT_INPUT_HASHES.json','work/setup/candidate_final_artifact_audit/actual_20260930T0859Z/AUTHOR_REFERENCE_FINAL_ARTIFACT_AUDIT_INPUT_HASHES.json']
 checked={}
 for manifest in manifests:
  for item in load(manifest)['files']:
   path=item['path'];previous=checked.get(path)
   if previous and previous!=item['sha256']:errors.append({'path':path,'issue':'conflicting prior audit hashes'})
   if previous:continue
   p=ROOT/path
   if not p.is_file() or p.stat().st_size!=item['size_bytes'] or sha(p)!=item['sha256']:errors.append({'path':path,'issue':'prior artifact audit hash/size mismatch'})
   checked[path]=item['sha256']
 integrated=load('analysis/results.json');lookup={r['job_id']:r for r in integrated}
 if len(integrated)!=576 or len(lookup)!=576 or set(lookup)!={r['job_id'] for r in rows}:errors.append({'issue':'integrated denominator differs from indexed planned jobs'})
 for group in index['groups']:
  for row in group['rows']:
   combined=lookup[row['job_id']]
   for field,value in row['original_summary'].items():
    if combined.get(field)!=value:errors.append({'job_id':row['job_id'],'field':field,'issue':'integrated changed original measurement/score'})
 with (ROOT/'analysis/results.csv').open(newline='') as f:
  if [r['job_id'] for r in csv.DictReader(f)]!=[r['job_id'] for r in integrated]:errors.append({'issue':'integrated CSV order/denominator mismatch'})
 evidence=['verification/portable_replay_full_v1/audit.json','verification/source_restore_v2/audit.json','work/setup/infrastructure_audit/final_baseline_artifacts/FINAL_BASELINE_ARTIFACT_AUDIT.json','work/setup/candidate_final_artifact_audit/actual_20260930T0859Z/AUDIT_AGGREGATE.json','work/setup/nocd_author_refcheck_audit/results/audit_result.json','analysis/nocd_pairdot_gate_v1/gate-analysis.json','provenance/locked_source_trees_manifest.json']
 checks={'portable_564_match_12_unknown':load(evidence[0])['status']=='PASS' and load(evidence[0])['core_score_recomputed_matches']==564 and load(evidence[0])['quality_unknown_timeouts']==12,'source_1853_payload_mode_restored':load(evidence[1])['status']=='PASS' and load(evidence[1])['regular_files_restored']==1853,'initial_artifact_audit_observed_pass':load(evidence[2])['observed_checks_pass'],'new312_artifact_audit_observed_pass':load(evidence[3])['all_observed_checks_pass'],'all24_author_harness_exact':load(evidence[4])['all_cases_pass'],'frozen_gate_closed':load(evidence[5])['confirmation_gate_open'] is False,'source_tar_matches':sha(ROOT/'provenance/locked_source_trees.tar.gz')==load(evidence[6])['sha256'],'source_tar_no_pdfs':not any(Path(r['path']).suffix.lower()=='.pdf' for r in load(evidence[6])['files'])}
 for name in ['BASELINE_REPORT_ZH.md','FAILURE_MAP_ZH.md','CANDIDATE_DECISION_ZH.md','FINAL_REPORT_ZH.md']:checks['report_'+name]=(ROOT/'reports'/name).is_file()
 for q in ['tools/portable_replay.py','REPRODUCE.sh','docs/REPRODUCIBILITY_ZH.md','provenance/SOURCE_LOCK.json','provenance/dependency_versions.txt','provenance/protocol_freeze.json']:checks['required_'+q]=(ROOT/q).is_file()
 for q in ROOT.glob('provenance/licenses/*'):checks['license_'+q.name]=q.stat().st_size>0
 plots=[str(p.relative_to(ROOT)) for p in ROOT.glob('analysis/quality_cost_*.png')]+['analysis/nocd_pairdot_gate_v1/gate_quality_cost.png']
 checks['five_canonical_plots']=len(plots)==5 and all((ROOT/p).is_file() for p in plots)
 report={'audited_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'PASS' if not errors and all(checks.values()) else 'FAIL','formal_planned_rows':len(rows),'status_counts':dict(collections.Counter(r['status'] for r in rows)),'core_replay_index_files_verified':len(index['files']),'prior_terminal_artifact_hashes_reverified':len(checked),'retained_nocd_model_jobs':models,'retained_formal_saved_cover_checkpoints':covers,'checks':checks,'errors':errors,'evidence_sha256':{p:sha(ROOT/p) for p in evidence},'report_sha256':{'reports/'+name:sha(ROOT/'reports'/name) for name in ['BASELINE_REPORT_ZH.md','FAILURE_MAP_ZH.md','CANDIDATE_DECISION_ZH.md','FINAL_REPORT_ZH.md']},'plots_sha256':{p:sha(ROOT/p) for p in plots},'limitations':['No inference, full-loss regeneration, new score, OS resource telemetry or statistical claim. Models/states are retained and bound to prior actual artifact audits; this is a delivery inventory.','ZIP payload validation still must execute after this pre-package gate; it is not inferred from these checks.']}
 out=ROOT/'verification/final_required_artifacts_v1';out.mkdir(parents=True,exist_ok=True);(out/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
 with (out/'jobs.csv').open('w',newline='') as f:w=csv.DictWriter(f,list(rows[0]));w.writeheader();w.writerows(rows)
 print(json.dumps({k:report[k] for k in ['status','formal_planned_rows','status_counts','core_replay_index_files_verified','prior_terminal_artifact_hashes_reverified','retained_nocd_model_jobs','retained_formal_saved_cover_checkpoints','errors']}));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':sys.exit(main())
