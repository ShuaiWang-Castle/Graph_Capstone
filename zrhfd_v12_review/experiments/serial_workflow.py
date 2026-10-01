"""Durable orchestration of already-frozen CPU measurement cohorts.

No algorithm choices depend on outputs. Stage failures stop orchestration;
within-stage failures/timeouts remain the frozen runner's immutable results.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,signal,subprocess,sys,time
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atomic(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(temporary,path)

def stages():
    py=str(ROOT/'.venv/bin/python')
    return [
      ('m6_prepared',[py,'experiments/run_m6_compressed.py','--run']),
      ('m4_dev',[py,'experiments/schedule.py','--phase','main','--split','dev','--output','results/m4/dev_main_v12_002']),
      ('m4_test',[py,'experiments/schedule.py','--phase','main','--split','test','--output','results/m4/test_main_v12_002']),
      ('m4_ablations',[py,'experiments/schedule.py','--phase','ablations','--split','dev','--output','results/m4/dev_ablations_v12_002']),
      ('m5_storage_smoke',[py,'experiments/run_m5_archived.py','--run','results/m5/toy_archived_v12_004','--toy','--tl-backend','numba','--execute']),
      ('m5_official',[py,'experiments/run_m5_archived.py','--run','results/m5/official_v12_001','--tl-backend','numba','--execute']),
    ]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wait-for-pid',type=int);ap.add_argument('--execute',action='store_true');ap.add_argument('--state',default='results/serial_workflow_v001');args=ap.parse_args()
    plan=stages();directory=ROOT/args.state;directory.mkdir(parents=True,exist_ok=True)
    if not args.execute:
        print(json.dumps({'prepared_only':True,'stages':[{'name':n,'argv':c} for n,c in plan]},indent=2));return
    request=directory/'LAUNCH.json'
    if not request.exists():
        wait=None
        if args.wait_for_pid:
            owned=psutil.Process(args.wait_for_pid)
            if Path(owned.cwd()).resolve()!=ROOT or 'experiments/m6_prepared/run.py' not in owned.cmdline() or '--run' not in owned.cmdline():
                raise RuntimeError('Wait target must be the owned frozen M6 controller')
            wait={'pid':owned.pid,'created':owned.create_time(),'argv':owned.cmdline(),'cwd':owned.cwd()}
        value={'started_utc':utc(),'actual_argv':sys.argv,'workflow_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'serial_measurement':True,'wait_target':wait,'stages':[{'name':n,'argv':c} for n,c in plan]}
        with request.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    launch=json.loads(request.read_text())
    if launch['workflow_source_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise RuntimeError('Workflow source changed; new execution directory required')
    lock=directory/'runner.lock'
    if lock.exists() and psutil.pid_exists(int(lock.read_text())):raise RuntimeError('Workflow already running')
    lock.write_text(str(os.getpid()));process=None;current_command=None
    def stopping(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stopping)
    state={'status':'ACTIVE','updated_utc':utc(),'controller_pid':os.getpid(),'current_stage':'wait_existing_M6','child_pid':None}
    try:
        waiting=launch.get('wait_target')
        while waiting and psutil.pid_exists(waiting['pid']):
            p=psutil.Process(waiting['pid'])
            if p.create_time()!=waiting['created']:break
            state['updated_utc']=utc();atomic(directory/'STATE.json',state);time.sleep(1)
        for name,command in plan:
            current_command=command;stage=directory/name;stage.mkdir(exist_ok=True)
            attempts=sorted(stage.glob('attempt_*'))
            if attempts and (attempts[-1]/'receipt.json').exists() and json.loads((attempts[-1]/'receipt.json').read_text())['status']=='COMPLETED':continue
            attempt=stage/f'attempt_{len(attempts):03d}';attempt.mkdir()
            began=time.perf_counter();record={'stage':name,'status':'STARTED','started_utc':utc(),'actual_argv':command,'cwd':str(ROOT)}
            atomic(attempt/'receipt.json',record)
            with (attempt/'stdout.log').open('x') as out,(attempt/'stderr.log').open('x') as err:
                process=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err,start_new_session=True)
                state.update(current_stage=name,child_pid=process.pid,current_command=command,stage_receipt=str(attempt.relative_to(ROOT)/'receipt.json'))
                while process.poll() is None:
                    state['updated_utc']=utc();atomic(directory/'STATE.json',state);time.sleep(1)
                code=process.returncode
            if code==0 and name=='m5_storage_smoke':
                from experiments.archival import read_bytes,read_json,verify_archive
                toy=ROOT/'results/m5/toy_archived_v12_004';manifest=json.loads((toy/'manifest.json').read_text())
                receipts=[]
                for task in manifest['frozen']['tasks']:
                    attempt_dir=toy/'queries'/task['task_id']/'attempt_000'
                    terminal=read_json(attempt_dir/'receipt.json')
                    if terminal['status']!='COMPLETED':raise RuntimeError('Storage-integrated smoke failed: '+task['task_id'])
                    raw=read_bytes(attempt_dir/'worker_result.json')
                    if hashlib.sha256(raw).hexdigest()!=terminal['worker_result_sha256']:raise RuntimeError('Storage smoke result bytes differ')
                    archive=json.loads((attempt_dir/'ARCHIVE.json').read_text());verify_archive(attempt_dir,archive)
                    receipts.append({'task':task['task_id'],'status':'PASS','archive_sha256':archive['archive_sha256']})
                if len(receipts)!=8:raise RuntimeError('Eight storage-integrated toy methods required')
                atomic(stage/'acceptance.json',{'status':'PASS','checks':receipts,'formal_quality_result':False})
            record.update(status='COMPLETED' if code==0 else 'CONTROLLER_ERROR',returncode=code,finished_utc=utc(),
                controller_wall_seconds=time.perf_counter()-began,algorithm_completion_claim=False,
                meaning='controller returned; inspect every task status, timeouts and partials before quality claims')
            atomic(attempt/'receipt.json',record);process=None
            if code:raise RuntimeError('Controller failed: '+name)
        state.update(status='MEASUREMENTS_TERMINAL_ANALYSIS_PENDING',child_pid=None,updated_utc=utc())
    except BaseException as error:
        if process is not None and process.poll() is None:
            os.kill(process.pid,signal.SIGINT)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                state['cleanup_pending_controller_pid']=process.pid
        state.update(status='INTERRUPTED' if isinstance(error,KeyboardInterrupt) else 'WORKFLOW_ERROR',error=repr(error),updated_utc=utc(),next_command=current_command)
        recovery=ROOT/'RESUME.md'
        with recovery.open('a') as stream:stream.write('\n工作流恢复状态：'+json.dumps(state,ensure_ascii=False)+'\n')
        raise
    finally:
        atomic(directory/'STATE.json',state);lock.unlink(missing_ok=True)

if __name__=='__main__':main()
