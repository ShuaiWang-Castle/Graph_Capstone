"""Incremental immutable M4 offline diagnostics. Default: prepare/inventory only."""
from pathlib import Path
import argparse
import gzip
import json
import math
import os
import platform
import importlib.metadata
import signal
import subprocess
import sys
import time
import psutil
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.diagnostics.storage import sha,stamp,write_json,scoped_output
from experiments.diagnostics.m4_query import POLICY
from experiments.diagnostics.m4_worker import validate_record


def sources():
    names=['experiments/diagnostics/graph_query.py','experiments/diagnostics/m4_query.py','experiments/diagnostics/m4_worker.py','experiments/diagnostics/run_m4.py','experiments/diagnostics/storage.py','zrhfd/__init__.py','zrhfd/graph.py','zrhfd/diffusion.py','provenance/dependency_versions.txt']
    return {name:sha(PROJECT/name) for name in names}


def plan(upstream):
    rows=[];manifests={}
    for run in upstream:
        folder=PROJECT/run;manifest=json.loads((folder/'manifest.json').read_text());manifests[run]=sha(folder/'manifest.json')
        if manifest['phase']!='main':raise ValueError('Only M4 main-phase runs are supported')
        for path in manifest['jobs']:
            if not path.endswith('_main.json'):continue
            job=json.loads((PROJECT/path).read_text())
            if job['method']!='zrhfd' or job['setting']!='no_volume':raise ValueError('Main label must identify no-volume ZR')
            q=job['query'];rows.append({'diagnostic_query_id':folder.name+'__'+job['task'],'task':job['task'],'split':q['split'],'upstream_run':run,'job_path':path,'job_sha256':sha(PROJECT/path),'raw_path':job['result_path'],'case_id':q['case_id'],'seed':q['seed'],'community_index':q['community_index'],'graph_path':q['graph_path'],'graph_sha256':q['graph_sha256'],'truth_path':q['truth_path'],'truth_sha256':q['truth_sha256'],'primary_protocol_sha256':job['protocol_sha256']})
    if len({r['diagnostic_query_id'] for r in rows})!=len(rows):raise ValueError('Duplicate diagnostic query identity')
    return rows,manifests


def inventory(rows):
    entries=[]
    for row in rows:
        file=PROJECT/row['raw_path'];failure=file.with_suffix('.failure.json');status='PENDING_PRIMARY_RESULT';digest=None;reason=None
        if failure.exists():
            try:status='EXCLUDED_UPSTREAM_OUTER_FAILURE';reason=json.loads(failure.read_text()).get('status')
            except Exception as error:status='NOT_ELIGIBLE_OR_RAW_NOT_FINISHED';reason='Malformed outer failure: '+repr(error)
        elif file.exists():
            try:
                record=json.loads(gzip.open(file,'rt').read());job=json.loads((PROJECT/row['job_path']).read_text());validate_record(job,record);status='ELIGIBLE_COMPLETED_MAIN';digest=sha(file)
            except Exception as error:status='NOT_ELIGIBLE_OR_RAW_NOT_FINISHED';reason=repr(error)
        entries.append(dict(row,inventory_status=status,raw_sha256=digest,reason=reason))
    return entries


def freeze(folder,upstream,wall,memory):
    rows,manifests=plan(upstream);frozen={'schema_version':1,'upstream_manifests':manifests,'source_sha256':sources(),'diagnostic_policy':POLICY,'queries':rows,'resources':{'query_wall_seconds':wall,'query_memory_bytes':memory,'cpu_threads':1,'measurement_role':'independent offline diagnostic, never headline method timing'},'selection':'all completed main ZR outputs, dev and test, without recovery/F1/failure filtering','python_version':platform.python_version(),'dependency_versions':{name:importlib.metadata.version(name) for name in ['numpy','scipy','numba','llvmlite','psutil']}}
    path=folder/'manifest.json'
    if path.exists():
        existing=json.loads(path.read_text())
        if existing['frozen']!=frozen:raise RuntimeError('Diagnostic source/input/policy changed; use a new diagnostic run directory')
        return existing
    for relative,digest in frozen['source_sha256'].items():
        file=folder/'sources'/relative;file.parent.mkdir(parents=True,exist_ok=True);content=(PROJECT/relative).read_bytes()
        if sha(PROJECT/relative)!=digest:raise RuntimeError('Source changed while preparing diagnostic freeze')
        if file.exists() and sha(file)!=digest:raise RuntimeError('Diagnostic snapshot changed')
        if not file.exists():
            with file.open('xb') as stream:stream.write(content)
    import hashlib
    manifest={'frozen':frozen,'frozen_sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'created_utc':stamp(),'initial_status':'PREPARED_NOT_EXECUTED','host_metadata':{'platform':platform.platform(),'cpu_count':os.cpu_count()}}
    write_json(path,manifest);return manifest


def stop_group(process):
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=.5)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()


