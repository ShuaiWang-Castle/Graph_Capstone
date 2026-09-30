#!/usr/bin/env python3
"""Bounded continuation: wait on candidate runner, then serial author control and analyses.

No candidate job is restarted. The author reference cross-check starts only
after all candidate records exist and the verified original runner exits.
"""
from pathlib import Path
import argparse, datetime, os, signal, subprocess, sys, time, traceback
import psutil
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.io import read_json, write_json


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--create-time', type=float, required=True)
    parser.add_argument('--candidate-plan', required=True)
    parser.add_argument('--candidate-run-root', required=True)
    parser.add_argument('--reference-plan', required=True)
    parser.add_argument('--reference-run-root', required=True)
    args = parser.parse_args()
    state = read_json(ROOT / 'work/state.json')
    deadline = datetime.datetime.fromisoformat(state['deadline'])
    diary = ROOT / 'work/candidate_continuation_diary.json'
    events = []
    current_command = None

    def event(stage, **fields):
        events.append({'at_utc': now().isoformat(), 'stage': stage, **fields})
        write_json(diary, {'deadline': deadline.isoformat(), 'events': events})
        print(stage, fields, flush=True)

    def check_deadline():
        if now() >= deadline:
            raise TimeoutError('Whole-round deadline reached; it was not reset')

    def command(argv):
        nonlocal current_command
        check_deadline()
        current_command = [sys.executable, *argv]
        event('COMMAND_START', command=current_command)
        # Analysis/runner children inherit one-thread environment. Native jobs
        # are additionally supervised by lab.runner's RAM and deadline limits.
        remaining = (deadline - now()).total_seconds()
        if remaining <= 8:
            raise TimeoutError('No time left for a command and bounded cleanup')
        child = subprocess.Popen(current_command, cwd=ROOT, env=environment,
                                 start_new_session=(os.name == 'posix'))
        child_identity = psutil.Process(child.pid).create_time()
        try:
            code = child.wait(timeout=remaining - 8)
        except BaseException:
            # Signal this owned runner first so lab.runner can stop its native
            # session and preserve INTERRUPTED + the last valid checkpoint.
            owned = []
            try:
                parent = psutil.Process(child.pid)
                if abs(parent.create_time() - child_identity) < .001:
                    owned = [(q.pid, q.create_time()) for q in parent.children(recursive=True)]
                    parent.send_signal(signal.SIGINT)
            except psutil.NoSuchProcess:
                pass
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                pass
            # Any surviving algorithm lives in a separate native session. Only
            # the pre-signal verified descendants are eligible for cleanup.
            for pid, created in reversed(owned):
                try:
                    q = psutil.Process(pid)
                    if abs(q.create_time() - created) < .001:
                        q.terminate()
                except psutil.NoSuchProcess:
                    pass
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=1)
            for pid, created in reversed(owned):
                try:
                    q = psutil.Process(pid)
                    if abs(q.create_time() - created) < .001:
                        q.kill()
                except psutil.NoSuchProcess:
                    pass
            event('OWNED_COMMAND_CLEANUP_COMPLETED', child_pid=child.pid)
            raise
        if code != 0:
            raise subprocess.CalledProcessError(code, current_command)
        event('COMMAND_COMPLETED', command=current_command)

    environment = os.environ.copy()
    for key in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS']:
        environment[key] = '1'
    try:
        verified_observations = 0
        while True:
            check_deadline()
            try:
                process = psutil.Process(args.pid)
                identity_matches = abs(process.create_time() - args.create_time) < .001
                if not identity_matches or process.status() == psutil.STATUS_ZOMBIE:
                    break
                cmdline = process.cmdline()
                if 'tools/run_jobs.py' not in cmdline or args.candidate_plan not in cmdline:
                    raise RuntimeError('Live process identity has unexpected command')
                verified_observations += 1
                if verified_observations == 1:
                    event('ORIGINAL_RUNNER_VERIFIED_LIVE', pid=args.pid,
                          create_time=args.create_time, command=cmdline)
            except psutil.NoSuchProcess:
                break
            time.sleep(min(10, max(0, (deadline - now()).total_seconds())))
        plan = read_json(ROOT / args.candidate_plan)
        missing = [j['job_id'] for j in plan['jobs'] if not (ROOT / args.candidate_run_root / j['job_id'] / 'result.json').exists()]
        if missing:
            raise RuntimeError('Candidate runner ended with missing terminal records; do not restart automatically: ' + repr(missing))
        event('ALL_CANDIDATE_DEV_RESULTS_PRESENT', count=len(plan['jobs']), verified_live_observations=verified_observations)
        catalog = 'work/dev_lfr/catalog.json'
        command(['tools/run_jobs.py','--plan',args.reference_plan,'--run-root',args.reference_run_root])
        for phase_plan,phase_root,output in [(args.candidate_plan,args.candidate_run_root,'analysis/nocd_pairdot_dev_all_v1'),(args.reference_plan,args.reference_run_root,'analysis/nocd_author_refcheck73_v1')]:
            command(['tools/summarize.py','--catalog',catalog,'--plan',phase_plan,'--run-root',phase_root,'--output',output,'--plot'])
            command(['tools/summarize_extended.py','--catalog',catalog,'--plan',phase_plan,'--run-root',phase_root,'--analysis',output])
        event('CANDIDATE_DEV_AND_AUTHOR_CONTROL_FINISHED_ROOT_GATE_REVIEW_REQUIRED')
    except BaseException as exc:
        event('CONTINUATION_STOPPED', error=repr(exc), next_command=current_command,
              traceback=traceback.format_exc())
        with (ROOT / 'RESUME.md').open('a', encoding='utf-8') as stream:
            stream.write('\n\nContinuation stopped at ' + now().isoformat() + ': ' + repr(exc)
                         + '\nInspect work/candidate_continuation_diary.json; do not reset deadline or restart a live runner.\n')
        raise


if __name__ == '__main__':
    main()
