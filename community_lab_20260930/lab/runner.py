from __future__ import annotations
import json,os,signal,subprocess,time,sys,threading
from pathlib import Path
import psutil
from lab.io import write_json,read_json,sha256,graph,cover

def stop_tree(p):
    if p.poll() is not None:return
    try:
        if os.name=='posix':os.killpg(p.pid,signal.SIGTERM)
        else:p.terminate()
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name=='posix':os.killpg(p.pid,signal.SIGKILL)
            else:p.kill()
    except ProcessLookupError:pass
    p.wait()

def run_job(job,root,run_root,remaining_seconds=None):
    root=Path(root).resolve();directory=Path(run_root)/job['job_id'];directory.mkdir(parents=True,exist_ok=True)
    signature=json.dumps(job,sort_keys=True)
    specfile=directory/'spec.json';resultfile=directory/'result.json'
    if specfile.exists() and read_json(specfile)!=job:raise ValueError('Job ID reused with different spec; use a new ID')
    if resultfile.exists():
        cached=read_json(resultfile)
        for field,key in [('graph','graph_sha256'),('config','config_sha256')]:
            if cached.get(key) and sha256(job[field])!=cached[key]:
                raise ValueError(f'{field} no longer matches the recorded run; preserve the old record and restore its input')
        if cached.get('prediction') and cached.get('prediction_sha256'):
            if sha256(cached['prediction'])!=cached['prediction_sha256']:
                raise ValueError('Recorded prediction changed; do not silently reuse it')
        return cached
    write_json(specfile,job)
    if job.get('blocked_reason'):
        r={'job_id':job['job_id'],'method':job['method'],'status':'BLOCKED','reason':job['blocked_reason'],'pipeline_seconds':0.0}
        write_json(resultfile,r);return r
    limit=min(float(job['timeout_s']),remaining_seconds) if remaining_seconds is not None else float(job['timeout_s'])
    if limit<=1:
        r={'job_id':job['job_id'],'method':job['method'],'status':'NOT_RUN_BUDGET','pipeline_seconds':0.0};write_json(resultfile,r);return r
    output=directory/'prediction.json';checkpoint=directory/'checkpoint.json'
    # Existing output without result can be a killed attempt. Preserve it, never score it as this attempt.
    for f in [output,checkpoint]:
        if f.exists():raise RuntimeError(f'Incomplete prior attempt at {directory}; archive it and resume under a new job ID')
    placeholders={'python':sys.executable,'root':str(root),'graph':str(Path(job['graph']).resolve()),
                  'output':str(output.resolve()),'checkpoint':str(checkpoint.resolve()),'seed':str(job['seed']),
                  'config':str(Path(job['config']).resolve()),'run_dir':str(directory.resolve())}
    argv=[s.format(**placeholders) for s in job['command']]
    for field,key in [('graph','graph_sha256'),('config','config_sha256')]:
        if key in job and sha256(job[field])!=job[key]:raise ValueError(f'{field} changed after job-plan freeze')
    for file,digest in job.get('source_hashes',{}).items():
        if sha256(file)!=digest:raise ValueError('Adapter code changed after freeze: '+file)
    env=os.environ.copy();nt=str(job.get('threads',1))
    env.update(OMP_NUM_THREADS=nt,OPENBLAS_NUM_THREADS=nt,MKL_NUM_THREADS=nt,NUMEXPR_NUM_THREADS=nt,
               VECLIB_MAXIMUM_THREADS=nt,BLIS_NUM_THREADS=nt,
               PYTHONHASHSEED=str(job['seed']),LAB_ROOT=str(root),LAB_CHECKPOINT=str(checkpoint.resolve()),
               LAB_BUDGET_SECONDS=str(limit),LAB_CONFIG=placeholders['config'])
    env['PYTHONPATH']=str(root)+os.pathsep+env.get('PYTHONPATH','')
    if job.get('gpu') is not None:env['CUDA_VISIBLE_DEVICES']=str(job['gpu'])
    elif job.get('device','cpu')=='cpu':env['CUDA_VISIBLE_DEVICES']=''
    rec={'job_id':job['job_id'],'case_id':job.get('case_id'),'method':job['method'],
         'information_policy':job.get('information_policy'),'device':job.get('device','cpu'),
         'threads':job.get('threads',1),'seed':job['seed'],'command':argv,
         'python_executable':sys.executable,'source_hashes':job.get('source_hashes',{}),
         'declared_implementation':job.get('declared_implementation'),
         'thread_environment':{k:env[k] for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS']},
         'graph_sha256':sha256(job['graph']),'config_sha256':sha256(job['config']),
         'budget_seconds':limit,'original_timeout_s':job['timeout_s'],
         'resource_measurement':'0.2s sampled sum of process-tree RSS; shared pages may be counted more than once; GPU memory needs adapter/external telemetry.'}
    start=time.perf_counter();p=None;peak=0;cpupeak=0;status=None
    exited=threading.Event();exit_observation={};waiter=None
    def observe_exit():
        # Blocking wait avoids the monitoring interval quantizing short jobs.
        try:exit_observation['returncode']=p.wait()
        except Exception as e:exit_observation['wait_error']=str(e)
        finally:
            exit_observation['elapsed_seconds']=time.perf_counter()-start
            exited.set()
    try:
        with open(directory/'stdout.log','w',encoding='utf-8') as out,open(directory/'stderr.log','w',encoding='utf-8') as err:
            p=subprocess.Popen(argv,cwd=root,env=env,stdout=out,stderr=err,start_new_session=(os.name=='posix'))
            waiter=threading.Thread(target=observe_exit,name='lab-process-waiter',daemon=True)
            waiter.start()
            try:ps=psutil.Process(p.pid)
            except psutil.NoSuchProcess:ps=None  # A fast job may already have exited.
            while not exited.is_set():
                try:
                    procs=([ps]+ps.children(recursive=True)) if ps is not None else []
                    rss=0;cpu=0
                    for c in procs:
                        try:rss+=c.memory_info().rss;t=c.cpu_times();cpu+=t.user+t.system
                        except(psutil.NoSuchProcess,psutil.AccessDenied):pass
                    peak=max(peak,rss);cpupeak=max(cpupeak,cpu)
                except(psutil.NoSuchProcess,psutil.AccessDenied):pass
                if exited.is_set():break
                if time.perf_counter()-start>limit:status='TIMEOUT';stop_tree(p);break
                if peak>job.get('memory_mb',8192)*1024**2:status='MEMORY_LIMIT';stop_tree(p);break
                if sum(f.stat().st_size for f in [directory/'stdout.log',directory/'stderr.log'])>50*1024**2:
                    status='LOG_LIMIT';stop_tree(p);break
                exited.wait(min(.2,max(0,limit-(time.perf_counter()-start))))
            if waiter is not None:waiter.join()
            if exit_observation.get('wait_error'):
                raise RuntimeError('Process waiter failed: '+exit_observation['wait_error'])
            if status is None:status='COMPLETED' if p.returncode==0 else 'ERROR'
            rec['returncode']=p.returncode
    except KeyboardInterrupt:
        status='INTERRUPTED'
        if p is not None:stop_tree(p)
    except Exception as e:
        status='LAUNCH_ERROR';rec['error']=str(e)
        if p is not None:stop_tree(p)
    finally:
        if waiter is not None:waiter.join()
    monitor_elapsed=time.perf_counter()-start
    rec.update(status=status,pipeline_seconds=exit_observation.get('elapsed_seconds',monitor_elapsed),
               monitor_elapsed_seconds=monitor_elapsed,
               timing_definition='Elapsed from before process launch to blocking p.wait return, observed by a dedicated wait thread; monitor completion separately recorded; resource samples remain approximately 0.2s.',
               peak_tree_rss_bytes=peak,sampled_tree_cpu_seconds=cpupeak)
    target=output if status=='COMPLETED' and output.exists() else checkpoint if checkpoint.exists() else None
    if target:
        try:
            n,_=graph(job['graph']);_,audit=cover(target,n)
            rec.update(prediction=str(target.resolve()),prediction_sha256=sha256(target),cover_validation=audit,
                       prediction_kind='completed' if target==output else 'partial_checkpoint')
        except Exception as e:
            rec['prediction_error']=str(e);rec['prediction_kind']='invalid'
            if status=='COMPLETED':rec['status']='INVALID_OUTPUT'
    elif status=='COMPLETED':rec['status']='INVALID_OUTPUT'
    write_json(resultfile,rec);return rec
