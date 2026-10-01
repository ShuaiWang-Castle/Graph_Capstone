"""Hold only the owned orchestrator; its measured child continues unchanged."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,signal
import psutil
ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');os.replace(temporary,path)
def identity(pid):
    p=psutil.Process(pid)
    return {'pid':pid,'create_time':p.create_time(),'argv':p.cmdline(),'cwd':p.cwd()}
def same_process(expected):
    actual=identity(expected['pid'])
    if actual!=expected:raise RuntimeError('Owned process identity changed; no signal sent')
    return psutil.Process(expected['pid'])
def alive(expected):
    if not psutil.pid_exists(expected['pid']):return False
    p=psutil.Process(expected['pid'])
    return p.create_time()==expected['create_time'] and p.status()!=psutil.STATUS_ZOMBIE
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group();group.add_argument('--hold',action='store_true');group.add_argument('--release',action='store_true');group.add_argument('--interrupt',action='store_true')
    parser.add_argument('--state',default='results/serial_workflow_v003/STATE.json')
    parser.add_argument('--receipt',default='results/orchestration/m6_analysis_barrier_v001.json')
    args=parser.parse_args();receipt=(ROOT/args.receipt).resolve();state_path=(ROOT/args.state).resolve()
    if not receipt.is_relative_to(ROOT/'results/orchestration') or not state_path.is_relative_to(ROOT/'results'):
        parser.error('Barrier metadata must remain inside its project scopes')
    if args.hold:
        if receipt.exists():raise RuntimeError('Existing barrier receipt retained; refuse overwrite')
        state=read(state_path);owner=identity(state['controller_pid']);child=identity(state['child_pid'])
        source=ROOT/'experiments/serial_workflow.py';launch=read(state_path.parent/'LAUNCH.json')
        if state['current_stage']!='m6_prepared' or state['status']!='ACTIVE' or owner['cwd']!=str(ROOT) or child['cwd']!=str(ROOT):
            raise RuntimeError('Only the owned active M6 orchestration stage may be held')
        if 'experiments/serial_workflow.py' not in owner['argv'] or '--execute' not in owner['argv'] or '--state' not in owner['argv']:
            raise RuntimeError('Owner argv is not the canonical workflow')
        if owner['argv'][owner['argv'].index('--state')+1]!=str(state_path.parent.relative_to(ROOT)) or sha(source)!=launch['workflow_source_sha256']:
            raise RuntimeError('Owner state or source identity differs')
        if owner['argv'][1:]!=launch['actual_argv']:
            raise RuntimeError('Full workflow script argv differs from its original launch')
        if 'experiments/run_m6_compressed.py' not in child['argv'] or '--run' not in child['argv']:
            raise RuntimeError('The current measured child is not the frozen M6 wrapper')
        receipt.parent.mkdir(parents=True,exist_ok=True)
        record={'schema_version':1,'status':'PREPARED','created_utc':stamp(),'owner':owner,'measured_child':child,
                'state_path':str(state_path.relative_to(ROOT)),'workflow_source_sha256':sha(source),
                'hold_helper_source_sha256':sha(__file__),'hold_actual_command':list(os.sys.argv),
                'reason':'Serial offline audit window after the current M6 child ends; child timers and budgets unchanged',
                'signals_target_orchestrator_only':True,'algorithm_completion_claim':False}
        save(receipt,record)
        with (ROOT/'RESUME.md').open('a') as stream:
            stream.write('\n阶段核验屏障：父调度器将暂挂，M6测量子进程继续。记录 '+str(receipt.relative_to(ROOT))+'；不要重复启动workflow。只有记录中的M6 child已退出，才有离线CPU窗口。核验后执行 `.venv/bin/python experiments/stage_barrier.py --release`；要中断整个本项目工作流执行 `--interrupt`（先SIGINT后唤醒同一owned父进程），均会核PID/create_time/cwd/argv。goal仍ACTIVE。\n')
        same_process(owner);os.kill(owner['pid'],signal.SIGSTOP)
        record.update(status='HELD',held_utc=stamp());save(receipt,record)
        print(json.dumps({'status':'HELD','orchestrator_pid':owner['pid'],'measured_child_continues':child['pid']}));return
    record=read(receipt);p=same_process(record['owner'])
    if sha(ROOT/'experiments/serial_workflow.py')!=record['workflow_source_sha256']:
        raise RuntimeError('Workflow source changed; refuse signal')
    if args.release or args.interrupt:
        stopped=p.status()==psutil.STATUS_STOPPED
        if not stopped and record['status'] in ('RELEASE_REQUESTED','RELEASED','INTERRUPT_REQUESTED','INTERRUPTED_PENDING_CLEANUP'):
            # Never send another interrupt to an already resumed cleanup loop.
            print(json.dumps({'status':record['status'],'owner_status':p.status(),
                              'recovery':'Already resumed; inspect owned workflow state/child termination',
                              'signals_sent':0,'algorithm_completion_claim':False}));return
        allowed={'PREPARED','HELD','INTERRUPT_REQUESTED','INTERRUPTED_PENDING_CLEANUP'} if args.interrupt else {'PREPARED','HELD','RELEASE_REQUESTED','RELEASED'}
        if record['status'] not in allowed or not stopped:raise RuntimeError('Barrier is not held for this action; no signal sent')
        if args.release and alive(record['measured_child']):raise RuntimeError('Measured child still live; no offline window or release yet')
        record.update(status='INTERRUPT_REQUESTED' if args.interrupt else 'RELEASE_REQUESTED',signal_utc=stamp());save(receipt,record)
        same_process(record['owner'])
        # While the same owner remains SIGSTOPPED, standard pending SIGINTs
        # coalesce. This covers a crash before/after delivery but before CONT.
        if args.interrupt:os.kill(p.pid,signal.SIGINT)
        os.kill(p.pid,signal.SIGCONT)
        record.update(status='INTERRUPTED_PENDING_CLEANUP' if args.interrupt else 'RELEASED',released_utc=stamp());save(receipt,record)
    print(json.dumps({'status':record['status'],'owner_status':p.status(),'measured_child_live':alive(record['measured_child']),'algorithm_completion_claim':False}))

if __name__=='__main__':main()
