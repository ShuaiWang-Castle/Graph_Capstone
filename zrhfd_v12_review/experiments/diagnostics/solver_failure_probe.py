"""Diagnostic replay of one frozen M6 request; no cover or quality is reported.

Default: describe the prepared probe without loading any experiment files.
--execute launches one budgeted child, verifies provenance before numerical
imports, and runs the unchanged pipeline/config with the prepared-cut adapter.
Exception frames are inspected after failure; sys.settrace is never installed.
This is a diagnostic replay, never a completed main-cohort retry or theorem test.
"""
from datetime import datetime,timezone
from pathlib import Path
from dataclasses import asdict
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import signal
import subprocess
import sys
import time
import traceback
import uuid

ROOT=Path(__file__).resolve().parents[2]
VERSION='M6_prepared_exact_cut_v001'
QUERY='lfr_scale_n1000000_s202610063_q10'
SOURCE_FILES=(
 'zrhfd/__init__.py','zrhfd/graph.py','zrhfd/storage.py','zrhfd/diffusion.py',
 'zrhfd/sweep.py','zrhfd/mincut.py','zrhfd/certificate.py','zrhfd/pipeline.py',
 'work/bin/mincut128','zrhfd/mincut128.cpp','zrhfd/experimental_cut_workspace.py',
 'experiments/m6_prepared/config.json','experiments/m6_prepared/common.py',
 'experiments/m6_prepared/run.py','experiments/m6_prepared/worker.py','experiments/m6_prepared/summarize.py')
ROLE='Independent solver exception diagnosis; no main completion, quality, or theory claim'


def utc():return datetime.now(timezone.utc).isoformat()


def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
 return h.hexdigest()


def read(path):return json.loads(Path(path).read_text())


def portable(name):
 p=Path(name)
 if p.is_absolute() or '..' in p.parts:raise ValueError('Nonportable project path')
 p=(ROOT/p).resolve()
 if not p.is_relative_to(ROOT):raise ValueError('Path escapes workspace')
 return p


def clean(value):
 if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [clean(v) for v in value]
 if isinstance(value,float) and not math.isfinite(value):return {'nonfinite_float':repr(value)}
 if hasattr(value,'item'):return clean(value.item())
 return value


