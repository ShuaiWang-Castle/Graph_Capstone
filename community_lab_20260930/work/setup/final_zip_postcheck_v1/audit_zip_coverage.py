#!/usr/bin/env python3
"""Read actual ZIP coverage/bindings only; no inference, scorer or whole-ZIP SHA."""
from pathlib import Path, PurePosixPath
import collections, datetime, hashlib, json, sys, zipfile

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
EXPECTED_ZIP_BYTES=2217948855
EXPECTED_ZIP_SHA='7718b644667b7576a6c6928fc37288d400f5224b120dff5c2425ec27ebd8094a'
ERRORS=[];CHECKS=[];READ_HASHES={}
def check(name,ok,detail=None):
    CHECKS.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
    if not ok:ERRORS.append({'name':name,'detail':detail})
def digest(data): return hashlib.sha256(data).hexdigest()
def main():
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    archive=ROOT/'DELIVERY.zip';sidecar=ROOT/'DELIVERY.sha256.json'
    side=json.loads(sidecar.read_text())
    with zipfile.ZipFile(archive) as z:
        names=z.namelist();entries={i.filename:i for i in z.infolist()};name_set=set(names)
        def read(path):
            data=z.read(path);READ_HASHES[path]={'sha256':digest(data),'size_bytes':len(data)};return data
        def load(path): return json.loads(read(path))
        manifest=load('DELIVERY_MANIFEST.json');m={r['path']:r for r in manifest['files']}
        index=load('provenance/replay_index.json');closeout=load('provenance/final_closeout.json')
        check('actual_zip_size_and_reported_whole_SHA',archive.stat().st_size==side['bytes']==EXPECTED_ZIP_BYTES and side['sha256']==EXPECTED_ZIP_SHA,{'bytes':archive.stat().st_size,'reported_sha256':side['sha256'],'whole_SHA_recomputed_here':False})
        check('no_duplicate_or_unsafe_archive_paths',len(names)==len(name_set) and all(not PurePosixPath(p).is_absolute() and '..' not in PurePosixPath(p).parts and '\\' not in p for p in names))
        check('payload_17361_plus_one_manifest',len(m)==len(manifest['files'])==17361 and len(names)==17362 and name_set==set(m)|{'DELIVERY_MANIFEST.json'})
        check('all_central_directory_sizes_match_manifest',all(entries[p].file_size==r['bytes'] for p,r in m.items()))
        forbidden=[p for p in names if any(part in ['.venv','venv','.git'] for part in PurePosixPath(p).parts) or PurePosixPath(p).suffix.lower()=='.pdf']
        check('no_PDF_venv_git_in_outer_ZIP',not forbidden,forbidden)
        check('root_packager_actual_byte_verification_record',side['phase']=='final' and side['verified_all_zip_payload_hashes'] and side['verified_embedded_replay_index_payloads'] and side['verified_embedded_source_archive_sha256'],side)
        def metadata_binding(path,expected_hash,expected_size=None):
            if path not in m:return False
            return m[path]['sha256']==expected_hash and (expected_size is None or m[path]['bytes']==expected_size)
        for p,expected in closeout['report_sha256'].items():
            data=read(p);check('four_report_binding:'+p,digest(data)==expected and metadata_binding(p,expected,len(data)))
        for p,expected in closeout['evidence_sha256'].items():
            data=read(p);check('closeout_actual_evidence_binding:'+p,digest(data)==expected and metadata_binding(p,expected,len(data)))
        numerical=load('work/setup/candidate_final_artifact_audit/final_delivery_review/REPORT_NUMERICAL_REVIEW.json')
        check('closeout_four_current_report_versions',all(numerical['inputs'][p]['sha256']==expected for p,expected in closeout['report_sha256'].items()) and len(closeout['report_sha256'])==4)
        check('truthful_closed_gate_status',closeout['status']=='NO_REPRODUCIBLE_GAIN' and closeout['selected_claim_scope']=='none' and closeout['confirmation_gate_open'] is False and closeout['confirmation_graphs_generated']==0 and closeout['formal_status_counts']=={'COMPLETED':564,'TIMEOUT':12})
        check('canonical_replay_index_3017_metadata_binding',len(index['files'])==3017 and all(metadata_binding(p,r['sha256'],r['size_bytes']) for p,r in index['files'].items()))
        groups=[];all_jobs=[];formal_prefixes=set();nocd_prefixes=set()
        for group in index['groups']:
            statuses=collections.Counter();predictions=0;unknown=0;missing=[]
            for row in group['rows']:
                refs=row['references'];p=refs['result'];prefix=p.rsplit('/',1)[0];formal_prefixes.add(prefix)
                result_data=read(p);result=json.loads(result_data);spec_data=read(refs['spec']);spec=json.loads(spec_data)
                if not metadata_binding(p,digest(result_data),len(result_data)) or not metadata_binding(refs['spec'],digest(spec_data),len(spec_data)):missing.append(row['job_id']+':manifest_bytes')
                if digest(result_data)!=index['files'][p]['sha256'] or digest(spec_data)!=index['files'][refs['spec']]['sha256']:missing.append(row['job_id']+':index_bytes')
                if result['job_id']!=row['job_id'] or spec['job_id']!=row['job_id'] or result['status']!=row['measurement_status']:missing.append(row['job_id']+':identity_status')
                statuses[result['status']]+=1
                for kind in ['graph','truth','config']:
                    if refs[kind] not in name_set:missing.append(row['job_id']+':'+kind)
                for log in ['stdout.log','stderr.log']:
                    if prefix+'/'+log not in name_set:missing.append(row['job_id']+':'+log)
                if not result.get('command'):missing.append(row['job_id']+':actual_command')
                if row['measurement_status']=='COMPLETED':
                    pred=refs.get('prediction');pred_data=read(pred) if pred in name_set else None
                    if pred_data is None or digest(pred_data)!=result['prediction_sha256'] or digest(pred_data)!=index['files'][pred]['sha256']:missing.append(row['job_id']+':prediction')
                    if row['original_summary'].get('metric_status')!='SCORED':missing.append(row['job_id']+':scored')
                    predictions+=1
                elif row['measurement_status']=='TIMEOUT':
                    if refs.get('prediction') is not None or row['replay_eligibility']!='NO_COVER_QUALITY_UNKNOWN' or row.get('expected_metrics') is not None:missing.append(row['job_id']+':timeout_unknown')
                    if prefix+'/prediction.json' in name_set:missing.append(row['job_id']+':unexpected_timeout_prediction')
                    if row['original_summary'].get('matched_macro_f1') is not None or row['original_summary'].get('matched_membership_micro_f1') is not None:missing.append(row['job_id']+':timeout_imputed_quality')
                    unknown+=1
                else:missing.append(row['job_id']+':unexpected_status')
                if row['method'].startswith('nocd_'):
                    nocd_prefixes.add(prefix)
                    for artifact in ['best_model.pt','initial_embedding.npy','best_embedding.npy','checkpoint.json']:
                        if prefix+'/'+artifact not in name_set:missing.append(row['job_id']+':'+artifact)
                all_jobs.append({'group':group['name'],'job_id':row['job_id'],'prefix':prefix,'status':result['status'],'prediction_in_archive':refs.get('prediction') in name_set,'model_required':row['method'].startswith('nocd_')})
            check('formal_group_records_predictions_unknown:'+group['name'],not missing and dict(statuses)==group['status_counts'],{'planned':len(group['rows']),'actual_status_counts':dict(statuses),'predictions':predictions,'quality_unknown':unknown,'errors':missing})
            groups.append({'name':group['name'],'planned':len(group['rows']),'status_counts':dict(statuses),'predictions':predictions,'quality_unknown':unknown})
        check('formal576_records_564_predictions_12unknown',len(all_jobs)==576 and sum(r['predictions']for r in groups)==564 and sum(r['quality_unknown']for r in groups)==12)
        models={p+'/best_model.pt' for p in nocd_prefixes};check('formal336_model_jobs_present',len(models)==336 and models<=name_set,{'required_models':len(models),'all_archive_models_including_smoke_diag':sum(p.endswith('/best_model.pt')for p in names)})
        actual_covers={n for n in names if '/checkpoints/epoch_' in n and n.endswith('.json') and n.split('/checkpoints/')[0] in formal_prefixes}
        expected_covers={};expected_artifacts={}
        base=load('work/setup/infrastructure_audit/final_baseline_artifacts/FINAL_BASELINE_ARTIFACT_AUDIT.json')
        for row in base['nocd']:
            prefix='work/baseline73_v2/'+row['job_id']
            for rel,meta in row['files'].items():expected_artifacts[prefix+'/'+rel]=meta
            for cp in row['checkpoints']:expected_covers[cp['path']]=cp['sha256']
        for audit in ['C1_FINAL_ARTIFACT_AUDIT','AUTHOR_REFERENCE_FINAL_ARTIFACT_AUDIT']:
            d=load('work/setup/candidate_final_artifact_audit/actual_20260930T0859Z/'+audit+'.json')
            for row in d['rows']:
                root='work/nocd_pairdot_dev_all_v1' if audit.startswith('C1') else 'work/nocd_author_refcheck73_v1'
                for rel,meta in row['artifacts'].items():expected_artifacts[root+'/'+row['job_id']+'/'+rel]=meta
                for cp in row['nocd']['saved_checkpoints']:expected_covers[root+'/'+row['job_id']+'/'+cp['path']]=cp['sha256']
        cover_mismatches=[p for p,expected in expected_covers.items() if not metadata_binding(p,expected)]
        artifact_mismatches=[]
        for p,meta in expected_artifacts.items():
            size=meta.get('size_bytes',meta.get('bytes'))
            if not metadata_binding(p,meta['sha256'],size):artifact_mismatches.append(p)
        check('formal7879_saved_cover_exact_set_and_prior_hash_binding',actual_covers==set(expected_covers) and len(actual_covers)==7879 and not cover_mismatches,{'actual_count':len(actual_covers),'expected_count':len(expected_covers),'missing':sorted(set(expected_covers)-actual_covers),'unexpected':sorted(actual_covers-set(expected_covers)),'manifest_prior_hash_mismatch':cover_mismatches})
        check('all_prior_NOCD_model_embedding_log_cover_metadata_bound',not artifact_mismatches,{'prior_artifact_paths':len(expected_artifacts),'mismatches':artifact_mismatches,'scope':'Archive central sizes and embedded manifest SHA match prior actual artifact audits; model tensors/covers not re-loaded and all-payload byte verification not repeated.'})
        check('index_recorded_missing12_retained_not_expected_payload',len(index['missing_files'])==12 and all(p not in name_set for p in index['missing_files']))
        for required in ['provenance/locked_source_trees.tar.gz','provenance/locked_source_trees_manifest.json','provenance/SOURCE_LOCK.json','REPRODUCE.sh','docs/REPRODUCIBILITY_ZH.md','RESUME.md','reports/BASELINE_REPORT_ZH.md','reports/FAILURE_MAP_ZH.md','reports/CANDIDATE_DECISION_ZH.md','reports/FINAL_REPORT_ZH.md']:
            check('required_artifact_in_actual_ZIP:'+required,required in name_set)
        outcome={'started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'PASS' if not ERRORS else 'FAIL','archive':str(archive),'archive_bytes':archive.stat().st_size,'root_actual_whole_archive_sha256':side['sha256'],'whole_archive_SHA_recomputed_by_this_audit':False,'archive_entry_count':len(names),'payload_count':len(manifest['files']),'checks':CHECKS,'errors':ERRORS,'groups':groups,'formal_jobs':all_jobs,'read_member_byte_hashes':READ_HASHES,'actual_command_argv':[sys.executable,str(Path(__file__).resolve())],'tool_sha256':digest(Path(__file__).read_bytes()),'scope':'Reads actual ZIP central directory and selected record/spec/prediction/report/evidence bytes. No inference/scorer/training/rebuild. Prior model/checkpoint hashes bound against embedded payload manifest; root whole-payload byte checks were not repeated. Native/source/license deep check is a separate child audit.'}
        (OUT/'ZIP_COVERAGE_AUDIT.json').write_text(json.dumps(outcome,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps({'status':outcome['status'],'checks':dict(collections.Counter(c['status']for c in CHECKS)),'errors':[e['name'] for e in ERRORS],'groups':groups,'models':len(models),'checkpoint_covers':len(actual_covers),'read_hashed_members':len(READ_HASHES),'output':str(OUT/'ZIP_COVERAGE_AUDIT.json')},ensure_ascii=False))
        return 0 if not ERRORS else 1
if __name__=='__main__':raise SystemExit(main())
