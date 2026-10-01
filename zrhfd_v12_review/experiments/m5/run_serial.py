"""Immutable serial M5 execution; defaults to preparation, never implicit run."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
import importlib.metadata
import math
import psutil
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.m5.inputs import CONFIG,config,digest,immutable_json,validate_official,generate_hsbm,tasks


def source_pins(backend):
    paths=sorted([str(p.relative_to(PROJECT)) for directory in ['zrhfd/hyper','experiments/m5'] for p in (PROJECT/directory).glob('*.py')])
    paths+=['zrhfd/__init__.py','zrhfd/graph.py','zrhfd/mincut.py','zrhfd/mincut128.cpp','work/bin/mincut128','zrhfd/baselines/hypergraph.py','zrhfd/baselines/hfd.py','zrhfd/baselines/acl.py','zrhfd/baselines/tlhfd.py','zrhfd/baselines/_native.py','zrhfd/baselines/_common.py','zrhfd/baselines/_execution.py','zrhfd/baselines/native_driver.jl','external/runtime/julia-1.10.10/bin/julia','external/runtime/hfd-environment/Project.toml','external/runtime/hfd-environment/Manifest.toml','provenance/environment.json','provenance/baselines/acquisition.json']
    acquisition=json.loads((PROJECT/'provenance/baselines/acquisition.json').read_text())
    for repository,files in [('hfd',['ucHFD.jl','utils.jl','struct.jl']),('localgraphclustering',['localgraphclustering/algorithms/acl_list.py'])]:
        record=acquisition['repositories'][repository]
        for filename in files:
            relative=record['path']+'/'+filename
            if digest(relative)!=record['tracked_worktree_file_sha256'][filename]:raise RuntimeError('Frozen original author source changed: '+relative)
            paths.append(relative)
    if backend=='numba':paths.append('zrhfd/baselines/hyper_tlhfd_numba.py')
    return {path:digest(path) for path in sorted(set(paths))}


def freeze(run_directory,selected,backend,toy):
    c=config();configuration_sha=digest(CONFIG)
    manifest_path=run_directory/'manifest.json'
    dependencies={name:importlib.metadata.version(name) for name in ['numpy','scipy','networkx','cvxpy','clarabel','psutil']}
    if backend=='numba':
        dependencies['numba']=importlib.metadata.version('numba');dependencies['llvmlite']=importlib.metadata.version('llvmlite')
    expected={'schema_version':1,'configuration':c,'configuration_file':CONFIG,'configuration_sha256':configuration_sha,'source_pins':source_pins(backend),'dependency_versions':dependencies,'python_version':platform.python_version(),'tl_backend':backend,'tasks':selected,'toy':toy,'formal_measurement':not toy,'threads':1,'serial_execution':True}
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest['frozen']!=expected:raise RuntimeError('Existing run manifest differs; use a new run directory instead of switching protocol/backend/source')
        return manifest
    for relative,sha in expected['source_pins'].items():
        path=run_directory/'sources'/relative;path.parent.mkdir(parents=True,exist_ok=True)
        content=(PROJECT/relative).read_bytes()
        if hashlib.sha256(content).hexdigest()!=sha:raise RuntimeError('Source changed during freeze: '+relative)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise RuntimeError('Source snapshot changed')
        else:
            with path.open('xb') as stream:stream.write(content)
    manifest={'frozen':expected,'frozen_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'created_utc':datetime.now(timezone.utc).isoformat(),'host_metadata':{'python':platform.python_version(),'platform':platform.platform(),'cpu_count':os.cpu_count(),'dependencies':dependencies},'initial_status':'PREPARED_FROZEN_RUN','execution_status_source':'immutable per-query receipts, not this creation manifest','source_snapshot_directory':'sources'}
    immutable_json(manifest_path,manifest);return manifest


def kill_group(process):
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=.5)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()


def run_one(directory,task,c,backend,manifest_context=None,worker_script='experiments/m5/worker.py'):
    # Each attempt's request, raw logs, progress, result and samples are permanent.
    directory.mkdir(parents=True,exist_ok=False)
    immutable_json(directory/'request.json',{'task':task,'configuration':c,'tl_backend':backend})
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1',JULIA_NUM_THREADS='1')
    if worker_script!='experiments/m5/worker.py' and (not task['toy'] or not worker_script.startswith('tests/hyper_core/')):
        raise ValueError('Alternative worker scripts are restricted to nonformal engineering fixtures')
    command=[sys.executable,worker_script,'--request',str((directory/'request.json').resolve())]
    immutable_json(directory/'execution_request.json',{'actual_command':command,'working_directory':str(PROJECT),'thread_environment_overrides':{key:env[key] for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','JULIA_NUM_THREADS']},'source_context':manifest_context or {'context':'isolated engineering fixture, not formal manifest'},'configuration_sha256':hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'created_before_process_start':True})
    start=time.perf_counter();peak=0;reason=None;samples=[];limit=c['budgets']['memory_bytes'];wall=c['budgets']['wall_seconds_per_method_query']
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr,(directory/'resource_samples.jsonl').open('x') as resource_log:
        try:process=subprocess.Popen(command,cwd=PROJECT,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        except OSError as error:
            receipt={'schema_version':1,'task_id':task['task_id'],'status':'FAILED','failure_reason':'PROCESS_START_FAILED','exception':repr(error),'exit_code':None,'wall_seconds':time.perf_counter()-start,'formal_measurement':not task['toy']}
            immutable_json(directory/'receipt.json',receipt);return receipt
        immutable_json(directory/'process_started.json',{'worker_pid':process.pid,'process_group':process.pid,'started_utc':datetime.now(timezone.utc).isoformat()})
        try:
            while process.poll() is None:
                elapsed=time.perf_counter()-start; rss=0;pids=[]
                try:members=[psutil.Process(process.pid)]+psutil.Process(process.pid).children(recursive=True)
                except psutil.NoSuchProcess:members=[]
                for member in members:
                    try:rss+=member.memory_info().rss;pids.append(member.pid)
                    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                peak=max(peak,rss);sample={'elapsed_seconds':elapsed,'rss_bytes_sum':rss,'live_pids':pids};samples.append(sample);resource_log.write(json.dumps(sample)+'\n');resource_log.flush()
                if rss>limit:reason='MEMORY_LIMIT';kill_group(process);break
                if elapsed>=wall:reason='TIMEOUT';kill_group(process);break
                time.sleep(.1)
        except KeyboardInterrupt:
            reason='INTERRUPTED';kill_group(process)
        except BaseException:
            kill_group(process);raise
        exitcode=process.wait()
    result_path=directory/'worker_result.json';worker=None;failure=None
    try:
        if result_path.exists():
            worker=json.loads(result_path.read_text())
            if not isinstance(worker,dict) or worker.get('task',{}).get('task_id')!=task['task_id'] or worker.get('status') not in ['COMPLETED','FAILED','PARTIAL_TIMEOUT','PARTIAL_UPDATE_BUDGET']:raise ValueError('Invalid worker result schema/task/status')
            if worker['status']=='COMPLETED':
                vertices=worker['output']['vertices'];quality=worker['offline_metrics']['F1']
                if not isinstance(vertices,list) or any(type(v)!=int for v in vertices) or len(vertices)!=len(set(vertices)) or not isinstance(quality,(float,int)) or not 0<=quality<=1:raise ValueError('Invalid completed result output')
                for value in [worker['output']['runtime_seconds'],worker['worker_wall_seconds'],worker['input_load_seconds']]:
                    if not isinstance(value,(float,int)) or not math.isfinite(value) or value<0:raise ValueError('Invalid completed timing value')
                if task['method'] in ['zr_hfd','zh_prov']:
                    for value in [worker['output']['certificate']['LB_R'],worker['output']['certificate']['gap']]:
                        if not isinstance(value,(float,int)) or not math.isfinite(value):raise ValueError('Invalid completed numeric certificate')
        else:failure='WORKER_RESULT_MISSING'
    except Exception as error:failure='WORKER_RESULT_INVALID: '+repr(error)
    if not reason and exitcode!=0:failure='NONZERO_EXIT_CODE'
    status=reason or ('FAILED' if failure else worker['status'])
    progress_paths=sorted((directory/'progress').glob('*.json'));last_partial=None;progress_errors=[]
    for path in progress_paths:
        try:
            item=json.loads(path.read_text())
            if item['event']=='baseline_progress':last_partial={'path':str(path.relative_to(directory)),'payload':item['payload']}
        except Exception as error:progress_errors.append({'path':str(path.relative_to(directory)),'parse_error':repr(error)})
    if progress_errors and status=='COMPLETED':status='FAILED';failure='MALFORMED_PROGRESS_ARTIFACT'
    receipt={'schema_version':1,'task_id':task['task_id'],'status':status,'failure_reason':failure,'worker_status':worker.get('status') if isinstance(worker,dict) else None,'exit_code':exitcode,'wall_seconds':time.perf_counter()-start,'peak_sum_rss_bytes':peak,'wall_budget_seconds':wall,'memory_budget_bytes':limit,'resource_samples':len(samples),'partial_progress_events':len(progress_paths),'progress_parse_errors':progress_errors,'unpublished_partial_files':[p.name for p in (directory/'progress').glob('.*.partial-*')],'last_truth_free_baseline_checkpoint':last_partial,'worker_result_sha256':hashlib.sha256(result_path.read_bytes()).hexdigest() if result_path.exists() else None,'raw_files':['stdout.log','stderr.log','resource_samples.jsonl','request.json','execution_request.json','process_started.json']+(['worker_result.json'] if result_path.exists() else []),'formal_measurement':not task['toy'],'includes_topology_loading':True,'watchdog_definition':'single serial worker and descendants; wall and conservative summed RSS sampled every .1s; budget overshoot at most one sample plus termination latency; all partial artifacts kept'}
    immutable_json(directory/'receipt.json',receipt)
    if reason=='INTERRUPTED':raise KeyboardInterrupt
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',default='results/m5/official_v12_001');parser.add_argument('--execute',action='store_true');parser.add_argument('--toy',action='store_true');parser.add_argument('--datasets',nargs='+');parser.add_argument('--methods',nargs='+');parser.add_argument('--tl-backend',choices=['pure_python','numba'],default='numba');parser.add_argument('--max-jobs',type=int);parser.add_argument('--retry-failed',action='store_true');args=parser.parse_args()
    directory=PROJECT/args.run
    if not directory.resolve().is_relative_to((PROJECT/'results/m5').resolve()):raise ValueError('Run output must stay in assigned results/m5 directory')
    directory.mkdir(parents=True,exist_ok=True)
    if not args.toy:
        validation=validate_official();immutable_json(directory/'input_validation.json',validation);generate_hsbm()
    selected=tasks(args.datasets,args.methods,args.toy);manifest=freeze(directory,selected,args.tl_backend,args.toy)
    print(json.dumps({'run':args.run,'tasks':len(selected),'frozen_sha256':manifest['frozen_sha256'],'execute':args.execute,'toy':args.toy}),flush=True)
    if not args.execute:return
    def stop_handler(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop_handler)
    lock=directory/'serial.lock'
    try:fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        owner=int(lock.read_text())
        if psutil.pid_exists(owner):raise RuntimeError('Another serial runner holds this run')
        lock.unlink();fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    os.write(fd,str(os.getpid()).encode());os.close(fd);completed=0
    try:
        for task in selected:
            taskdir=directory/'queries'/task['task_id'];attempts=sorted(taskdir.glob('attempt_*')) if taskdir.exists() else []
            previous=[json.loads((p/'receipt.json').read_text()) for p in attempts if (p/'receipt.json').exists()]
            if previous and (previous[-1]['status']=='COMPLETED' or not args.retry_failed):continue
            if args.max_jobs is not None and completed>=args.max_jobs:break
            for p in attempts:
                if not (p/'receipt.json').exists():
                    immutable_json(p/'receipt.json',{'schema_version':1,'task_id':task['task_id'],'status':'ABANDONED_PREVIOUS_RUN','reason':'incomplete attempt discovered on resume; raw files preserved; timing unknown','formal_measurement':not task['toy']})
            attempt=taskdir/f'attempt_{len(attempts):03d}'
            context={'manifest_path':str((directory/'manifest.json').relative_to(PROJECT)),'manifest_file_sha256':digest(str((directory/'manifest.json').relative_to(PROJECT))),'frozen_sha256':manifest['frozen_sha256'],'source_pins':manifest['frozen']['source_pins'],'dependency_versions':manifest['frozen']['dependency_versions']}
            receipt=run_one(attempt,task,manifest['frozen']['configuration'],args.tl_backend,context);completed+=1
            print(task['task_id'],receipt['status'],flush=True)
    finally:lock.unlink(missing_ok=True)


if __name__=='__main__':main()