def publish(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 data=(json.dumps(clean(value),sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
 if path.exists():
  if path.read_bytes()!=data:raise RuntimeError('Immutable artifact differs')
  return
 partial=path.parent/('.'+path.name+'.partial-'+str(uuid.uuid4()))
 with partial.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
 os.link(partial,path);partial.unlink()


def dependency():
 packages={}
 for name in ('numpy','scipy','numba','llvmlite'):
  dist=importlib.metadata.distribution(name)
  record=next((f for f in dist.files or [] if str(f).endswith('.dist-info/RECORD')),None)
  packages[name]={'version':dist.version,'distribution_record_sha256':sha(dist.locate_file(record)) if record else None}
 return {'python_binary_sha256':sha(Path(sys.executable).resolve()),'python_version':sys.version,'packages':packages}


def verify_request(request_path,helper_sha):
 """Stream-hash input provenance; no truth decoding and no numerical imports."""
 checked={}
 def check(path,expected=None):
  value=sha(path)
  if expected is not None and value!=expected:raise ValueError('SHA differs: '+str(path))
  checked[str(Path(path).relative_to(ROOT))]=value;return value
 req=read(request_path);check(request_path)
 if req.get('mode')!='formal' or req.get('query_id')!=QUERY or req.get('implementation_version')!=VERSION:
  raise ValueError('Only the named frozen formal failure request is supported')
 manifest_path=portable(req['manifest_path']);check(manifest_path,req['manifest_sha256']);manifest=read(manifest_path)
 if manifest.get('implementation_version')!=VERSION or manifest.get('legacy_measurements_imported') is not False or manifest.get('source_state')!='SOURCE_FROZEN':
  raise ValueError('Manifest is not the frozen prepared M6 cohort')
 if set(manifest['source_sha256'])!=set(SOURCE_FILES) or req['source_sha256']!=manifest['source_sha256']:
  raise ValueError('All16 frozen source identity differs')
 for name,expected in manifest['source_sha256'].items():check(portable(name),expected)
 cfg_path=portable('experiments/m6_prepared/config.json');check(cfg_path,manifest['config_sha256']);cfg=read(cfg_path)
 if cfg!=manifest['configuration'] or cfg['method_config']!=req['method_config'] or cfg['implementation_version']!=VERSION:
  raise ValueError('Frozen configuration differs')
 limits={k:cfg[k] for k in ('query_wall_limit_seconds','query_process_group_rss_limit_bytes','resource_poll_seconds')}
 if req.get('resource_limits')!=limits:raise ValueError('Original resource limits differ')
 if manifest['dependency_fingerprint']!=dependency():raise ValueError('Frozen dependency fingerprint differs')
 q=req['query'];matches=[v for v in manifest['schedule'] if v['query_id']==QUERY]
 if len(manifest['schedule'])!=108 or len(matches)!=1 or matches[0]!=q:raise ValueError('Request query differs from frozen108 schedule')
 if q['n']!=1000000:raise ValueError('Unexpected failure graph size')
 catalog_path=portable(cfg['catalog']);check(catalog_path,cfg['catalog_sha256']);catalog=read(catalog_path)
 if manifest['catalog_sha256']!=cfg['catalog_sha256']:raise ValueError('Catalog identity differs')
 cases=[c for c in catalog['cases'] if c['case_id']==q['case_id']]
 if len(cases)!=1:raise ValueError('Named graph absent from frozen catalog')
 case=cases[0]
 if case['csr_path']!=q['csr_path'] or case['csr_metadata_sha256']!=q['csr_metadata_sha256']:
  raise ValueError('Request graph differs from catalog')
 metadata_path=portable(q['csr_path'])/'csr_metadata.json';check(metadata_path,q['csr_metadata_sha256']);meta=read(metadata_path)
 if set(meta['files'])!={'indptr','indices','weights','degree'} or meta['sha256']!=q['csr_array_sha256'] or manifest['csr_full_hash_verification'][q['case_id']]!=meta['sha256']:
  raise ValueError('CSR input inventory differs')
 for key,name in meta['files'].items():check(portable(str(Path(q['csr_path'])/name)),meta['sha256'][key])
 if q['native_network_sha256']!=meta['source_network_sha256'] or q['native_community_sha256']!=meta['source_community_sha256']:
  raise ValueError('Native input provenance differs')
 # These are provenance-only byte hashes: labels are never JSON decoded.
 for key in ('truth','queries'):
  offline=q['offline_only']
  if case[key+'_path']!=offline[key+'_path'] or case[key+'_sha256']!=offline[key+'_sha256']:raise ValueError('Offline input binding differs')
  check(portable(offline[key+'_path']),offline[key+'_sha256'])
 if sha(Path(__file__))!=helper_sha:raise ValueError('Probe source changed during initial verification')
 return req,manifest,metadata_path,{'verified_file_sha256':checked,'dependency_fingerprint':manifest['dependency_fingerprint'],
            'labels_decoded':False,'truth_role':'Input provenance SHA only; never method input or offline quality evaluation',
            'original_method_config_unchanged':True,'original_resource_limits':limits}


def active_frame(error):
 """Find the frozen Python error frame; no tracing/profiling interception."""
 tb=error.__traceback__;found=None
 while tb is not None:
  frame=tb.tb_frame
  if frame.f_code.co_name=='_active_linear_finish' and Path(frame.f_code.co_filename).resolve()==ROOT/'zrhfd/diffusion.py':
   found=frame
  tb=tb.tb_next
 return found


def capture(frame,directory,np):
 """Recompute residuals via degree diagonal minus captured local adjacency.

    This uses an independent arithmetic expression, not a new sparse solve.
    No full system matrix or dense global scores are serialized.
 """
 loc=frame.f_locals;graph=loc['graph'];U=np.asarray(loc['U'],dtype=np.int64)
 values=np.asarray(loc['values'],dtype=np.float64);clipped=np.asarray(loc['raw'][U],dtype=np.float64)
 degree=np.asarray(graph.degree[U],dtype=np.float64);rhs=np.asarray(loc['rhs'],dtype=np.float64)
 local=loc['local'];sigma=float(loc['sigma'])
 if values.shape!=U.shape or clipped.shape!=U.shape or np.any(degree<=0):raise ValueError('Captured active arrays are invalid')
 unclip_residual=(1+sigma)*degree*values-local.dot(values)-rhs
 clipped_residual=(1+sigma)*degree*clipped-local.dot(clipped)-rhs
 def stats(vector):
  scaled=np.abs(vector)/degree;i=int(np.argmax(scaled)) if len(U) else None
  return {'l2_residual':float(np.linalg.norm(vector)),'relative_rhs_l2_residual':float(np.linalg.norm(vector)/max(1.,np.linalg.norm(rhs))),
          'max_degree_scaled_residual':float(np.max(scaled,initial=0)),
          'node_max_residual':int(U[i]) if i is not None else None,
          'node_signed_residual':float(vector[i]) if i is not None else None}
 indices=np.argsort(np.abs(clipped_residual)/degree)[-10:][::-1]
 report={key:loc.get(key) for key in ('seed','mass','sigma','tolerance','iteration','linear_status','negative','residual','worst')}
 report.update({'exception_frame_file':'zrhfd/diffusion.py','exception_frame_function':'_active_linear_finish','exception_frame_line':frame.f_lineno,
                'Ulen':len(U),'support_volume':float(degree.sum()),'raw_support_entries':len(loc.get('support',[])),
                'frame_minimum_solution':loc.get('negative'),'unclipped_minimum_value':float(np.min(values)) if len(U) else None,
                'negative_unclipped_count':int(np.count_nonzero(values<0)),'CG_info':loc.get('info'),
                'active_set_trace':loc.get('trace',[]),'new_active_vertices':len(loc.get('additions',[])),
                'unclipped_residual':stats(unclip_residual),'clipped_residual':stats(clipped_residual),
                'residual_evaluation':'(1+sigma)*degree[U]*x-local_adjacency@x-rhs; independent evaluation, no solve or tolerance change',
                'top_degree_scaled_clipped_residual_nodes':[{'node':int(U[i]),'degree':float(degree[i]),'unclipped':float(values[i]),
                     'clipped':float(clipped[i]),'residual':float(clipped_residual[i]),'scaled_abs_residual':float(abs(clipped_residual[i])/degree[i])} for i in indices]})
 partial=directory/('.active_values.npz.partial-'+str(uuid.uuid4()))
 with partial.open('xb') as stream:
  np.savez(stream,U=U,unclipped_values=values,clipped_raw_U=clipped)
  stream.flush();os.fsync(stream.fileno())
 target=directory/'active_values.npz';os.link(partial,target);partial.unlink()
 report['arrays']={'path':str(target.relative_to(ROOT)),'sha256':sha(target),'stored_bytes':target.stat().st_size,
                   'uncompressed_array_bytes':int(U.nbytes+values.nbytes+clipped.nbytes),'codec':'numpy.savez ZIP_STORED; no compression',
                   'members':['U','unclipped_values','clipped_raw_U'],'full_system_saved':False,'global_raw_scores_saved':False}
 return report


def worker(request_path,directory):
 started=time.perf_counter();cpu=time.process_time();helper_sha=sha(Path(__file__));timing={};result={'schema_version':1,'scope_role':ROLE,
   'main_cohort_completion_claim':False,'theory_counterexample_claim':False,'final_cover_reported':False,'quality_evaluated':False,
   'probe_source_sha256':helper_sha,'actual_command':[sys.executable,*sys.argv],'started_utc':utc()}
 events=[];workspace=None
 def progress(packet):
  # Persist a small scalar summary only; discard vertex lists/arrays.
  keys=('stage','status','j','mass','j_act','j_star','m_act','objective','runtime_seconds')
  event={k:v for k,v in packet.items() if k in keys and isinstance(v,(str,int,float,bool,type(None)))}
  event['probe_elapsed_seconds']=time.perf_counter()-started
  publish(directory/'progress'/f'{len(events):05d}.json',event);events.append(event)
 try:
  before=time.perf_counter();req,manifest,metadata,provenance=verify_request(request_path,helper_sha)
  timing['full_source_input_verification_wall_seconds']=time.perf_counter()-before;result['provenance']=provenance
  result['original_request_sha256']=sha(request_path);result['original_request_path']=str(request_path.relative_to(ROOT))
  result['query_id']=req['query_id'];result['method_config']=req['method_config']
  sys.path.insert(0,str(ROOT));before=time.perf_counter()
  import numpy as np
  from zrhfd.pipeline import Config,run
  from zrhfd.storage import load_csr
  from zrhfd.experimental_cut_workspace import installed_workspace
  cfg=Config(**{**req['method_config'],'fixed_grid':tuple(req['method_config']['fixed_grid'])})
  if json.loads(json.dumps(asdict(Config())))!=req['method_config']:raise ValueError('Frozen default Config differs')
  timing['numerical_imports_wall_seconds']=time.perf_counter()-before
  before=time.perf_counter();graph=load_csr(metadata,verify_hashes=False)
  timing['input_load_wall_seconds']=time.perf_counter()-before
  progress({'stage':'frozen_pipeline_started','mass':None});before=time.perf_counter()
  try:
   with installed_workspace() as active:
    workspace=active
    output=run(graph,int(req['query']['seed']),cfg,progress=progress)
   timing['pipeline_observed_wall_seconds']=time.perf_counter()-before
   result['status']='METHOD_RETURNED_WITHOUT_EVALUATION';result['exception_reproduced']=False
   # Do not persist output vertices, regional cover, certificate or any quality.
   del output
  except Exception as error:
   timing['pipeline_observed_wall_seconds_not_completion']=time.perf_counter()-before
   result.update(status='FROZEN_PIPELINE_EXCEPTION',exception_reproduced=True,
       exception={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
   print(result['exception']['traceback'],file=sys.stderr,flush=True)
   frame=active_frame(error);result['active_linear_exception_frame_found']=frame is not None
   if frame is not None:
    save_start=time.perf_counter();result['active_linear_failure']=capture(frame,directory,np)
    timing['post_exception_residual_and_NPZ_wall_seconds']=time.perf_counter()-save_start
   frame=None
  if workspace is not None:result['prepared_workspace_summary']=workspace.summary()
  for name,expected in manifest['source_sha256'].items():
   if sha(portable(name))!=expected:raise ValueError('Frozen source changed during probe')
  if sha(Path(__file__))!=helper_sha:raise ValueError('Probe source changed during execution')
 except Exception as error:
  result.update(status='PROBE_FAILED',probe_exception={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
  print(result['probe_exception']['traceback'],file=sys.stderr,flush=True)
 result.update(timing=timing,last_progress_summary=events[-1] if events else None,progress_event_count=len(events),
               probe_worker_observed_wall_seconds=time.perf_counter()-started,probe_worker_cpu_seconds=time.process_time()-cpu,
               stopped_utc=utc(),cold_execution='No original warmup replay; compile/cache/global verification costs retained, no performance claim')
 publish(directory/'probe_result.json',result)
 print(json.dumps({'status':result['status'],'query_id':result.get('query_id'),'scope_role':ROLE}),flush=True)
 return 0 if result['status']!='PROBE_FAILED' else 1


def stop_owned(process):
 if process.poll() is not None:return
 try:os.killpg(process.pid,signal.SIGTERM)
 except ProcessLookupError:return
 try:process.wait(timeout=.5)
 except subprocess.TimeoutExpired:
  try:os.killpg(process.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  process.wait()


def execute(request_path,directory,budget,memory):
 directory.mkdir(parents=True,exist_ok=False)
 helper_sha=sha(Path(__file__));env=dict(os.environ,**{key:'1' for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS')})
 env.update(PYTHONHASHSEED='0',PYTHONDONTWRITEBYTECODE='1',NUMBA_CACHE_DIR=str(directory/'numba_cache'))
 command=[sys.executable,str(Path(__file__).relative_to(ROOT)),'--request',str(request_path.relative_to(ROOT)),
          '--output',str(directory.relative_to(ROOT)),'--worker']
 overrides={k:env[k] for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS','PYTHONHASHSEED','PYTHONDONTWRITEBYTECODE','NUMBA_CACHE_DIR')}
 publish(directory/'execution_request.json',{'schema_version':1,'actual_command':command,'cwd':str(ROOT),'environment_overrides':overrides,
       'probe_source_sha256':helper_sha,'original_request_sha256':sha(request_path),'diagnostic_wall_budget_seconds':budget,
       'diagnostic_group_rss_limit_bytes':memory,'source_unchanged':True,'created_before_worker_start':True,'scope_role':ROLE,
       'main_cohort_completion_claim':False,'original_algorithm_config_overrides':None})
 import psutil
 start=time.perf_counter();peak=0;cause=None;returncode=None;controller_error=None
 with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err,(directory/'resource_samples.jsonl').open('x') as samples:
  try:process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=out,stderr=err,start_new_session=True)
  except OSError as error:
   publish(directory/'terminal.json',{'status':'PROCESS_START_FAILED','exception':repr(error),'main_cohort_completion_claim':False,'scope_role':ROLE});return
  try:
   try:created=psutil.Process(process.pid).create_time()
   except psutil.Error:created=None
   publish(directory/'process_started.json',{'pid':process.pid,'create_time':created,'owned_process_group':process.pid})
   while process.poll() is None:
    rss=0
    try:members=[psutil.Process(process.pid)]+psutil.Process(process.pid).children(recursive=True)
    except psutil.Error:members=[]
    for member in members:
     try:rss+=member.memory_info().rss
     except psutil.Error:pass
    peak=max(peak,rss);elapsed=time.perf_counter()-start
    samples.write(json.dumps({'observed_wall_seconds':elapsed,'sum_live_rss_bytes':rss})+'\n');samples.flush()
    if elapsed>=budget:cause='DIAGNOSTIC_TIMEOUT'
    if rss>memory:cause='DIAGNOSTIC_MEMORY_LIMIT'
    if cause:stop_owned(process);break
    time.sleep(.1)
  except KeyboardInterrupt:cause='DIAGNOSTIC_INTERRUPTED';stop_owned(process)
  except Exception as error:
   cause='DIAGNOSTIC_CONTROLLER_ERROR';controller_error={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()};stop_owned(process)
  except BaseException:stop_owned(process);raise
  returncode=process.wait()
 result_path=directory/'probe_result.json';status=cause or ('DIAGNOSTIC_FINISHED' if returncode==0 and result_path.exists() else 'DIAGNOSTIC_FAILED')
 publish(directory/'terminal.json',{'schema_version':1,'status':status,'exit_code':returncode,'observed_wall_seconds':time.perf_counter()-start,
       'peak_sum_live_rss_bytes':peak,'probe_result_sha256':sha(result_path) if result_path.exists() else None,
       'diagnostic_wall_budget_seconds':budget,'diagnostic_group_rss_limit_bytes':memory,'probe_source_sha256':helper_sha,
       'original_request_sha256':sha(request_path),'main_cohort_completion_claim':False,'scope_role':ROLE,
       'controller_error':controller_error,
       'timeout_is_not_completion':True,'all_partial_files_retained':True,'finished_utc':utc()})
 print(json.dumps({'status':status,'output':str(directory.relative_to(ROOT)),'scope_role':ROLE}))


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--request',default='results/m6_prepared/queries/'+QUERY+'/attempt_000/request.json')
 parser.add_argument('--output',default='reviews/solver_failure_probe/run_v001')
 parser.add_argument('--execute',action='store_true');parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
 parser.add_argument('--budget-seconds',type=float,default=60.);parser.add_argument('--memory-bytes',type=int,default=12000000000)
 args=parser.parse_args()
 if not math.isfinite(args.budget_seconds) or args.budget_seconds<=0 or args.memory_bytes<=0:parser.error('Invalid diagnostic resource limits')
 request=portable(args.request);folder=portable(args.output)
 if not folder.is_relative_to(ROOT/'reviews/solver_failure_probe'):parser.error('Output outside assigned probe scope')
 if args.worker:return worker(request,folder)
 if not args.execute:
  print(json.dumps({'status':'CODE_PREPARED_NOT_EXECUTED','query_id':QUERY,'request':args.request,'output':args.output,
        'budget_seconds':args.budget_seconds,'scope_role':ROLE,'input_files_opened':False,'algorithm_invocations':0}));return 0
 def interrupted(signum,frame):raise KeyboardInterrupt
 signal.signal(signal.SIGTERM,interrupted)
 execute(request,folder,args.budget_seconds,args.memory_bytes)
 return 0


if __name__=='__main__':sys.exit(main())
