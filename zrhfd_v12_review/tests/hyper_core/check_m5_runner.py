"""Real watchdog processes and latest toy artifacts; no formal timing claims."""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import psutil
import sys
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.m5.inputs import config,digest,immutable_json
from experiments.m5.run_serial import run_one


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='results/m5/watchdog_v12_001');parser.add_argument('--toy-run',default='results/m5/toy_numba_v12_002');args=parser.parse_args()
    root=PROJECT/args.output;root.mkdir(parents=True,exist_ok=True);violations=[];cases=[]
    expected={'normal':'COMPLETED','nonzero':'FAILED','malformed_progress':'FAILED','malformed_result':'FAILED','timeout':'TIMEOUT','memory':'MEMORY_LIMIT'}
    for kind,wanted in expected.items():
        c=deepcopy(config());c['budgets']['wall_seconds_per_method_query']=1.2 if kind=='timeout' else 3.;c['budgets']['memory_bytes']=32*1024*1024 if kind=='memory' else 12000000000
        task={'task_id':'fixture_'+kind,'toy':True,'fixture':kind,'method':'hfd_no_volume','query':{'query_id':'fixture_'+kind,'seed_zero_based':0}}
        context={'purpose':'controlled real-process watchdog/storage fixture, not a clustering experiment','fixture_source':'tests/hyper_core/runner_fixture_worker.py','fixture_source_sha256':digest('tests/hyper_core/runner_fixture_worker.py'),'runner_source_sha256':digest('experiments/m5/run_serial.py')}
        receipt=run_one(root/kind,task,c,'numba',context,'tests/hyper_core/runner_fixture_worker.py')
        if receipt['status']!=wanted:violations.append(kind+' status')
        if not (root/kind/'execution_request.json').exists():violations.append(kind+' execution context')
        if not receipt.get('last_truth_free_baseline_checkpoint'):violations.append(kind+' checkpoint lost')
        if kind=='nonzero' and (receipt['exit_code']!=7 or receipt['worker_status']!='COMPLETED'):violations.append('nonzero raw completion not preserved')
        if kind=='malformed_progress' and not receipt['progress_parse_errors']:violations.append('malformed checkpoint error lost')
        if kind=='timeout':
            pid=json.loads((root/kind/'fixture_child.json').read_text())['pid']
            alive=psutil.pid_exists(pid) and psutil.Process(pid).status()!=psutil.STATUS_ZOMBIE
            if alive:violations.append('timeout descendant survived process-group termination')
            receipt=dict(receipt,fixture_descendant_running_after_termination=alive)
        cases.append({'fixture':kind,'expected':wanted,'receipt':receipt})
    toy=PROJECT/args.toy_run;rows=[]
    for path in sorted(toy.glob('queries/*/attempt_000/worker_result.json')):
        result=json.loads(path.read_text());receipt=json.loads((path.parent/'receipt.json').read_text());method=result['task']['method']
        if receipt['status']!='COMPLETED' or receipt['exit_code']!=0:violations.append(method+' toy completion')
        events=[json.loads(p.read_text()) for p in sorted((path.parent/'progress').glob('*.json'))]
        actual=[e['payload'] for e in events if e['event']=='baseline_progress']
        if method not in ['zr_hfd','zh_prov'] and not actual:violations.append(method+' actual callbacks absent')
        if any(e.get('truth_used') is not False for e in events if e['event']=='baseline_progress'):violations.append(method+' checkpoint truth flag')
        rows.append({'method':method,'status':receipt['status'],'actual_callback_count':len(actual),'completed_trial_checkpoints':sum(e.get('stage')=='trial_finished' for e in actual),'contains_seed':result['output']['contains_seed'],'oracle_volume_policy':result['output'].get('metadata',{}).get('oracle'),'last_actual_callback':actual[-1] if actual else None})
    if len(rows)!=8:violations.append('8-method toy count')
    manifest=json.loads((toy/'manifest.json').read_text());pins=manifest['frozen']['source_pins']
    for relative,sha in pins.items():
        snapshot=toy/'sources'/relative
        if not snapshot.exists() or __import__('hashlib').sha256(snapshot.read_bytes()).hexdigest()!=sha:violations.append('source snapshot '+relative)
    evidence={'schema_version':1,'status':'PASS' if not violations else 'FAIL','violations':violations,'watchdog_fixtures':cases,'actual_toy_interfaces':rows,'toy_frozen_sha256':manifest['frozen_sha256'],'toy_source_snapshot_count':len(pins),'formal_measurement':False,'headline_timing_claim':False,'source_sha256':digest('tests/hyper_core/check_m5_runner.py')}
    immutable_json(root/'summary.json',evidence);print(json.dumps({'status':evidence['status'],'violations':violations,'watchdog_cases':len(cases),'toy_methods':len(rows)}))
    if violations:raise SystemExit(1)


if __name__=='__main__':main()