def partial_observations(events):
    rows=[e for e in events if e.get('event')=='support_probe_finished' and 'covered' in e]
    uncovered=[e for e in rows if not e['covered']];covered=[e for e in rows if e['covered']]
    low=max((e['mass'] for e in uncovered),default=None);high=min((e['mass'] for e in covered),default=None);ordered=low is None or high is None or low<high
    return {'status':'NOT_COMPLETED_OFFLINE_COVERAGE','observed_uncovered_mass_lower':low,'observed_covered_mass_upper':high,'relative_observed_width':(high-low)/max(1,high) if low is not None and high is not None and ordered else None,'observations_ordered':ordered,'first_observed_coverage':covered[0] if covered else None,'finished_support_observations':len(rows),'m_c_completion_claim':False,'note':'partial observed bounds retained; they are not a completed m_c estimate or substituted field value'}


def validate_diagnostic_result(result,query_id,raw_sha256):
    if not isinstance(result,dict):raise ValueError('Diagnostic result must be a JSON object')
    if result.get('diagnostic_query_id')!=query_id or result.get('status') not in ['COMPLETED','FAILED','NOT_COMPLETED']:raise ValueError('Wrong diagnostic result identity/status')
    if result.get('source_raw_sha256')!=raw_sha256:raise ValueError('Wrong source raw hash')
    if result['status']=='COMPLETED':
        diagnosis=result.get('diagnosis');mc=diagnosis.get('coverage_mass') if isinstance(diagnosis,dict) else None
        if not isinstance(mc,dict):raise ValueError('Missing completed coverage diagnosis')
        if mc.get('status')=='NUMERIC_COVERAGE_BRACKET':
            if mc.get('relative_tolerance_met') is not True:raise ValueError('Completed numeric bracket lacks requested tolerance')
            for key in ['m_c_lower','m_c_upper','relative_bracket_width']:
                value=mc.get(key)
                if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0:raise ValueError('Invalid completed numeric bracket field: '+key)
            if mc['m_c_lower']>=mc['m_c_upper'] or mc['relative_bracket_width']>POLICY['coverage_relative_tolerance']:raise ValueError('Invalid completed bracket ordering/width')
        elif mc.get('status')!='NO_FINITE_COVERAGE':raise ValueError('Unsupported completed coverage status')
        for key in ['worker_wall_seconds_before_final_serialization','worker_cpu_seconds_before_final_serialization']:
            value=result.get(key)
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0:raise ValueError('Nonfinite diagnostic elapsed time')
    return result


def read_progress(directory):
    events=[];malformed=[]
    for file in sorted((directory/'progress').glob('*.json')):
        try:
            event=json.loads(file.read_text())
            if not isinstance(event,dict) or not isinstance(event.get('event'),str):raise ValueError('Progress record must be an event object')
            if event['event']=='support_probe_finished':
                if not isinstance(event.get('support'),list) or type(event.get('covered')) is not bool:raise ValueError('Finished support lacks vertices/coverage observation')
                for key in ['mass','support_volume','outside_truth_volume']:
                    value=event.get(key)
                    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0:raise ValueError('Invalid finished support field: '+key)
            events.append(event)
        except Exception as error:malformed.append({'path':str(file.relative_to(directory)),'error':repr(error)})
    return events,malformed


def recover_abandoned(attempt,query_id):
    started=attempt/'process_started.json'
    if started.exists():
        pid=json.loads(started.read_text())['pid']
        try:
            command=psutil.Process(pid).cmdline()
            if 'experiments/diagnostics/m4_worker.py' in command:raise RuntimeError('Prior diagnostic worker remains alive; stop it before serial resume')
        except psutil.NoSuchProcess:pass
    events,malformed=read_progress(attempt);request=attempt/'request.json';request=json.loads(request.read_text()) if request.exists() else {}
    receipt={'schema_version':1,'diagnostic_query_id':query_id,'status':'ABANDONED_PREVIOUS_DIAGNOSTIC','completed_m_c_claim':False,'reason':'incomplete attempt found on resume; all raw/checkpoint files retained; no completion-time claim','source_raw_sha256':request.get('raw_sha256'),'finished_support_observations':sum(e['event']=='support_probe_finished' for e in events),'partial_coverage':partial_observations(events),'progress_parse_errors':malformed,'unpublished_partial_files':[p.name for p in (attempt/'progress').glob('.*.partial-*')]}
    write_json(attempt/'receipt.json',receipt)
    return receipt


