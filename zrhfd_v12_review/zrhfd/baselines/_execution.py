"""Immutable logs for actual CPU Julia invocations, including partial timeout output."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import subprocess
import time
import uuid
from ._common import ROOT


def execute_julia(args, config, deadline, sources):
    directory = Path(config.get('artifact_directory', 'reviews/baselines/execution_logs'))
    if directory.is_absolute() or not (ROOT/directory).resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('artifact_directory must be a relative directory within the project')
    run = ROOT/directory/('native_'+uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    environment_delta = {'JULIA_DEPOT_PATH':str(ROOT/'external/runtime/julia-depot'),'JULIA_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','JULIA_PKG_PRECOMPILE_AUTO':'0'}
    environment = dict(os.environ)
    environment.update(environment_delta)
    receipt = {'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_command':args,'environment_overrides':environment_delta,'sources':sources,'driver_sha256':hashlib.sha256(Path(args[4]).read_bytes()).hexdigest(),'status':'STARTED','graph_source_path':config.get('graph_source_path'),'stdout_path':str((run/'stdout.txt').relative_to(ROOT)),'stderr_path':str((run/'stderr.txt').relative_to(ROOT)),'output_live_to_files':True}
    input_edge_path = Path(args[7])
    receipt['input_edge_csv_sha256'] = hashlib.sha256(input_edge_path.read_bytes()).hexdigest()
    commandpath = run/'execution.json'
    commandpath.write_text(json.dumps(receipt,indent=2)+'\n')
    returncode = None
    started = time.perf_counter()
    remaining = deadline-started
    # Live files also retain author output if the outer task scheduler kills
    # this worker just before its internal timeout handler can finish.
    with (run/'stdout.txt').open('xb') as output, (run/'stderr.txt').open('xb') as errors:
        if remaining<=0:
            status='TIMEOUT'
        else:
            try:
                process = subprocess.Popen(args,stdout=output,stderr=errors,env=environment)
                try:
                    returncode = process.wait(timeout=remaining)
                    status='COMPLETED' if returncode==0 else 'FAILED'
                except subprocess.TimeoutExpired:
                    process.kill()
                    returncode = process.wait()
                    status='TIMEOUT'
            except Exception as exc:
                errors.write((type(exc).__name__+': '+str(exc)).encode())
                status='FAILED'
    stdout,stderr=(run/'stdout.txt').read_bytes(),(run/'stderr.txt').read_bytes()
    trials, parsing_errors = [], []
    for line in stdout.decode('utf-8',errors='replace').splitlines():
        if line.startswith('{'):
            try:
                trials.append(json.loads(line))
            except (ValueError,TypeError) as exc:
                parsing_errors.append(str(exc))
    receipt.update(finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),status=status,returncode=returncode,subprocess_wall_seconds=time.perf_counter()-started,complete_json_records=len(trials),json_parse_errors=parsing_errors,stdout_sha256=hashlib.sha256(stdout).hexdigest(),stderr_sha256=hashlib.sha256(stderr).hexdigest(),stdout_bytes=len(stdout),stderr_bytes=len(stderr))
    commandpath.write_text(json.dumps(receipt,indent=2)+'\n')
    logs={key:str(path.relative_to(ROOT)) for key,path in {'execution':commandpath,'stdout':run/'stdout.txt','stderr':run/'stderr.txt'}.items()}
    if status=='FAILED':
        raise RuntimeError('Author baseline failed; complete invocation logs at '+logs['execution']+'; '+stderr.decode('utf-8',errors='replace')[-2000:])
    if parsing_errors and status=='COMPLETED':
        raise RuntimeError('Author output parse failure; retained logs at '+logs['execution'])
    return trials, {'status':status,'returncode':returncode,'logs':logs,'subprocess_wall_seconds':receipt['subprocess_wall_seconds'],'source_stderr':stderr.decode('utf-8',errors='replace')[-1000:] or None,'json_parse_errors':parsing_errors}
