#!/usr/bin/env python3
"""Audit terminal NOCD inference artifacts only; never read labels or scores."""
from pathlib import Path
import datetime, hashlib, json, os, tempfile, traceback
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'work/baseline73_v2'
OUT=ROOT/'analysis/artifact_audit'
torch.set_num_threads(1)

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

snapshot=[];audited=[];skipped=[]
for folder in sorted(RUN.glob('*__nocd_graph_oracleK__s73')):
    result_path=folder/'result.json'
    if not result_path.exists():
        skipped.append({'job_id':folder.name,'reason':'no terminal result.json; model files not opened'})
        continue
    result_bytes=result_path.read_bytes()
    try:result=json.loads(result_bytes)
    except Exception as exc:
        skipped.append({'job_id':folder.name,'reason':'result.json unreadable; model files not opened','error':str(exc)})
        continue
    snapshot.append({'job_id':folder.name,'status':result.get('status')})
    if result.get('status')!='COMPLETED':
        skipped.append({'job_id':folder.name,'reason':'terminal status is not COMPLETED; model files not opened','status':result.get('status')})
        continue
    row={'job_id':folder.name,'status':'COMPLETED','path':str(folder.relative_to(ROOT)),'checks':{},'files':{}}
    files=['result.json','prediction.json','best_embedding.npy','initial_embedding.npy','best_model.pt','checkpoint.json']
    try:
        pre={f:(folder/f).stat() for f in files}
        pred=json.loads((folder/'prediction.json').read_text())
        best=np.load(folder/'best_embedding.npy',allow_pickle=False)
        initial=np.load(folder/'initial_embedding.npy',allow_pickle=False)
        model=torch.load(folder/'best_model.pt',map_location='cpu',weights_only=True)
        trace=pred['trace']
        lowest=min(trace,key=lambda x:x['training_reconstruction_loss'])
        decoded=[np.flatnonzero(best[:,c]>.5).astype(int).tolist() for c in range(best.shape[1])]
        state_tensors=[v for v in model['state_dict'].values() if torch.is_tensor(v)]
        checks={
            'best_embedding_rank_two':best.ndim==2,
            'initial_embedding_same_shape':initial.shape==best.shape,
            'best_embedding_finite':bool(np.isfinite(best).all()),
            'initial_embedding_finite':bool(np.isfinite(initial).all()),
            'embedding_k_matches_explicit_known_k':best.shape[1]==pred['metadata']['known_k'],
            'best_embedding_gt_point5_decodes_to_prediction':decoded==pred['communities'],
            'best_model_weights_only_load':True,
            'best_model_state_dict_tensors_finite':bool(state_tensors) and all(bool(torch.isfinite(t).all()) for t in state_tensors),
            'best_model_epoch_is_first_min_trace_epoch':model['epoch']==lowest['epoch'],
            'best_model_loss_matches_min_trace_loss':abs(float(model['training_loss'])-float(lowest['training_reconstruction_loss']))<1e-9,
            'optimizer_state_present':'optimizer_state_dict' in model,
            'result_still_terminal_unchanged':result_path.read_bytes()==result_bytes,
        }
        row.update(best_embedding_shape=list(best.shape),initial_embedding_shape=list(initial.shape),saved_model_epoch=int(model['epoch']),trace_minimum_epoch=int(lowest['epoch']),trace_count=len(trace),prediction_kind=pred['metadata'].get('kind'))
        for f in files:
            path=folder/f;s=path.stat()
            row['files'][f]={'sha256':sha(path),'size_bytes':s.st_size}
            if (pre[f].st_size,pre[f].st_mtime_ns)!=(s.st_size,s.st_mtime_ns):raise RuntimeError('Terminal artifact changed during read: '+f)
        checks['files_unchanged_during_read']=True
        row['checks']=checks;row['audit_pass']=all(checks.values())
        row['bound_hashes']={k:result.get(k) for k in ['graph_sha256','config_sha256','prediction_sha256']}
        row['recorded_source_hashes']=result.get('source_hashes',{})
        row['checks']['prediction_hash_matches_runner_record']=row['files']['prediction.json']['sha256']==result.get('prediction_sha256')
        row['audit_pass']=all(row['checks'].values())
    except Exception as exc:
        row.update(audit_pass=False,error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    audited.append(row)

report={'audit_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run_directory':str(RUN.relative_to(ROOT)),'scope':'Only completed terminal NOCD jobs present in this directory snapshot; no algorithm execution, labels, evaluation_only, or quality scores read. Training reconstruction loss used solely for checkpoint consistency.','completed_jobs_audited':len(audited),'passing_jobs':sum(r['audit_pass'] for r in audited),'failing_jobs':sum(not r['audit_pass'] for r in audited),'snapshot_statuses':snapshot,'skipped':skipped,'all_audited_pass':bool(audited) and all(r['audit_pass'] for r in audited),'rows':audited,'limitations':['Artifact integrity does not prove convergence, community recovery quality or full baseline completion.','Jobs absent/nonterminal at snapshot are not audited; rerun this script after they complete.','Checkpoint selection is based on full training reconstruction loss, not true labels.']}
OUT.mkdir(parents=True,exist_ok=True)
fd,tmp=tempfile.mkstemp(dir=OUT,prefix='.nocd_completed_audit.')
with os.fdopen(fd,'w') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
os.replace(tmp,OUT/'nocd_completed_audit.json')
text=f"# 已完成 NOCD artifacts 完整性审计\n\n审计UTC：{report['audit_utc']}。只读取 baseline73_v2 已终态 COMPLETED 的 NOCD 任务；没有执行算法、读取真标签/evaluation_only 或质量分数。\n\n本次快照审计 {len(audited)} 项，通过 {report['passing_jobs']} 项，失败 {report['failing_jobs']} 项；跳过 {len(skipped)} 项。逐文件 SHA-256、实际shape、checkpoint epoch、所有检查在 nocd_completed_audit.json。\n\n检查涵盖 initial/best embedding 有限、形状/K一致、best embedding >.5 解码与最终cover逐组一致、best_model.pt weights_only加载与有限state、saved epoch/loss对应trace首次最低full训练loss，以及文件读取期间未变和prediction hash与runner记录一致。\n\n这仅证明该快照内推断artifacts的一致性；不证明收敛、恢复质量、全部基线任务完成。未终态/尚未出现的任务需要后续重跑审计。\n\n可重跑：`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python analysis/artifact_audit/audit_completed_nocd.py`。\n"
(OUT/'nocd_completed_audit_report.md').write_text(text)
print(json.dumps({'completed_jobs_audited':len(audited),'passing_jobs':report['passing_jobs'],'failing_jobs':report['failing_jobs'],'skipped':len(skipped),'all_audited_pass':report['all_audited_pass']}))