def execute_one(directory,row,manifest,run_folder):
    directory.mkdir(parents=True,exist_ok=False);resources=manifest['frozen']['resources']
    request={'query':{k:v for k,v in row.items() if k not in ['inventory_status','reason','raw_sha256']},'raw_sha256':row['raw_sha256'],'cache_directory':str((run_folder/'support_cache').relative_to(PROJECT)),'manifest_path':str((run_folder/'manifest.json').relative_to(PROJECT)),'manifest_sha256':sha(run_folder/'manifest.json'),'source_sha256':manifest['frozen']['source_sha256'],'dependency_versions':manifest['frozen']['dependency_versions'],'diagnostic_policy':POLICY}
    write_json(directory/'request.json',request)
    overrides={key:'1' for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS']};overrides['PYTHONHASHSEED']='0';env=dict(os.environ,**overrides)
    command=[sys.executable,'experiments/diagnostics/m4_worker.py','--request',str((directory/'request.json').resolve())]
    write_json(directory/'execution_request.json',{'actual_command':command,'cwd':str(PROJECT),'thread_environment':overrides,'manifest_sha256':request['manifest_sha256'],'frozen_sha256':manifest['frozen_sha256'],'source_sha256':request['source_sha256'],'created_before_process_start':True,'measurement_role':'offline diagnostic only'})
    started=time.perf_counter();peak=0;last_cpu=0.;reason=None;returncode=None
    with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err,(directory/'resource_samples.jsonl').open('x') as sampling:
        try:process=subprocess.Popen(command,cwd=PROJECT,env=env,stdout=out,stderr=err,start_new_session=True)
        except OSError as error:
            receipt={'schema_version':1,'diagnostic_query_id':row['diagnostic_query_id'],'status':'FAILED','failure_reason':'PROCESS_START_FAILED','exception':repr(error),'exit_code':None,'source_raw':row['raw_path'],'source_raw_sha256':row['raw_sha256'],'completed_m_c_claim':False,'measurement_role':'offline diagnostic only'}
            write_json(directory/'receipt.json',receipt);return receipt
        write_json(directory/'process_started.json',{'pid':process.pid,'process_group':process.pid,'started_utc':stamp()})
        try:
            while process.poll() is None:
                rss=0;observed_cpu=0.;pids=[]
                try:members=[psutil.Process(process.pid)]+psutil.Process(process.pid).children(recursive=True)
                except psutil.NoSuchProcess:members=[]
                for member in members:
                    try:
                        rss+=member.memory_info().rss;c=member.cpu_times();observed_cpu+=c.user+c.system;pids.append(member.pid)
                    except psutil.Error:pass
                peak=max(peak,rss);last_cpu=max(last_cpu,observed_cpu);elapsed=time.perf_counter()-started
                sampling.write(json.dumps({'elapsed_wall_seconds':elapsed,'sum_rss_bytes':rss,'sum_live_process_cpu_seconds':observed_cpu,'live_pids':pids})+'\n');sampling.flush()
                if elapsed>=resources['query_wall_seconds']:reason='TIMEOUT'
                if rss>resources['query_memory_bytes']:reason='MEMORY_LIMIT'
                if reason:stop_group(process);break
                time.sleep(.1)
        except KeyboardInterrupt:reason='INTERRUPTED';stop_group(process)
        except BaseException:stop_group(process);raise
        returncode=process.wait()
    result=None;failure=None;path=directory/'result.json'
    if path.exists():
        try:
            result=json.loads(path.read_text());validate_diagnostic_result(result,row['diagnostic_query_id'],row['raw_sha256'])
        except Exception as error:failure='INVALID_DIAGNOSTIC_RESULT: '+repr(error)
    else:failure='DIAGNOSTIC_RESULT_MISSING'
    if not reason and returncode!=0:failure='NONZERO_DIAGNOSTIC_EXIT'
    status=reason or ('FAILED' if failure else result['status']);events,malformed=read_progress(directory)
    if malformed and status=='COMPLETED':status='FAILED';failure='MALFORMED_PROGRESS'
    supports=[e for e in events if e.get('event')=='support_probe_finished'];raw_result_sha=sha(path) if path.exists() else None
    receipt={'schema_version':1,'diagnostic_query_id':row['diagnostic_query_id'],'status':status,'worker_status':result.get('status') if isinstance(result,dict) else None,'failure_reason':failure,'exit_code':returncode,'observed_wall_seconds':time.perf_counter()-started,'last_sampled_cpu_seconds_not_completion':last_cpu,'peak_sum_rss_bytes':peak,'result_sha256':raw_result_sha,'static_diagnosis_present':(directory/'static_diagnosis.json').exists(),'finished_support_observations':len(supports),'last_finished_support_observation':supports[-1] if supports else None,'partial_coverage':partial_observations(events) if status!='COMPLETED' else None,'progress_parse_errors':malformed,'unpublished_partial_files':[p.name for p in (directory/'progress').glob('.*.partial-*')],'resources':resources,'source_raw':row['raw_path'],'source_raw_sha256':row['raw_sha256'],'finished_utc':stamp(),'measurement_role':'independent offline diagnostic only; no headline method timing','completed_m_c_claim':bool(status=='COMPLETED' and result['diagnosis']['coverage_mass'].get('status')=='NUMERIC_COVERAGE_BRACKET'),'coverage_analysis_completed':status=='COMPLETED'}
    write_json(directory/'receipt.json',receipt)
    if reason=='INTERRUPTED':raise KeyboardInterrupt
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runs',nargs='+',default=['results/m4/dev_main_v12_002','results/m4/test_main_v12_002']);parser.add_argument('--output',default='results/diagnostics/m4_main_v12_001');parser.add_argument('--execute',action='store_true');parser.add_argument('--limit',type=int);parser.add_argument('--retry-incomplete',action='store_true');parser.add_argument('--query-wall-seconds',type=float,default=600.);parser.add_argument('--memory-bytes',type=int,default=12000000000);args=parser.parse_args()
    if args.limit is not None and args.limit<0 or not math.isfinite(args.query_wall_seconds) or args.query_wall_seconds<=0 or args.memory_bytes<=0:raise ValueError('Invalid diagnostic budget/limit')
    folder=scoped_output(args.output);folder.mkdir(parents=True,exist_ok=True);manifest=freeze(folder,args.runs,args.query_wall_seconds,args.memory_bytes)
    rows=inventory(manifest['frozen']['queries']);counts={s:sum(r['inventory_status']==s for r in rows) for s in sorted({r['inventory_status'] for r in rows})}
    inspections=folder/'inventories';number=len(list(inspections.glob('*.json')));write_json(inspections/f'{number:06d}.json',{'created_utc':stamp(),'manifest_sha256':sha(folder/'manifest.json'),'counts':counts,'queries':rows,'execution_requested':args.execute,'quality_filtered':False})
    print(json.dumps({'frozen_sha256':manifest['frozen_sha256'],'planned_queries':len(rows),'inventory':counts,'execute':args.execute}),flush=True)
    if not args.execute:return
    def interrupt(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt);lock=folder/'serial.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        pid=int(lock.read_text())
        if psutil.pid_exists(pid):raise RuntimeError('Another diagnostic controller holds this serial run')
        lock.unlink();fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.write(fd,str(os.getpid()).encode());os.close(fd);attempted=0
    try:
        for row in rows:
            if row['inventory_status']!='ELIGIBLE_COMPLETED_MAIN':continue
            root=folder/'queries'/row['diagnostic_query_id'];attempts=sorted(root.glob('attempt_*'))
            for attempt in attempts:
                if not (attempt/'receipt.json').exists():recover_abandoned(attempt,row['diagnostic_query_id'])
            finished=[json.loads((p/'receipt.json').read_text()) for p in attempts]
            if finished and (finished[-1]['status']=='COMPLETED' or finished[-1]['status'] not in ['ABANDONED_PREVIOUS_DIAGNOSTIC','INTERRUPTED'] and not args.retry_incomplete):continue
            if args.limit is not None and attempted>=args.limit:break
            receipt=execute_one(root/f'attempt_{len(attempts):03d}',row,manifest,folder);attempted+=1
            print(row['task'],receipt['status'],flush=True)
    finally:lock.unlink(missing_ok=True)


if __name__=='__main__':main()
