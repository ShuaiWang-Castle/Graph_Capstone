"""Canonical recovery gate: never duplicate an owned live measurement cohort."""
from pathlib import Path
import argparse,datetime,fcntl,hashlib,json,os,signal,subprocess,sys,time
import psutil
ROOT=Path(__file__).resolve().parents[1]
MARKERS=['experiments/serial_workflow.py','experiments/resume_workflow.py',
 'experiments/schedule.py','experiments/worker.py','experiments/m6_prepared/run.py',
 'experiments/m6_prepared/worker.py','experiments/run_m6_compressed.py',
 'experiments/m5/run_serial.py','experiments/m5/worker.py','experiments/run_m5_archived.py',
 'zrhfd/baselines/native_driver.jl','work/bin/mincut128']

def live_owned():
    targets=set(MARKERS)|{str(ROOT/p) for p in MARKERS};rows=[]
    for process in psutil.process_iter(['pid','cmdline','cwd','create_time']):
        if process.pid==os.getpid():continue
        try:
            command=process.info['cmdline'] or []
            if process.info['cwd']==str(ROOT) and any(value in targets for value in command):
                rows.append({'pid':process.pid,'create_time':process.info['create_time'],'argv':command,'cwd':str(ROOT)})
        except (psutil.Error,TypeError):pass
    return rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state',default='results/serial_workflow_v003');parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    directory=(ROOT/args.state).resolve()
    if not directory.is_relative_to(ROOT/'results'):
        parser.error('Recovery state must be within this project results directory')
    live=live_owned()
    if not args.execute:
        print(json.dumps({'read_only':True,'owned_live_processes':live,'safe_to_start':not live},indent=2));return
    if live:
        print(json.dumps({'status':'ACTIVE_EXISTING_WORK','new_measurement_started':False,'owned_live_processes':live},indent=2));raise SystemExit(3)
    lease=ROOT/'results/measurement_workflow_lease.lock';lease.parent.mkdir(exist_ok=True)
    with lease.open('a+') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another recovery launcher owns the project measurement lease')
        live=live_owned()
        if live:raise RuntimeError('A recorded measurement started during recovery gate; inspect its durable state')
        stream.seek(0);stream.truncate();json.dump({'launcher_pid':os.getpid(),'actual_argv':sys.argv,'created_unix':time.time()},stream);stream.flush()
        command=[str(ROOT/'.venv/bin/python'),'experiments/serial_workflow.py','--state',args.state,'--execute']
        # Own the workflow lifecycle explicitly. Python subprocess.call kills
        # its child on KeyboardInterrupt, bypassing the workflow's cleanup.
        receipt_directory=ROOT/'results/recovery_launches'/f'{time.time_ns()}_{os.getpid()}'
        receipt_directory.mkdir(parents=True)
        record={'launcher_pid':os.getpid(),'actual_argv':sys.argv,'workflow_argv':command,
                'launcher_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'status':'STARTED','received_signals':[],'cleanup_signal_sent':False}
        process=None
        def save():
            target=receipt_directory/'STATE.json';temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps(record,indent=2)+'\n');os.replace(temporary,target)
        def forward_once():
            if record['received_signals'] and not record['cleanup_signal_sent'] and process is not None and process.poll() is None:
                try:
                    process.send_signal(signal.SIGINT)
                    record['cleanup_signal_sent']=True
                except ProcessLookupError:pass
        def stopping(signum,frame):
            record['received_signals'].append({'received':signum,'at_unix':time.time()})
            forward_once()
            save()
        previous={s:signal.signal(s,stopping) for s in (signal.SIGINT,signal.SIGTERM)}
        try:
            save()
            process=subprocess.Popen(command,cwd=ROOT,start_new_session=True)
            record['workflow_pid']=process.pid;forward_once();save()
            while process.poll() is None:
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:pass
            record.update(status='WORKFLOW_RETURNED',returncode=process.returncode,
                          ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          remaining_owned_live_processes=live_owned(),algorithm_completion_claim=False)
            save()
            raise SystemExit(process.returncode)
        finally:
            for s,handler in previous.items():signal.signal(s,handler)

if __name__=='__main__':main()
